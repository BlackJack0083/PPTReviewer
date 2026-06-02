"""Generate structured feedback benchmark episodes from corruption manifests."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from tqdm.auto import tqdm

from benchmarking.fine_grained.common import (
    error_types_for_mutation,
    normalize_mutation_type,
)

DATA_SOURCE_FIELDS_BY_MUTATION = {
    "scope_time_range_shift": ["time_range"],
    "scope_city_substitution": ["city"],
    "scope_block_substitution": ["block"],
}

LOGIC_FIELDS_BY_MUTATION = {
    "chart_metric_label_swap": ["metrics"],
    "table_metric_label_swap": ["metrics"],
    "agg_func_swap": ["agg_func"],
    "metric_source_swap": ["metric_source"],
    "binning_step_swap": ["dimensions"],
}

UPDATE_CONFIRMATION_FIELDS_BY_MUTATION = {
    "numeric_value_perturbation": ["table_values"],
    "range_value_shift": ["table_values"],
    "trend_direction_flip": ["summary"],
    "presentation_type_substitution": ["presentation_type"],
}

TABLE_METRIC_RULES = {
    "trade_counts": {
        "source_col": "trade_sets",
        "agg_func": "count",
        "filter_condition": {"trade_sets": 1},
    },
    "avg_unit_price": {
        "source_col": "dim_unit_price",
        "agg_func": "mean",
        "filter_condition": {"trade_sets": 1},
    },
    "dim_area": {
        "source_col": "dim_area",
        "agg_func": "sum",
        "filter_condition": {"trade_sets": 1},
    },
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
        "--workers",
        type=int,
        default=min(32, (os.cpu_count() or 4) * 4),
        help="Number of worker threads for cleanup and feedback generation.",
    )
    return parser.parse_args()


@cache
def load_yaml(path: Path) -> dict:
    """Load a YAML file as a dictionary."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@cache
