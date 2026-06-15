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
    "scope",
    "value",
    "claim",
]
VALID_ERROR_TYPES = {"scope_error", "value_error", "claim_error"}
MUTATION_ERROR_TYPES = {
    "scope_city_missing": ("scope_error",),
    "scope_city_error": ("scope_error",),
    "scope_city_unmatch": ("scope_error",),
    "scope_city_conflict": ("scope_error",),
    "scope_block_missing": ("scope_error",),
    "scope_block_error": ("scope_error",),
    "scope_block_unmatch": ("scope_error",),
    "scope_block_conflict": ("scope_error",),
    "scope_time_range_missing": ("scope_error",),
    "scope_time_range_error": ("scope_error",),
    "scope_time_range_conflict": ("scope_error",),
    "value_table_cell": ("value_error",),
    "value_summary_slot": ("value_error",),
    "claim_caption_presentation": ("claim_error",),
    "claim_summary_slot": ("claim_error",),
}
NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH_INPUT_DIR = PROJECT_ROOT / "config" / "benchmark" / "ground_truth_inputs"


def now_iso() -> str:
    """生成用于 manifest 和校验报告的 UTC 时间戳。"""
    return datetime.now(UTC).isoformat()


def error_types_for_mutation(mutation_type: str) -> list[str]:
    """Return benchmark error labels for a mutation type."""
    labels = MUTATION_ERROR_TYPES.get(str(mutation_type))
    if labels is None:
        raise ValueError(f"Unknown mutation_type for error labels: {mutation_type}")
    return list(labels)


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
    """对数值施加 seed-controlled 多样扰动，并尽量保留原始格式。"""
    parsed = parse_number(value)
    if parsed is None:
        return value
    magnitude = max(abs(parsed), 1.0)
    candidates = [
        parsed + rng.choice([-1, 1]) * magnitude * rng.choice([0.05, 0.1, 0.2, 0.35]),
        parsed * rng.choice([0.5, 0.75, 1.25, 1.5, 2.0]),
        parsed + rng.choice([-1, 1]) * rng.choice([1, 3, 5, 10, 20, 50]),
    ]
    if float(parsed).is_integer():
        candidates.append(parsed + rng.choice([-1, 1]) * rng.randint(1, max(2, int(magnitude // 5) + 2)))
    candidates = [
        candidate
        for candidate in candidates
        if candidate != parsed and not (parsed >= 0 and candidate < 0)
    ]
    candidate = rng.choice(candidates) if candidates else parsed + 1
    return format_like_number(candidate, value)
