from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from engine.data_files import (
    data_elements,
    read_dataframe_csv,
    resolve_element_data_path,
)

from .common import (
    DEFAULT_FAMILIES,
    SCHEMA_VERSION,
    error_types_for_mutation,
    load_yaml,
    now_iso,
    read_jsonl,
    write_json,
)

REQUIRED_RECORD_FIELDS = {
    "operations",
    "expected_repair_yaml",
    "source_yaml",
    "output_yaml",
    "corruption_json",
}
REQUIRED_OPERATION_FIELDS = {
    "target",
    "element_id",
    "mutation_type",
}
VALID_TARGETS = {"st.caption", "st.body", "summary"}
SCOPE_FAMILY_MUTATIONS = {
    "scope_city_missing",
    "scope_city_error",
    "scope_city_unmatch",
    "scope_city_conflict",
    "scope_block_missing",
    "scope_block_error",
    "scope_block_unmatch",
    "scope_block_conflict",
    "scope_time_range_missing",
    "scope_time_range_error",
    "scope_time_range_conflict",
}
VALUE_FAMILY_MUTATIONS = {
    "value_table_cell",
    "value_summary_slot",
}
CLAIM_FAMILY_MUTATIONS = {
    "claim_caption_presentation",
    "claim_summary_slot",
}


