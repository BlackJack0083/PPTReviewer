from __future__ import annotations

import copy
import hashlib
import random
import re
from pathlib import Path
from typing import Any

import pandas as pd

from core import resource_manager
from engine.summary_injector import SummaryInjector
from engine.yaml_importer import YAMLImporter

from .common import (
    NUMBER_RE,
    SCHEMA_VERSION,
    TITLE_DONORS,
    TREND_FLIPS,
    YEAR_RE,
    dataframe_to_split_payload,
    format_like_number,
    load_ground_truth_blocks,
    load_yaml,
    mutate_number,
    now_iso,
    number_key,
    parse_number,
    scalar_to_json,
)

TEMPORAL_SLOT_HINTS = ("year", "month", "date", "temporal", "time")
RANGE_RE = re.compile(
    r"(?P<left>[-+]?\d[\d,]*(?:\.\d+)?)\s*[-–]\s*(?P<right>[-+]?\d[\d,]*(?:\.\d+)?)"
)


def mutate_text_value(
    value: str, rng: random.Random, slot_name: str | None = None
) -> tuple[str, str] | None:
    """当 summary slot 包含趋势词或业务数值时，生成对应文本扰动。"""
    text = str(value)
    lower = text.lower()
    for old, new in TREND_FLIPS.items():
        if re.search(rf"\b{re.escape(old)}\b", lower):
            pattern = re.compile(rf"\b{re.escape(old)}\b", flags=re.IGNORECASE)
            return pattern.sub(new, text, count=1), "trend_flip"

    numeric_mutation = mutate_summary_numeric_value(text, rng, slot_name)
    if numeric_mutation:
        return numeric_mutation

    return None


def mutate_summary_numeric_value(
    text: str, rng: random.Random, slot_name: str | None = None
) -> tuple[str, str] | None:
    """扰动非时间类 summary 数值；年份 scope 错误交给 scope 策略处理。"""
    if slot_name and any(hint in slot_name.lower() for hint in TEMPORAL_SLOT_HINTS):
        return None

    range_mutation = mutate_non_temporal_range(text, rng)
    if range_mutation:
        return range_mutation, "range_delta"

    matches = [match for match in NUMBER_RE.finditer(text) if not is_year_token(match.group(0))]
    if not matches:
        return None

    match = rng.choice(matches)
    token = match.group(0)
    parsed = parse_number(token)
    if parsed is None:
        return None

    suffix = text[match.end() :]
    is_percent_context = suffix.lstrip().startswith("%")
    mutated_token = mutate_business_number_token(token, parsed, rng, is_percent_context)
    if mutated_token == token:
        return None
    return text[: match.start()] + mutated_token + text[match.end() :], "numeric_delta"


def mutate_non_temporal_range(text: str, rng: random.Random) -> str | None:
    """整体平移非年份数值区间的左右端点。"""
    for match in RANGE_RE.finditer(text):
        left_token = match.group("left")
        right_token = match.group("right")
        if is_year_token(left_token) or is_year_token(right_token):
            continue
        left = parse_number(left_token)
        right = parse_number(right_token)
        if left is None or right is None:
            continue
        lo = min(left, right)
        hi = max(left, right)
        width = max(hi - lo, 1.0)
        shift = width * rng.choice([0.25, 0.5, 1.0]) * rng.choice([-1, 1])
        if lo >= 0 and lo + shift < 0:
            shift = abs(shift)
        new_left = format_like_number(left + shift, left_token)
        new_right = format_like_number(right + shift, right_token)
        replacement = f"{new_left}-{new_right}"
        return text[: match.start()] + replacement + text[match.end() :]
    return None


def mutate_business_number_token(
    token: str, parsed: float, rng: random.Random, is_percent_context: bool
) -> str:
    """按数值量级为单个业务数值 token 生成替换值。"""
    magnitude = max(abs(parsed), 1.0)
    if is_percent_context:
        delta = rng.choice([5.0, 10.0, 15.0])
    else:
        delta = magnitude * rng.choice([0.1, 0.2, 0.35])
        if token.replace(",", "").replace(".", "").isdigit():
            delta = max(1.0, round(delta))
    candidate = parsed + rng.choice([-1, 1]) * delta
    if parsed >= 0 and candidate < 0:
        candidate = parsed + abs(delta)
    return str(format_like_number(candidate, token))


