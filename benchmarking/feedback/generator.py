"""Generate structured feedback benchmark episodes from corruption manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

CONFIRM_MUTATION_TYPES = {
    "caption_chart_type_mismatch",
    "data_numeric_delta",
    "numeric_delta",
    "range_delta",
    "trend_flip",
    "title_theme_drift",
    "linked_numeric_delta",
}

SCOPE_MUTATION_TYPES = {
    "caption_scope_year",
    "caption_scope_city",
    "caption_scope_object",
    "summary_scope_year",
    "summary_scope_city",
    "summary_scope_object",
}

LOGIC_MUTATION_TYPES = {
    "series_metric_swap",
    "table_metric_swap",
}

ACTION_PRIORITY = {
    "page_intent_correction": 4,
    "logic_correction": 3,
    "scope_correction": 2,
    "confirm": 1,
}

SCOPE_FIELDS_BY_MUTATION = {
    "caption_scope_year": {"start_year", "end_year"},
    "summary_scope_year": {"start_year", "end_year"},
    "caption_scope_city": {"city"},
    "summary_scope_city": {"city"},
    "caption_scope_object": {"block"},
    "summary_scope_object": {"block"},
}


def parse_args() -> argparse.Namespace:
    """Parse CLI args for episode generation."""
    parser = argparse.ArgumentParser(
        description="Generate structured feedback episodes from corruption manifests."
    )
    parser.add_argument(
        "--benchmark-root",
        type=Path,
        required=True,
        help="Benchmark root containing manifest/corruptions.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSONL path. Defaults to <benchmark-root>/feedback/episodes.jsonl",
    )
    return parser.parse_args()


def load_yaml(path: Path) -> dict:
    """Load a YAML file as a dictionary."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def mutation_action(mutation_type: str) -> str | None:
    """Map a mutation type to its default expected action."""
    if mutation_type in SCOPE_MUTATION_TYPES:
        return "scope_correction"
    if mutation_type in LOGIC_MUTATION_TYPES:
        return "logic_correction"
    if mutation_type in CONFIRM_MUTATION_TYPES:
        return "confirm"
    return None


def derive_expected_action(operations: list[dict]) -> str | None:
    """Derive a single expected action from a list of corruption operations."""
    targets = {operation["target"] for operation in operations}
    if targets == {"st.body", "summary", "title"}:
        return "page_intent_correction"

    best_action = None
    best_priority = -1
    for operation in operations:
        action = mutation_action(operation["mutation_type"])
        if action is None:
            return None
        priority = ACTION_PRIORITY[action]
        if priority > best_priority:
            best_action = action
            best_priority = priority
    return best_action


def action_target_label(operations: list[dict]) -> str:
    """Map operations to a compact confirm target label."""
    targets = {operation["target"] for operation in operations}
    if targets == {"summary"}:
        return "summary"
    if targets == {"title"}:
        return "title"
    if targets == {"st.header"}:
        return "st.header"
    if targets == {"st.caption"}:
        return "caption"
    if targets == {"st.body"}:
        return "st.body"
    if targets == {"st.body", "summary"}:
        return "st.body+summary"
    if targets == {"summary", "title"}:
        return "summary+title"
    if targets == {"st.body", "summary", "title"}:
        return "st.body+summary+title"
    return "+".join(sorted(targets))


def scope_required_fields(operations: list[dict]) -> list[str]:
    """Collect required scope fields from scope-related mutations."""
    fields: set[str] = set()
    for operation in operations:
        fields.update(SCOPE_FIELDS_BY_MUTATION.get(operation["mutation_type"], set()))
    ordered = ["city", "block", "start_year", "end_year"]
    return [field for field in ordered if field in fields]


def build_scope_reply(gt_yaml: dict, required_fields: list[str]) -> dict:
    """Build structured scope reply from GT query filters."""
    query_filters = gt_yaml["query_filters"]
    reply: dict[str, str | int] = {}
    if "city" in required_fields:
        reply["city"] = query_filters["city"]
    if "block" in required_fields:
        reply["block"] = query_filters["block"]
    if "start_year" in required_fields:
        reply["start_year"] = int(str(query_filters["start_date"])[:4])
    if "end_year" in required_fields:
        reply["end_year"] = int(str(query_filters["end_date"])[:4])
    return reply