def load_csv_rows(path: Path) -> list[dict[str, str]]:
    """Load CSV rows as dictionaries."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def find_gt_element(gt_yaml: dict, element_id: str) -> dict | None:
    """Find a GT slide element by element id."""
    for element in gt_yaml.get("template_slide", {}).get("elements", []):
        if str(element.get("id")) == str(element_id):
            return element
    return None


def get_gt_title(gt_yaml: dict) -> str:
    """Return the GT slide title text."""
    for element in gt_yaml.get("template_slide", {}).get("elements", []):
        if element.get("role") == "slide-title":
            return str(element.get("text", ""))
    return ""


def get_gt_summary(gt_yaml: dict) -> str:
    """Return the GT slide summary/body text."""
    for element in gt_yaml.get("template_slide", {}).get("elements", []):
        if element.get("role") == "body-text":
            return str(element.get("text", ""))
    return ""


def fields_for_mutation(mutation_type: str) -> list[str] | None:
    """Map a mutation type to the state fields a client can provide."""
    mutation_type = normalize_mutation_type(mutation_type)
    if mutation_type in DATA_SOURCE_FIELDS_BY_MUTATION:
        return DATA_SOURCE_FIELDS_BY_MUTATION[mutation_type]
    if mutation_type in LOGIC_FIELDS_BY_MUTATION:
        return LOGIC_FIELDS_BY_MUTATION[mutation_type]
    if mutation_type in UPDATE_CONFIRMATION_FIELDS_BY_MUTATION:
        return UPDATE_CONFIRMATION_FIELDS_BY_MUTATION[mutation_type]
    return None


def table_index_for_operation(gt_yaml: dict, operation: dict) -> int:
    """Map an operation to the corresponding table in `analysis_state["tables"]`."""
    element_id = operation.get("element_id")
    structured_elements = [
        element
        for element in gt_yaml.get("template_slide", {}).get("elements", [])
        if str(element.get("role", "")).startswith("chart")
        or str(element.get("role", "")) == "table"
    ]
    if element_id is None:
        return 0
    for index, element in enumerate(structured_elements):
        if str(element.get("id")) == str(element_id):
            return index
    return 0


def build_data_source_state_patch(
    gt_yaml: dict,
    table_index: int,
    fields: list[str],
) -> dict:
    """Build a table-indexed data-source patch for requested slots only."""
    slide_filters = gt_yaml.get("slide_filters")
    if not isinstance(slide_filters, list) or table_index >= len(slide_filters):
        raise ValueError(f"GT slide_filters missing table_index={table_index}")

    source = slide_filters[table_index]
    filters = source.get("filters") or {}
    connection = source.get("connection") or {}
    requested = set(fields)
    table_patch: dict[str, Any] = {"index": table_index, "data_source": {}}

    if "city" in requested:
        table_patch["data_source"]["connection"] = {
            "table": _normalize_table_name(connection.get("table"))
        }

    filter_patch: dict[str, Any] = {}
    if "city" in requested:
        filter_patch["city"] = filters["city"]
    if "block" in requested:
        filter_patch["block"] = filters["block"]
    if "time_range" in requested:
        filter_patch["start_date"] = filters["start_date"]
        filter_patch["end_date"] = filters["end_date"]
    if filter_patch:
        table_patch["data_source"]["filters"] = filter_patch

    if not table_patch["data_source"]:
        raise ValueError(f"No data-source patch can be built for fields={fields}")
    return {"tables": [table_patch]}


def build_calculation_logic_state_patch(
    gt_yaml: dict,
    gt_yaml_path: Path,
    operation: dict,
    fields: list[str],
) -> dict:
    """Build a table-indexed calculation-logic patch for requested fields only."""
    table_index = table_index_for_operation(gt_yaml, operation)
    element = find_gt_element(gt_yaml, str(operation.get("element_id", "")))
    if element is None:
        raise ValueError(f"Cannot locate GT element for operation: {operation}")

    args = element.get("args") or {}
    if not args and element.get("role") == "table":
        args = build_table_args_from_csv(gt_yaml_path, element)
    requested = set(fields)
    logic: dict[str, Any] = {}
    if "metrics" in requested or "agg_func" in requested or "metric_source" in requested:
        logic["metrics"] = args.get("metrics", [])
    if "dimensions" in requested:
        logic["dimensions"] = args.get("dimensions", [])
    if "table_type" in args:
        logic["table_type"] = args["table_type"]

    if not logic:
        raise ValueError(f"No calculation-logic patch can be built for fields={fields}")
    return {"tables": [{"index": table_index, "calculation_logic": logic}]}


def build_table_args_from_csv(gt_yaml_path: Path, element: dict) -> dict:
    """Build static table logic for GT table slides that store rows as CSV."""
    data_ref = element.get("data")
    if not data_ref:
        raise ValueError(f"GT table element missing data path: {element}")

    rows = load_csv_rows((gt_yaml_path.parent / str(data_ref)).resolve())
    metrics = []
    for row in rows:
        metric_name = str(row.get("metric", "")).strip()
        if not metric_name:
            continue
        rule = TABLE_METRIC_RULES.get(metric_name)
        if rule is None:
            raise ValueError(f"Unsupported GT table metric={metric_name}")
        metrics.append({"name": metric_name, **rule})

    return {
        "table_type": "constraint-field",
        "metrics": metrics,
        "dimensions": [
            {
                "source_col": "date_code",
                "target_col": "year",
                "method": "period",
                "time_granularity": "year",
            }
        ],
    }


def build_update_confirmation_state_patch(
    gt_yaml: dict,
    mutation_type: str,
) -> dict:
    """Build optional state patch for content confirmations that need user text."""
    del gt_yaml, mutation_type
    return {}


def _normalize_table_name(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            raise ValueError("connection.table list is empty")
        value = value[0]
    table = str(value).strip().lower()
    if not table:
        raise ValueError("connection.table is empty")
    return table


def merge_patch(left: dict, right: dict) -> dict:
    """Merge nested state patches, including table-indexed patches."""
    merged = copy.deepcopy(left)
    for key, value in right.items():
        if key == "tables" and isinstance(value, list):
            merged[key] = _merge_table_patches(merged.get(key, []), value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _merge_table_patches(left: Any, right: list[dict]) -> list[dict]:
    if not isinstance(left, list):
        left = []
    merged = copy.deepcopy(left)
    positions = {
        item.get("index"): offset
        for offset, item in enumerate(merged)
        if isinstance(item, dict) and isinstance(item.get("index"), int)
    }
    for item in right:
        index = item.get("index")
        if isinstance(index, int) and index in positions:
            _deep_merge(merged[positions[index]], item)
        else:
            merged.append(copy.deepcopy(item))
    return merged


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def merge_fields(left: list[str], right: list[str]) -> list[str]:
    """Merge field lists while preserving first-seen order."""
    merged = list(left)
    for field in right:
        if field not in merged:
            merged.append(field)
    return merged


def feedback_item_for_operation(
    gt_yaml: dict,
    gt_yaml_path: Path,
    operation: dict,
) -> dict | None:
    """Build one feedback item from one corruption operation."""
    mutation_type = str(operation.get("mutation_type", ""))
    mutation_type = normalize_mutation_type(mutation_type)
    fields = fields_for_mutation(mutation_type)
    if fields is None:
        return None

    error_types = operation.get("error_types")
    if not isinstance(error_types, list) or not error_types:
        error_types = error_types_for_mutation(mutation_type)

    item = {
        "request_type": request_type_for_mutation(mutation_type),
        "table_index": table_index_for_operation(gt_yaml, operation),
        "error_types": sorted(str(label) for label in error_types),
        "targets": [str(operation["target"])],
        "fields": list(fields),
    }

    state_patch: dict = {}
    if mutation_type in DATA_SOURCE_FIELDS_BY_MUTATION:
        state_patch = build_data_source_state_patch(
            gt_yaml,
            table_index=item["table_index"],
            fields=item["fields"],
        )
    elif mutation_type in LOGIC_FIELDS_BY_MUTATION:
        state_patch = build_calculation_logic_state_patch(
            gt_yaml,
            gt_yaml_path,
            operation,
            fields=item["fields"],
        )
    elif mutation_type in UPDATE_CONFIRMATION_FIELDS_BY_MUTATION:
        item["decision"] = "revise" if mutation_type == "title_topic_substitution" else "accept"
        state_patch = build_update_confirmation_state_patch(gt_yaml, mutation_type)
    if state_patch:
        item["state_patch"] = state_patch
    return item


def request_type_for_mutation(mutation_type: str) -> str:
    """Return the client request type expected for one injected mutation."""
    if mutation_type in DATA_SOURCE_FIELDS_BY_MUTATION:
        return "data_source_slot_clarification"
    if mutation_type in LOGIC_FIELDS_BY_MUTATION:
        return "calculation_logic_clarification"
    if mutation_type in UPDATE_CONFIRMATION_FIELDS_BY_MUTATION:
        return "content_update_confirmation"
    if mutation_type in UPDATE_CONFIRMATION_FIELDS_BY_MUTATION:
        raise ValueError(f"Unhandled update confirmation mutation_type={mutation_type}")
    raise ValueError(f"Unsupported mutation_type={mutation_type}")


def merge_feedback_items(items: list[dict]) -> list[dict]:
    """Merge operation-level items by request type, table, target, and labels."""
    merged: dict[tuple[str, int | None, tuple[str, ...], str], dict] = {}
    for item in items:
        target = item["targets"][0]
        key = (
            item["request_type"],
            item.get("table_index"),
            tuple(item["error_types"]),
            target,
        )
        if key not in merged:
            merged[key] = {
                "request_type": item["request_type"],
                "table_index": item.get("table_index"),
                "error_types": item["error_types"],
                "targets": [target],
                "fields": list(item.get("fields", [])),
            }
            if item.get("decision"):
                merged[key]["decision"] = item["decision"]
            if item.get("state_patch"):
                merged[key]["state_patch"] = item["state_patch"]
            continue

        existing = merged[key]
        existing["fields"] = merge_fields(
            existing.get("fields", []),
            item.get("fields", []),
        )
        if item.get("state_patch"):
            existing["state_patch"] = merge_patch(
                existing.get("state_patch", {}),
                item["state_patch"],
            )
    return list(merged.values())


def build_episode(
    benchmark_root: Path,
    record: dict,
) -> dict | None:
    """Build a feedback episode from one corruption manifest record."""
    operations = record["operations"]
    gt_yaml_path = benchmark_root / record["source_yaml"]
    gt_yaml = load_yaml(gt_yaml_path)

    items = [
        item
        for operation in operations
        if (item := feedback_item_for_operation(gt_yaml, gt_yaml_path, operation))
        is not None
    ]
    if len(items) != len(operations):
        return None
    return {"feedback_items": merge_feedback_items(items)}


def cleanup_feedback_file(benchmark_root: Path, record: dict) -> int:
    """Delete stale feedback file for one record; return 1 if deleted else 0."""
    output_yaml_path = benchmark_root / str(record["output_yaml"])
    stale_path = output_yaml_path.parent / "feedback_episode.json"
    if stale_path.exists():
        stale_path.unlink()
        return 1
    return 0


def write_feedback_episode(
    benchmark_root: Path,
    record: dict,
) -> tuple[bool, str]:
    """Generate and write one case-local feedback episode."""
    episode = build_episode(
        benchmark_root=benchmark_root,
        record=record,
    )
    if episode is None:
        return False, str(record.get("split", "unknown"))
    output_yaml_path = benchmark_root / str(record["output_yaml"])
    case_dir = output_yaml_path.parent
    case_dir.mkdir(parents=True, exist_ok=True)
    feedback_path = case_dir / "feedback_episode.json"
    feedback_path.write_text(
        json.dumps(episode, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return True, str(record.get("split", "unknown"))


def generate_feedback_episodes(
    benchmark_root: Path,
    workers: int = min(32, (os.cpu_count() or 4) * 4),
) -> dict[str, int | dict[str, int]]:
    """Generate case-local feedback episodes from a benchmark manifest."""
    manifest_path = benchmark_root / "manifest" / "corruptions.jsonl"
    generated = 0
    skipped = 0

    print("Loading corruption manifest...")
    with manifest_path.open("r", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]

    print("Cleaning old feedback_episode.json files...")
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [
            executor.submit(cleanup_feedback_file, benchmark_root, record)
            for record in records
        ]
        for _ in tqdm(as_completed(futures), total=len(futures), desc="cleanup", unit="case"):
            pass

    by_split: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [
            executor.submit(write_feedback_episode, benchmark_root, record)
            for record in records
        ]
        with tqdm(total=len(futures), desc="feedback", unit="case") as progress:
            for future in as_completed(futures):
                written, split = future.result()
                if not written:
                    skipped += 1
                    progress.set_postfix(generated=generated, skipped=skipped)
                    progress.update(1)
                    continue
                generated += 1
                by_split[split] = by_split.get(split, 0) + 1
                progress.set_postfix(generated=generated, skipped=skipped)
                progress.update(1)

    return {"generated": generated, "skipped": skipped, "by_split": by_split}