def is_year_token(token: str) -> bool:
    """判断数值 token 是否应被视为日历年份。"""
    cleaned = token.replace(",", "").lstrip("+-")
    if not cleaned.isdigit():
        return False
    year = int(cleaned)
    return 1900 <= year <= 2099


def find_text_elements(
    data: dict[str, Any], role: str | None = None
) -> list[dict[str, Any]]:
    """在导出的 slide YAML 中查找 textBox 元素，可按语义 role 过滤。"""
    elements = data.get("template_slide", {}).get("elements", [])
    result = []
    for elem in elements:
        if not isinstance(elem, dict) or elem.get("type") != "textBox":
            continue
        if role is not None and elem.get("role") != role:
            continue
        result.append(elem)
    return result


def data_elements(data: dict[str, Any]) -> list[dict[str, Any]]:
    """返回可承载 ST body 数据扰动的 chart/table 元素。"""
    return [
        elem
        for elem in data.get("template_slide", {}).get("elements", [])
        if isinstance(elem, dict) and elem.get("type") in {"chart", "table"}
    ]


def make_text_op(
    target: str,
    elem: dict[str, Any],
    after: str,
    mutation_type: str,
    truth_basis: str = "gt_yaml",
) -> dict[str, Any]:
    """创建文本替换操作，并记录 before/after 修复元数据。"""
    return {
        "target": target,
        "element_id": str(elem.get("id", "")),
        "role": elem.get("role"),
        "before": str(elem.get("text", "")),
        "after": after,
        "mutation_type": mutation_type,
        "truth_basis": truth_basis,
    }


def reverse_op(op: dict[str, Any]) -> dict[str, Any]:
    """通过交换 before/after 构造期望修复操作。"""
    reversed_op = copy.deepcopy(op)
    reversed_op["before"], reversed_op["after"] = op.get("after"), op.get("before")
    reversed_op["mutation_type"] = f"repair_{op.get('mutation_type', 'mutation')}"
    return reversed_op


def mutate_caption(data: dict[str, Any], rng: random.Random) -> dict[str, Any] | None:
    """从图表类型和 scope 候选中构造一个 ST caption 错误。"""
    captions = find_text_elements(data, "caption")
    if not captions:
        return None
    elem = rng.choice(captions)
    text = str(elem.get("text", ""))
    candidates = []

    chart_type_op = mutate_caption_chart_type(elem, rng)
    if chart_type_op:
        candidates.append(chart_type_op)

    years = YEAR_RE.findall(text)
    if years:
        target_year = rng.choice(years)
        mutated_year = str(int(target_year) + rng.choice([-1, 1]))
        after = text.replace(target_year, mutated_year, 1)
        candidates.append(make_text_op("st.caption", elem, after, "caption_scope_year"))

    city = data.get("query_filters", {}).get("city")
    city_donors = [c for c in ["Beijing", "Guangzhou", "Shenzhen"] if c != city]
    if city and city in text and city_donors:
        after = text.replace(city, rng.choice(city_donors), 1)
        candidates.append(make_text_op("st.caption", elem, after, "caption_scope_city"))

    object_op = mutate_caption_scope_object(data, elem, rng)
    if object_op:
        candidates.append(object_op)

    return rng.choice(candidates) if candidates else None


def mutate_caption_scope_object(
    data: dict[str, Any], elem: dict[str, Any], rng: random.Random
) -> dict[str, Any] | None:
    """将 caption 中的 block 替换为同城市的另一个真实 block。"""
    text = str(elem.get("text", ""))
    city = str(data.get("query_filters", {}).get("city", "")).strip()
    block = str(data.get("query_filters", {}).get("block", "")).strip()
    if not city or not block or block not in text:
        return None

    donor_blocks = [candidate for candidate in load_ground_truth_blocks(city) if candidate != block]
    if not donor_blocks:
        return None

    wrong_block = rng.choice(donor_blocks)
    after = text.replace(block, wrong_block, 1)
    op = make_text_op(
        "st.caption",
        elem,
        after,
        "caption_scope_object",
        truth_basis="query_filters",
    )
    op.update(
        {
            "scope_field": "block",
            "truth_value": block,
            "wrong_value": wrong_block,
        }
    )
    return op