def validate_benchmark(dataset_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """校验 corruption manifest，并返回 validation 与 coverage 报告。"""
    dataset_root = dataset_root.resolve()
    manifest_path = dataset_root / "manifest" / "corruptions.jsonl"
    sample_manifest_path = dataset_root / "manifest" / "samples.jsonl"
    records = read_jsonl(manifest_path)
    samples = read_jsonl(sample_manifest_path)

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if not manifest_path.exists():
        errors.append({"code": "missing_manifest", "path": str(manifest_path)})

    for line_no, record in enumerate(records, start=1):
        context = {"line": line_no, "output_yaml": record.get("output_yaml")}
        _validate_record_schema(record, context, errors)
        _validate_unique_output(record, seen_ids, context, errors)
        _validate_record_paths(dataset_root, record, context, errors)
        _validate_operations(record, context, errors)
        _validate_sidecar_json(dataset_root, record, context, errors)
        _validate_output_yaml(dataset_root, record, context, errors)

    coverage = build_coverage_report(records, samples)
    validation = {
        "schema_version": SCHEMA_VERSION,
        "dataset_root": str(dataset_root),
        "created_at": now_iso(),
        "manifest_path": str(manifest_path),
        "record_count": len(records),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "valid": not errors,
    }
    return validation, coverage


def build_coverage_report(
    records: list[dict[str, Any]],
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    """按 family、split、template、layout 和 city 汇总 corruption 覆盖情况。"""
    by_family = Counter(infer_error_family(record) for record in records)
    by_split = Counter(str(record.get("split", "")) for record in records)
    by_template = Counter(str(record.get("template_id", "")) for record in records)
    by_layout = Counter(str(record.get("layout_type", "")) for record in records)
    by_city = Counter(str(record.get("city_key", "")) for record in records)

    template_family_counts: dict[str, dict[str, int]] = defaultdict(dict)
    layout_family_counts: dict[str, dict[str, int]] = defaultdict(dict)
    split_family_counts: dict[str, dict[str, int]] = defaultdict(dict)
    for record in records:
        family = infer_error_family(record)
        template_id = str(record.get("template_id", ""))
        layout_type = str(record.get("layout_type", ""))
        split = str(record.get("split", ""))
        if template_id:
            template_family_counts[template_id][family] = (
                template_family_counts[template_id].get(family, 0) + 1
            )
        if layout_type:
            layout_family_counts[layout_type][family] = (
                layout_family_counts[layout_type].get(family, 0) + 1
            )
        if split:
            split_family_counts[split][family] = (
                split_family_counts[split].get(family, 0) + 1
            )

    sample_templates = sorted(
        {str(row.get("template_id", "")) for row in samples if row.get("template_id")}
    )
    sample_layouts = sorted(
        {str(row.get("layout_type", "")) for row in samples if row.get("layout_type")}
    )
    generated_templates = sorted(template_family_counts)
    template_universe = sample_templates or generated_templates

    missing_template_family = []
    for template_id in template_universe:
        for family in DEFAULT_FAMILIES:
            if template_family_counts.get(template_id, {}).get(family, 0) == 0:
                missing_template_family.append(
                    {
                        "template_id": template_id,
                        "error_family": family,
                        "reason": "no_generated_corruption",
                    }
                )

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": now_iso(),
        "summary": {
            "total_corruptions": len(records),
            "unique_splits": len([key for key in by_split if key]),
            "unique_templates": len([key for key in by_template if key]),
            "unique_layouts": len([key for key in by_layout if key]),
            "unique_cities": len([key for key in by_city if key]),
            "sample_manifest_templates": len(sample_templates),
            "sample_manifest_layouts": len(sample_layouts),
        },
        "by_family": dict(sorted(by_family.items())),
        "by_split": dict(sorted(by_split.items())),
        "by_template": dict(sorted(by_template.items())),
        "by_layout": dict(sorted(by_layout.items())),
        "by_city": dict(sorted(by_city.items())),
        "template_family_counts": {
            key: dict(sorted(value.items()))
            for key, value in sorted(template_family_counts.items())
        },
        "layout_family_counts": {
            key: dict(sorted(value.items()))
            for key, value in sorted(layout_family_counts.items())
        },
        "split_family_counts": {
            key: dict(sorted(value.items()))
            for key, value in sorted(split_family_counts.items())
        },
        "missing_template_family": missing_template_family,
    }


def _validate_record_schema(
    record: dict[str, Any],
    context: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    """检查 manifest 必填字段和高层枚举类字段是否合法。"""
    missing = sorted(REQUIRED_RECORD_FIELDS - set(record))
    if missing:
        _add_error(errors, "missing_record_fields", context, fields=missing)

    if not isinstance(record.get("operations"), list) or not record.get("operations"):
        _add_error(errors, "invalid_operations", context)


def _validate_unique_output(
    record: dict[str, Any],
    seen_ids: set[str],
    context: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    """确保每个 output_yaml 存在且唯一。"""
    output_yaml = record.get("output_yaml")
    if not isinstance(output_yaml, str) or not output_yaml:
        _add_error(errors, "missing_output_yaml", context)
        return
    if output_yaml in seen_ids:
        _add_error(errors, "duplicate_output_yaml", context)
    seen_ids.add(output_yaml)


def _validate_record_paths(
    dataset_root: Path,
    record: dict[str, Any],
    context: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    """校验 manifest 行中引用的必选和可选产物路径。"""
    required_paths = [
        "source_yaml",
        "output_yaml",
        "corruption_json",
        "expected_repair_yaml",
    ]
    optional_paths = ["source_ppt", "output_ppt", "output_png"]
    for key in required_paths:
        _validate_existing_relative_path(
            dataset_root, record, key, context, errors, required=True
        )
    for key in optional_paths:
        _validate_existing_relative_path(
            dataset_root, record, key, context, errors, required=False
        )


def _validate_existing_relative_path(
    dataset_root: Path,
    record: dict[str, Any],
    key: str,
    context: dict[str, Any],
    errors: list[dict[str, Any]],
    *,
    required: bool,
) -> None:
    """检查某个相对路径在必填或已提供时是否真实存在。"""
    value = record.get(key)
    if value in (None, ""):
        if required:
            _add_error(errors, "missing_path", context, field=key)
        return
    path = dataset_root / str(value)
    if not path.exists():
        _add_error(errors, "path_not_found", context, field=key, path=str(path))


def _validate_operations(
    record: dict[str, Any],
    context: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    """校验 operation 对象结构。"""
    operations = record.get("operations")
    if not isinstance(operations, list):
        return

    for idx, op in enumerate(operations):
        op_context = {**context, "operation_index": idx}
        if not isinstance(op, dict):
            _add_error(errors, "invalid_operation_object", op_context)
            continue
        missing = sorted(REQUIRED_OPERATION_FIELDS - set(op))
        if missing:
            _add_error(errors, "missing_operation_fields", op_context, fields=missing)
        target = op.get("target")
        if target not in VALID_TARGETS:
            _add_error(errors, "invalid_operation_target", op_context, target=target)
        if target == "st.body" and "cell" not in op:
            _add_error(
                errors,
                "missing_st_body_operation_field",
                op_context,
                field="cell",
            )


def _validate_sidecar_json(
    dataset_root: Path,
    record: dict[str, Any],
    context: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    """检查 corruption.json 可读取，且关键字段与 manifest 行一致。"""
    corruption_json = record.get("corruption_json")
    if not corruption_json:
        return
    path = dataset_root / str(corruption_json)
    if not path.exists():
        return
    try:
        import json

        sidecar = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _add_error(
            errors, "invalid_corruption_json", context, path=str(path), error=str(exc)
        )
        return

    for key in ("operations", "expected_repair_yaml"):
        if sidecar.get(key) != record.get(key):
            _add_error(
                errors,
                "sidecar_manifest_mismatch",
                context,
                field=key,
                manifest_value=record.get(key),
                sidecar_value=sidecar.get(key),
            )


def _validate_output_yaml(
    dataset_root: Path,
    record: dict[str, Any],
    context: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    """检查 injected slide.yaml 可读取，且不内嵌 corruption 标注。"""
    output_yaml = record.get("output_yaml")
    if not output_yaml:
        return
    path = dataset_root / str(output_yaml)
    if not path.exists():
        return
    try:
        yaml_data = load_yaml(path)
    except Exception as exc:  # noqa: BLE001
        _add_error(
            errors, "invalid_output_yaml", context, path=str(path), error=str(exc)
        )
        return

    corruption = yaml_data.get("corruption")
    if isinstance(corruption, dict):
        _add_error(errors, "unexpected_yaml_corruption", context, path=str(path))
    if "mutated_data" in yaml_data:
        _add_error(errors, "unexpected_yaml_mutated_data", context, path=str(path))
    _validate_element_data_files(path, yaml_data, context, errors)


def _validate_element_data_files(
    yaml_path: Path,
    yaml_data: dict[str, Any],
    context: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    """检查 chart/table 元素是否声明并可读取外置 CSV 数据。"""
    for element in data_elements(yaml_data):
        element_context = {**context, "element_id": element.get("id")}
        try:
            data_path = resolve_element_data_path(yaml_path, element)
        except Exception as exc:  # noqa: BLE001
            _add_error(
                errors,
                "invalid_element_data_path",
                element_context,
                error=str(exc),
            )
            continue
        if not data_path.exists():
            _add_error(
                errors,
                "element_data_not_found",
                element_context,
                path=str(data_path),
            )
            continue
        try:
            read_dataframe_csv(data_path)
        except Exception as exc:  # noqa: BLE001
            _add_error(
                errors,
                "invalid_element_data_csv",
                element_context,
                path=str(data_path),
                error=str(exc),
            )


def infer_error_family(record: dict[str, Any]) -> str:
    """Infer the benchmark family for coverage statistics."""
    families: set[str] = set()
    for operation in record.get("operations", []):
        if not isinstance(operation, dict):
            continue
        mutation_type = str(operation.get("mutation_type", ""))
        try:
            error_types_for_mutation(mutation_type)
        except ValueError:
            return "unknown"
        if mutation_type in SCOPE_FAMILY_MUTATIONS:
            families.add("scope")
        elif mutation_type in VALUE_FAMILY_MUTATIONS:
            families.add("value")
        elif mutation_type in CLAIM_FAMILY_MUTATIONS:
            families.add("claim")
    if len(families) == 1:
        return next(iter(families))
    if len(families) > 1:
        return "mixed"
    return "unknown"


def _add_error(
    errors: list[dict[str, Any]],
    code: str,
    context: dict[str, Any],
    **details: Any,
) -> None:
    """追加一条带共享上下文和细节的结构化校验错误。"""
    errors.append({"code": code, **context, **details})


def parse_args() -> argparse.Namespace:
    """解析 benchmark 数据集校验 CLI 参数。"""
    parser = argparse.ArgumentParser(
        description="Validate fine-grained PPT benchmark corruptions."
    )
    parser.add_argument("--benchmark-root", default="output/benchmark/dataset_v1")
    return parser.parse_args()


def main() -> None:
    """执行 benchmark 校验，并在 manifest 目录下写入报告 JSON。"""
    args = parse_args()
    dataset_root = Path(args.benchmark_root)
    validation, coverage = validate_benchmark(dataset_root)
    manifest_dir = dataset_root / "manifest"
    write_json(manifest_dir / "corruption_validation.json", validation)
    write_json(manifest_dir / "corruption_coverage_detailed.json", coverage)

    print(
        f"Validated {validation['record_count']} corruptions: "
        f"errors={validation['error_count']}, warnings={validation['warning_count']}"
    )
    print(f"Coverage: {coverage['summary']}")
    if not validation["valid"]:
        raise SystemExit(1)
