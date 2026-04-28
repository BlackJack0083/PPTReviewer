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
    "metric_label",
    "st_summary",
    "summary_title",
    "three_element",
]
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


def dataframe_to_split_payload(df: pd.DataFrame) -> dict[str, Any]:
    """将 DataFrame 序列化为 mutated_data 使用的 split-orient 结构。"""
    return {
        "orient": "split",
        "index": [scalar_to_json(v) for v in df.index.tolist()],
        "columns": [scalar_to_json(v) for v in df.columns.tolist()],
        "data": [
            [scalar_to_json(value) for value in row]
            for row in df.to_numpy(dtype=object).tolist()
        ],
    }


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