def mutate_caption_chart_type(elem: dict[str, Any], rng: random.Random) -> dict[str, Any] | None:
    """将 caption 中可见的图表/表格类型标签替换为另一个类型。"""
    text = str(elem.get("text", ""))
    labels = ["Bar chart", "Line chart", "Pie chart", "Table"]
    for label in labels:
        current_label = f"({label})"
        if text.endswith(current_label):
            wrong_label = rng.choice([candidate for candidate in labels if candidate != label])
            after = text[: -len(current_label)] + f"({wrong_label})"
            return make_text_op(
                "st.caption",
                elem,
                after,
                "caption_chart_type_mismatch",
                truth_basis="visible_rendering",
            )
    return None


def mutate_title(data: dict[str, Any], rng: random.Random) -> dict[str, Any] | None:
    """将页面标题替换为其他报告主题的 donor title。"""
    titles = find_text_elements(data, "slide-title")
    if not titles:
        return None
    elem = titles[0]
    current = str(elem.get("text", ""))
    donors = [title for title in TITLE_DONORS if title != current]
    if not donors:
        return None
    return make_text_op("title", elem, rng.choice(donors), "title_theme_drift")


def apply_text_op(data: dict[str, Any], op: dict[str, Any]) -> None:
    """将文本操作应用到 YAML 中匹配的 textBox 元素。"""
    for elem in find_text_elements(data):
        if str(elem.get("id", "")) == str(op.get("element_id", "")):
            elem["text"] = op["after"]
            return
    raise ValueError(f"Text element not found: {op.get('element_id')}")


def find_summary_element(data: dict[str, Any]) -> dict[str, Any] | None:
    """解析 summary_binding 指向的 summary 文本元素。"""
    role = data.get("summary_binding", {}).get("target_text_role", "body-text")
    elems = find_text_elements(data, role)
    return elems[0] if elems else None


def mutate_summary(
    data: dict[str, Any],
    rng: random.Random,
    forced_slot: str | None = None,
    forced_value: Any | None = None,
) -> dict[str, Any] | None:
    """通过 scope 文本替换或 summary slot override 构造 Summary 错误。"""
    binding = data.get("summary_binding")
    elem = find_summary_element(data)
    if not isinstance(binding, dict) or elem is None:
        return None
    truth_slots = binding.get("summary_slots_truth", {})
    if not isinstance(truth_slots, dict) or not truth_slots:
        return None

    if forced_slot is not None:
        if forced_slot not in truth_slots:
            return None
        slot_name = forced_slot
        after_value = str(forced_value)
        mutation_type = "linked_numeric_delta"
    else:
        scope_ops = mutate_summary_scope(data, elem, rng)
        candidates = list(truth_slots.items())
        rng.shuffle(candidates)
        selected_slot_name = None
        for candidate_slot_name, truth_value in candidates:
            mutation = mutate_text_value(str(truth_value), rng, candidate_slot_name)
            if mutation:
                selected_slot_name = candidate_slot_name
                after_value, mutation_type = mutation
                break
        else:
            return rng.choice(scope_ops) if scope_ops else None
        if scope_ops and rng.choice([True, False]):
            return rng.choice(scope_ops)
        slot_name = selected_slot_name

    overrides = binding.get("summary_slot_overrides", {})
    if not isinstance(overrides, dict):
        overrides = {}
    overrides = dict(overrides)
    overrides[slot_name] = str(after_value)
    binding["summary_slot_overrides"] = overrides
    after_text = SummaryInjector.render_summary(binding)

    op = make_text_op("summary", elem, after_text, mutation_type)
    op["slot_name"] = slot_name
    op["slot_before"] = str(truth_slots[slot_name])
    op["slot_after"] = str(after_value)
    return op


