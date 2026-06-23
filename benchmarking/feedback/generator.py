"""Generate structured feedback benchmark episodes from corruption manifests."""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from tqdm.auto import tqdm

from benchmarking.fine_grained.common import error_types_for_mutation

DATA_SOURCE_FIELD_BY_MUTATION = {
    "scope_city_missing": "city",
    "scope_city_error": "city",
    "scope_city_unmatch": "city",
    "scope_city_conflict": "city",
    "scope_block_missing": "block",
    "scope_block_error": "block",
    "scope_block_unmatch": "block",
    "scope_block_conflict": "block",
    "scope_time_range_missing": "time_range",
    "scope_time_range_error": "time_range",
    "scope_time_range_conflict": "time_range",
}

SCOPE_ERROR_TYPE_BY_MUTATION = {
    "scope_city_missing": "missing",
    "scope_city_error": "error",
    "scope_city_unmatch": "unmatch",
    "scope_city_conflict": "conflict",
    "scope_block_missing": "missing",
    "scope_block_error": "error",
    "scope_block_unmatch": "unmatch",
    "scope_block_conflict": "conflict",
    "scope_time_range_missing": "missing",
    "scope_time_range_error": "error",
    "scope_time_range_conflict": "conflict",
}

UPDATE_CONFIRMATION_MUTATIONS = {
    "value_table_cell",
    "value_summary_slot",
    "claim_caption_presentation",
    "claim_summary_slot",
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


def table_index_for_scope_operation(operation: dict) -> int:
    """Return the datasource index for a scope operation."""
    source = str(operation.get("source", ""))
    if source == "summary":
        return 0
    if source.startswith("caption[") and source.endswith("]"):
        return int(source.removeprefix("caption[").removesuffix("]"))
    raise ValueError(f"Scope operation must include source=summary|caption[i]: {operation}")


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
    operation: dict,
) -> dict | None:
    """Build one feedback item from one corruption operation."""
    mutation_type = str(operation.get("mutation_type", ""))
    if (
        mutation_type not in DATA_SOURCE_FIELD_BY_MUTATION
        and mutation_type not in UPDATE_CONFIRMATION_MUTATIONS
    ):
        return None

    error_types = operation.get("error_types")
    if not isinstance(error_types, list) or not error_types:
        error_types = error_types_for_mutation(mutation_type)

    item: dict[str, Any] = {
        "request_type": request_type_for_mutation(mutation_type),
        "error_type": sorted(str(label) for label in error_types)[0],
        "target": str(operation["target"]),
    }

    if mutation_type in DATA_SOURCE_FIELD_BY_MUTATION:
        item["field"] = DATA_SOURCE_FIELD_BY_MUTATION[mutation_type]
        item["scope_error_type"] = SCOPE_ERROR_TYPE_BY_MUTATION[mutation_type]
        item["response"] = build_data_source_response(
            gt_yaml,
            table_index=table_index_for_scope_operation(operation),
            field=item["field"],
        )
    elif mutation_type in UPDATE_CONFIRMATION_MUTATIONS:
        item["response"] = "Yes, please apply the proposed update."
    return item


def request_type_for_mutation(mutation_type: str) -> str:
    """Return the client request type expected for one injected mutation."""
    if mutation_type in DATA_SOURCE_FIELD_BY_MUTATION:
        return "data_source_slot_clarification"
    if mutation_type in UPDATE_CONFIRMATION_MUTATIONS:
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
            str(item.get("target", "")),
            str(item.get("field", "")),
        )
        if key not in merged:
            merged[key] = {
                "request_type": item["request_type"],
                "error_type": item["error_type"],
                "response": item["response"],
            }
            if "field" in item:
                merged[key]["field"] = item["field"]
            if "target" in item:
                merged[key]["target"] = item["target"]
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
        if (item := feedback_item_for_operation(gt_yaml, operation))
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