def build_page_intent_reply(gt_yaml: dict) -> dict:
    """Build structured page intent reply from GT scope and title."""
    query_filters = gt_yaml["query_filters"]
    title_text = ""
    for element in gt_yaml.get("template_slide", {}).get("elements", []):
        if element.get("role") == "slide-title":
            title_text = element.get("text", "")
            break
    return {
        "page_intent": {
            "scope": {
                "city": query_filters["city"],
                "block": query_filters["block"],
                "start_year": int(str(query_filters["start_date"])[:4]),
                "end_year": int(str(query_filters["end_date"])[:4]),
            },
            "topic": title_text,
        }
    }


def build_episode(
    benchmark_root: Path,
    record: dict,
    episode_id: str,
) -> dict | None:
    """Build a feedback episode from one corruption manifest record."""
    operations = record["operations"]
    expected_action = derive_expected_action(operations)
    if expected_action is None:
        return None

    gt_yaml_path = benchmark_root / record["source_yaml"]
    gt_yaml = load_yaml(gt_yaml_path)
    episode = {
        "episode_id": episode_id,
        "sample_ref": record["output_yaml"],
        "corruption_ref": record["corruption_json"],
        "turns": [],
        "grading_spec": {
            "evaluate_action_sequence": True,
            "evaluate_final_repair": True,
            "max_turns": 1,
        },
    }

    if expected_action == "confirm":
        episode["turns"] = [
            {
                "expected_action": "confirm",
                "action_payload": {
                    "confirm_target": [action_target_label(operations)]
                },
                "user_reply": {"confirm": True},
            }
        ]
        return episode

    if expected_action == "scope_correction":
        action_payload = {"required_fields": scope_required_fields(operations)}
        if any(
            operation["mutation_type"] == "caption_chart_type_mismatch"
            for operation in operations
        ):
            action_payload["confirm_target"] = ["caption"]
        episode["turns"] = [
            {
                "expected_action": "scope_correction",
                "action_payload": action_payload,
                "user_reply": build_scope_reply(
                    gt_yaml, action_payload["required_fields"]
                ),
            }
        ]
        return episode

    if expected_action == "logic_correction":
        template_id = gt_yaml.get("meta", {}).get("template_id")
        if template_id in {
            "T05_Resale_Summary_Table",
            "T05_Resale_Summary_Table_Alt",
        }:
            metrics = [
                {
                    "name": "trade_counts",
                    "meaning": "成交套数",
                    "agg_func": "count",
                },
                {
                    "name": "avg_unit_price",
                    "meaning": "平均单价",
                    "agg_func": "mean",
                },
                {
                    "name": "dim_area",
                    "meaning": "成交面积",
                    "agg_func": "sum",
                },
            ]
            group_by = "year"
        else:
            metrics = [
                {
                    "name": "Supply Count",
                    "meaning": "供应套数",
                    "agg_func": "count",
                },
                {
                    "name": "Sales Count",
                    "meaning": "成交套数",
                    "agg_func": "count",
                },
            ]
            group_by = "area_range"
        episode["turns"] = [
            {
                "expected_action": "logic_correction",
                "action_payload": {
                    "required_fields": ["metrics", "group_by"]
                },
                "user_reply": {
                    "metrics": metrics,
                    "group_by": group_by,
                },
            }
        ]
        return episode

    if expected_action == "page_intent_correction":
        episode["turns"] = [
            {
                "expected_action": "page_intent_correction",
                "action_payload": {
                    "required_fields": ["scope", "topic"]
                },
                "user_reply": build_page_intent_reply(gt_yaml),
            }
        ]
        return episode

    return None


def generate_feedback_episodes(
    benchmark_root: Path,
    output_path: Path | None = None,
) -> dict[str, int]:
    """Generate structured feedback episodes from a benchmark manifest."""
    manifest_path = benchmark_root / "manifest" / "corruptions.jsonl"
    if output_path is None:
        output_path = benchmark_root / "feedback" / "episodes.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    generated = 0
    skipped = 0
    with manifest_path.open("r", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]

    with output_path.open("w", encoding="utf-8") as handle:
        for index, record in enumerate(records, start=1):
            episode = build_episode(
                benchmark_root=benchmark_root,
                record=record,
                episode_id=f"ep_{index:06d}",
            )
            if episode is None:
                skipped += 1
                continue
            handle.write(json.dumps(episode, ensure_ascii=False) + "\n")
            generated += 1
    return {"generated": generated, "skipped": skipped}