def mutate_summary_scope(
    data: dict[str, Any], elem: dict[str, Any], rng: random.Random
) -> list[dict[str, Any]]:
    """生成 Summary-only 的时间、城市和 block scope 文本错误候选。"""
    text = str(elem.get("text", ""))
    query_filters = data.get("query_filters", {})
    if not isinstance(query_filters, dict):
        return []

    ops = []
    start_year = str(query_filters.get("start_date", ""))[:4]
    end_year = str(query_filters.get("end_date", ""))[:4]
    years = [year for year in (start_year, end_year) if year and year in text]
    if years:
        truth_year = rng.choice(years)
        wrong_year = str(int(truth_year) + rng.choice([-1, 1]))
        op = make_text_op(
            "summary",
            elem,
            text.replace(truth_year, wrong_year, 1),
            "summary_scope_year",
            truth_basis="query_filters",
        )
        op.update(
            {
                "scope_field": "year",
                "truth_value": truth_year,
                "wrong_value": wrong_year,
            }
        )
        ops.append(op)

    city = str(query_filters.get("city", "")).strip()
    city_donors = [candidate for candidate in ["Beijing", "Guangzhou", "Shenzhen"] if candidate != city]
    if city and city in text and city_donors:
        wrong_city = rng.choice(city_donors)
        op = make_text_op(
            "summary",
            elem,
            text.replace(city, wrong_city, 1),
            "summary_scope_city",
            truth_basis="query_filters",
        )
        op.update(
            {
                "scope_field": "city",
                "truth_value": city,
                "wrong_value": wrong_city,
            }
        )
        ops.append(op)

    block = str(query_filters.get("block", "")).strip()
    if block and block in text and city:
        donor_blocks = [candidate for candidate in load_ground_truth_blocks(city) if candidate != block]
        if donor_blocks:
            wrong_block = rng.choice(donor_blocks)
            op = make_text_op(
                "summary",
                elem,
                text.replace(block, wrong_block, 1),
                "summary_scope_object",
                truth_basis="query_filters",
            )
            op.update(
                {
                    "scope_field": "block",
                    "truth_value": block,
                    "wrong_value": wrong_block,
                }
            )
            ops.append(op)

    return ops


def iter_numeric_cells(df: pd.DataFrame):
    """遍历 DataFrame 中可解析为数值的单元格坐标和值。"""
    for row_pos in range(df.shape[0]):
        for col_pos in range(df.shape[1]):
            value = df.iat[row_pos, col_pos]
            if parse_number(value) is None:
                continue
            yield row_pos, col_pos, value


