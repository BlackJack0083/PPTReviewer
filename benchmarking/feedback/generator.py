"""Generate structured feedback benchmark episodes from corruption manifests."""

from __future__ import annotations

import argparse
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

DATA_SOURCE_SCOPE_ERROR_TYPES_BY_MUTATION = {
    "scope_time_range_shift": "error",
    "scope_city_substitution": "unmatch",
    "scope_block_substitution": "unmatch",
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


def build_data_source_response(
    gt_yaml: dict,
    table_index: int,
    field: str,
) -> str:
    """Build a client-like reply for one data-source slot."""
    slide_filters = gt_yaml.get("slide_filters")
    if not isinstance(slide_filters, list) or table_index >= len(slide_filters):
        raise ValueError(f"GT slide_filters missing table_index={table_index}")

    source = slide_filters[table_index]
    filters = source.get("filters") or {}
    connection = source.get("connection") or {}
    if field == "city":
        return (
            "Please use "
            f"table={_normalize_table_name(connection.get('table'))}, "
            f"city={filters['city']}."
        )
    if field == "block":
        return f"Please use block={filters['block']}."
    if field == "time_range":
        return (
            "Please use "
            f"start_date={filters['start_date']}, "
            f"end_date={filters['end_date']}."
        )
    raise ValueError(f"Unsupported data-source field={field}")


def build_calculation_logic_response(
    gt_yaml: dict,
    gt_yaml_path: Path,
    operation: dict,
) -> str:
    """Build a client-like reply with the GT function logic."""
    element = find_gt_element(gt_yaml, str(operation.get("element_id", "")))
    if element is None:
        raise ValueError(f"Cannot locate GT element for operation: {operation}")

    args = element.get("args") or {}
    if not args and element.get("role") == "table":
        args = build_table_args_from_csv(gt_yaml_path, element)
    logic = {}
    if "table_type" in args:
        logic["table_type"] = args["table_type"]
    if "metrics" in args:
        logic["metrics"] = args["metrics"]
    if "dimensions" in args:
        logic["dimensions"] = args["dimensions"]
    if not logic:
        raise ValueError(f"No calculation logic can be built for operation: {operation}")
    return "Please use calculation_logic=" + json.dumps(logic, ensure_ascii=False) + "."


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


def _normalize_table_name(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            raise ValueError("connection.table list is empty")
        value = value[0]
    table = str(value).strip().lower()
    if not table:
        raise ValueError("connection.table is empty")
    return table


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

    table_index = table_index_for_operation(gt_yaml, operation)
    item = {
        "request_type": request_type_for_mutation(mutation_type),
        "error_type": sorted(str(label) for label in error_types)[0],
        "target": str(operation["target"]),
        "field": fields[0],
    }

    if mutation_type in DATA_SOURCE_FIELDS_BY_MUTATION:
        item["scope_error_type"] = DATA_SOURCE_SCOPE_ERROR_TYPES_BY_MUTATION[mutation_type]
        item["response"] = build_data_source_response(
            gt_yaml,
            table_index=table_index,
            field=item["field"],
        )
    elif mutation_type in LOGIC_FIELDS_BY_MUTATION:
        item["response"] = build_calculation_logic_response(
            gt_yaml,
            gt_yaml_path,
            operation,
        )
    elif mutation_type in UPDATE_CONFIRMATION_FIELDS_BY_MUTATION:
        item["response"] = "Yes, please apply the proposed update."
    return item


def request_type_for_mutation(mutation_type: str) -> str:
    """Return the client request type expected for one injected mutation."""
    if mutation_type in DATA_SOURCE_FIELDS_BY_MUTATION:
        return "data_source_slot_clarification"
    if mutation_type in LOGIC_FIELDS_BY_MUTATION:
        return "calculation_logic_clarification"
    if mutation_type in UPDATE_CONFIRMATION_FIELDS_BY_MUTATION:
        return "content_update_confirmation"
    raise ValueError(f"Unsupported mutation_type={mutation_type}")


def merge_feedback_items(items: list[dict]) -> list[dict]:
    """Merge duplicate operation-level items with the same request label."""
    merged: dict[tuple[str, str, str, str, str], dict] = {}
    for item in items:
        key = (
            item["request_type"],
            item["error_type"],
            str(item.get("scope_error_type", "")),
            item["target"],
            item["field"],
        )
        if key not in merged:
            merged[key] = {
                "request_type": item["request_type"],
                "error_type": item["error_type"],
                "target": item["target"],
                "field": item["field"],
                "response": item["response"],
            }
            if "scope_error_type" in item:
                merged[key]["scope_error_type"] = item["scope_error_type"]
            continue
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
