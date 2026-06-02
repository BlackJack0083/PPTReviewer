from __future__ import annotations

import csv
import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

SCHEMA_VERSION = "fine-grained-v1"
DEFAULT_FAMILIES = [
    "st_caption",
    "st_body",
    "summary",
    "title",
    "st_header",
    "st_summary",
    "summary_title",
    "three_element",
]
VALID_ERROR_TYPES = {"scope_error", "logic_error", "value_error", "claim_error"}
MUTATION_ERROR_TYPES = {
    "scope_time_range_shift": ("scope_error",),
    "scope_city_substitution": ("scope_error",),
    "scope_block_substitution": ("scope_error",),
    "chart_metric_label_swap": ("logic_error",),
    "table_metric_label_swap": ("logic_error",),
    "agg_func_swap": ("logic_error",),
    "metric_source_swap": ("logic_error",),
    "binning_step_swap": ("logic_error",),
    "numeric_value_perturbation": ("value_error",),
    "range_value_shift": ("value_error",),
    "trend_direction_flip": ("claim_error",),
    "title_topic_substitution": ("scope_error",),
    "presentation_type_substitution": ("claim_error",),
}
MUTATION_TYPE_ALIASES = {
    "caption_scope_year": "scope_time_range_shift",
    "summary_scope_year": "scope_time_range_shift",
    "caption_scope_city": "scope_city_substitution",
    "summary_scope_city": "scope_city_substitution",
    "caption_scope_block": "scope_block_substitution",
    "summary_scope_block": "scope_block_substitution",
    "caption_scope_object": "scope_block_substitution",
    "summary_scope_object": "scope_block_substitution",
    "series_metric_swap": "chart_metric_label_swap",
    "table_metric_swap": "table_metric_label_swap",
    "data_numeric_delta": "numeric_value_perturbation",
    "numeric_delta": "numeric_value_perturbation",
    "linked_numeric_delta": "numeric_value_perturbation",
    "range_delta": "range_value_shift",
    "trend_flip": "trend_direction_flip",
    "title_theme_drift": "title_topic_substitution",
    "caption_chart_type_mismatch": "presentation_type_substitution",
}
TITLE_DONORS = [
    "New-House Market Capacity Analysis",
    "New-House Cross-Structure Analysis",
    "Resale-House Cross-Structure Analysis",
    "Resale-House Capacity & Structure",
    "Annual Avg Price Growth",
    "Monthly Supply Analysis",
    "Area Segment Annual Trend Analysis",
]
TREND_FLIPS = {
    "increase": "decrease",
    "decrease": "increase",
    "increased": "decreased",
    "decreased": "increased",
    "upward": "downward",
    "downward": "upward",
    "growth": "decline",
    "decline": "growth",
}
NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH_INPUT_DIR = PROJECT_ROOT / "config" / "benchmark" / "ground_truth_inputs"


def now_iso() -> str:
    """生成用于 manifest 和校验报告的 UTC 时间戳。"""
    return datetime.now(UTC).isoformat()


def error_types_for_mutation(mutation_type: str) -> list[str]:
    """Return benchmark error labels for a mutation type."""
    labels = MUTATION_ERROR_TYPES.get(normalize_mutation_type(mutation_type))
    if labels is None:
        raise ValueError(f"Unknown mutation_type for error labels: {mutation_type}")
    return list(labels)


def normalize_mutation_type(mutation_type: str) -> str:
    """Normalize legacy mutation names to the public benchmark vocabulary."""
    raw = str(mutation_type)
    return MUTATION_TYPE_ALIASES.get(raw, raw)


def annotate_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach operation-level error labels without changing other fields."""
    annotated = []
    for operation in operations:
        op = dict(operation)
        op["mutation_type"] = normalize_mutation_type(str(op.get("mutation_type", "")))
        op["error_types"] = error_types_for_mutation(str(op.get("mutation_type", "")))
        annotated.append(op)
    return annotated


def collect_error_types(operations: list[dict[str, Any]]) -> list[str]:
    """Collect sorted case-level error labels from operation labels."""
    labels: set[str] = set()
    for operation in operations:
        for label in operation.get("error_types", []):
            labels.add(str(label))
    return sorted(labels)


def collect_affected_targets(operations: list[dict[str, Any]]) -> list[str]:
    """Collect sorted case-level affected targets from operations."""
    return sorted(
        {
            str(operation.get("target"))
            for operation in operations
            if operation.get("target")
        }
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL manifest；文件不存在时返回空列表。"""
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """向 JSONL manifest 追加一条记录，并自动创建父目录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_json(path: Path, data: dict[str, Any]) -> None:
    """写入带缩进的 JSON 产物，例如 coverage 或 validation 报告。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_yaml(path: Path) -> dict[str, Any]:
    """读取 YAML 文件；若内容不是 dict，则归一化为空 dict。"""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    """写入 benchmark YAML，保留键顺序和 Unicode 文本。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            data,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=1000,
        )


def rel(path: Path, root: Path) -> str:
    """返回相对于 benchmark 数据集根目录的稳定路径。"""
    return str(path.resolve().relative_to(root.resolve()))


@lru_cache(maxsize=8)
def load_ground_truth_blocks(city: str) -> tuple[str, ...]:
    """从 benchmark GT 输入 CSV 中读取指定城市的真实 block 名称。"""
    city_key = city.strip().lower()
    csv_path = GROUND_TRUTH_INPUT_DIR / f"{city_key}.csv"
    if not csv_path.exists():
        return ()

    blocks: list[str] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            block = str(row.get("block", "")).strip()
            if block:
                blocks.append(block)
    return tuple(blocks)


def scalar_to_json(value: Any) -> Any:
    """将 pandas/numpy 标量转换为可 JSON 序列化的 Python 标量。"""
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def parse_number(value: Any) -> float | None:
    """从标量或文本 token 中解析数值，用于错误扰动匹配。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, Real):
        if pd.isna(value):
            return None
        return float(value)
    match = NUMBER_RE.search(str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def number_key(value: Any) -> str | None:
    """构造归一化数值键，用于将 ST 单元格和 summary slot 对齐。"""
    parsed = parse_number(value)
    if parsed is None:
        return None
    return f"{parsed:.6f}".rstrip("0").rstrip(".")


def format_like_number(value: float, sample: Any) -> str | int | float:
    """按源值的类型和文本格式输出扰动后的数值。"""
    if isinstance(sample, Integral) and not isinstance(sample, bool):
        return int(round(value))
    if isinstance(sample, Real):
        return (
            round(value, 2) if abs(value - round(value)) > 1e-9 else int(round(value))
        )

    text = str(sample)
    match = NUMBER_RE.search(text)
    if not match:
        return str(int(round(value)))
    token = match.group(0)
    decimals = len(token.split(".", 1)[1]) if "." in token else 0
    use_comma = "," in token
    replacement = f"{value:.{decimals}f}" if decimals else str(int(round(value)))
    if use_comma and "." not in replacement:
        replacement = f"{int(replacement):,}"
    return text[: match.start()] + replacement + text[match.end() :]


def mutate_number(value: Any, rng) -> Any:
    """对数值施加通用小幅扰动，并尽量保留原始格式。"""
    parsed = parse_number(value)
    if parsed is None:
        return value
    delta = rng.choice([5, 20])
    if abs(parsed) < 20:
        delta = 5
    candidate = parsed + rng.choice([-delta, delta])
    if parsed >= 0 and candidate < 0:
        candidate = parsed + delta
    if candidate == parsed:
        candidate = parsed + delta
    return format_like_number(candidate, value)