def summary_numeric_slots(data: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """索引 summary 真值中的数值 slot，用于构造 ST+Summary 联动错误。"""
    slots = data.get("summary_binding", {}).get("summary_slots_truth", {})
    result = {}
    if not isinstance(slots, dict):
        return result
    for name, value in slots.items():
        key = number_key(value)
        if key is not None:
            result[key] = (name, str(value))
    return result


def load_truth_data(data: dict[str, Any]) -> tuple[list[pd.DataFrame], list[str]]:
    """基于 YAML filters 重算 GT 数据，并忽略已有 data_overrides。"""
    template_id = YAMLImporter.resolve_template_id(data, "<memory>")
    template_meta = resource_manager.get_template(template_id)
    if template_meta is None:
        raise ValueError(f"Template not found: {template_id}")
    all_data, _, _ = YAMLImporter.load_data_payloads(
        data,
        template_meta,
        use_overrides=False,
    )
    return all_data, list(template_meta.data_keys.values())


def mutate_st_body(
    data: dict[str, Any],
    rng: random.Random,
    require_summary_link: bool = False,
) -> tuple[dict[str, Any], str | None, Any | None] | None:
    """扰动一个 chart/table 数据单元格，并可选联动到 summary slot。"""
    all_data, data_keys = load_truth_data(data)
    data_elems = data_elements(data)
    linked_slots = summary_numeric_slots(data) if require_summary_link else {}
    candidates = []

    for data_idx, df in enumerate(all_data):
        if data_idx >= len(data_keys):
            continue
        for row_pos, col_pos, value in iter_numeric_cells(df):
            linked_slot = None
            if require_summary_link:
                linked_slot = linked_slots.get(number_key(value) or "")
                if linked_slot is None:
                    continue
            candidates.append((data_idx, row_pos, col_pos, value, linked_slot))

    if not candidates:
        return None

    data_idx, row_pos, col_pos, value, linked_slot = rng.choice(candidates)
    data_key = data_keys[data_idx]
    df = all_data[data_idx].copy()
    after_value = mutate_number(value, rng)
    df.iat[row_pos, col_pos] = after_value

    overrides = data.get("data_overrides", {})
    if not isinstance(overrides, dict):
        overrides = {}
    overrides = dict(overrides)
    overrides[data_key] = dataframe_to_split_payload(df)
    data["data_overrides"] = overrides

    elem = data_elems[data_idx] if data_idx < len(data_elems) else {}
    op = {
        "target": "st.body",
        "element_id": str(elem.get("id", "")),
        "role": elem.get("role"),
        "data_key": data_key,
        "cell": {
            "row_index": row_pos,
            "row_label": scalar_to_json(df.index[row_pos]),
            "column_index": col_pos,
            "column": scalar_to_json(df.columns[col_pos]),
        },
        "before": scalar_to_json(value),
        "after": scalar_to_json(after_value),
        "mutation_type": "data_numeric_delta",
        "truth_basis": "database_rebuild",
    }
    slot_name = linked_slot[0] if linked_slot else None
    slot_after = (
        format_like_number(parse_number(after_value), linked_slot[1])
        if linked_slot
        else None
    )
    return op, slot_name, slot_after


def apply_ops(data: dict[str, Any], ops: list[dict[str, Any]]) -> None:
    """在 data_overrides 准备完成后应用所有文本操作。"""
    for op in ops:
        if op["target"] in {"title", "summary", "st.caption"}:
            apply_text_op(data, op)


def build_corruption(
    dataset_root: Path,
    sample_row: dict[str, Any],
    family: str,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """为指定 error family 构造一个 injected YAML 及其 corruption 元数据。"""
    source_yaml = dataset_root / sample_row["gt_yaml"]
    if not source_yaml.exists():
        return None

    data = load_yaml(source_yaml)
    rng = random.Random(seed)  # noqa: S311
    operations: list[dict[str, Any]] = []

    if family == "st_caption":
        op = mutate_caption(data, rng)
        if not op:
            return None
        operations.append(op)

    elif family == "st_body":
        result = mutate_st_body(data, rng)
        if not result:
            return None
        operations.append(result[0])

    elif family == "summary":
        op = mutate_summary(data, rng)
        if not op:
            return None
        operations.append(op)

    elif family == "title":
        op = mutate_title(data, rng)
        if not op:
            return None
        operations.append(op)

    elif family == "st_summary":
        result = mutate_st_body(data, rng, require_summary_link=True)
        if not result:
            return None
        body_op, slot_name, slot_after = result
        summary_op = mutate_summary(data, rng, slot_name, slot_after)
        if not summary_op:
            return None
        operations.extend([body_op, summary_op])

    elif family == "summary_title":
        summary_op = mutate_summary(data, rng)
        title_op = mutate_title(data, rng)
        if not summary_op or not title_op:
            return None
        operations.extend([summary_op, title_op])

    elif family == "three_element":
        result = mutate_st_body(data, rng, require_summary_link=True)
        if not result:
            return None
        body_op, slot_name, slot_after = result
        summary_op = mutate_summary(data, rng, slot_name, slot_after)
        title_op = mutate_title(data, rng)
        if not summary_op or not title_op:
            return None
        operations.extend([body_op, summary_op, title_op])

    else:
        raise ValueError(f"Unknown family: {family}")

    apply_ops(data, operations)
    sample_id = sample_row["sample_id"]
    raw_id = f"{sample_id}|{family}|{seed}"
    corruption_id = (
        f"{sample_id}-{family}-{hashlib.md5(raw_id.encode()).hexdigest()[:8]}"  # noqa: S324
    )
    expected_operations = [reverse_op(op) for op in operations]
    targets = sorted({op["target"] for op in operations})
    corruption = {
        "schema_version": SCHEMA_VERSION,
        "corruption_id": corruption_id,
        "sample_id": sample_id,
        "error_family": family,
        "error_type": "+".join(op["mutation_type"] for op in operations),
        "targets": targets,
        "observability": "observable",
        "repair_mode": "unique_repair",
        "requires_user_feedback": False,
        "seed": seed,
        "operations": operations,
        "expected_operations": expected_operations,
        "expected_repair_yaml": sample_row["gt_yaml"],
        "created_at": now_iso(),
    }
    data["corruption"] = corruption
    return data, corruption
