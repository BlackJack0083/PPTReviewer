from __future__ import annotations

import copy
import hashlib
import random
import re
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Template

from common.function_specs import filter_function_args
from core import layout_manager, resource_manager
from core.data_provider import RealEstateDataProvider
from engine.yaml_importer import YAMLImporter

from .common import (
    NUMBER_RE,
    TITLE_DONORS,
    TREND_FLIPS,
    dataframe_to_split_payload,
    format_like_number,
    load_ground_truth_blocks,
    load_yaml,
    mutate_number,
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

    matches = [
        match for match in NUMBER_RE.finditer(text) if not is_year_token(match.group(0))
    ]
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
    semantic_slot: str | None = None,
) -> dict[str, Any]:
    """创建文本替换操作；after 仅用于应用变更，不写入公开标注。"""
    op = {
        "target": target,
        "element_id": str(elem.get("id", "")),
        "role": elem.get("role"),
        "mutation_type": mutation_type,
        "_after": after,
    }
    if semantic_slot:
        op["semantic_slot"] = semantic_slot
    return op


def mutate_caption(data: dict[str, Any], rng: random.Random) -> dict[str, Any] | None:
    """从图表类型和 scope 候选中构造一个 ST caption 错误。"""
    captions = find_text_elements(data, "caption")
    if not captions:
        return None
    elem = rng.choice(captions)
    candidates = []

    chart_type_op = mutate_caption_chart_type(data, elem, rng)
    if chart_type_op:
        candidates.append(chart_type_op)

    context = caption_context(data)
    year_slots = [
        slot
        for slot in ("Temporal_Start_Year", "Temporal_End_Year")
        if context.get(slot)
    ]
    if year_slots:
        semantic_slot = rng.choice(year_slots)
        truth_year = str(context[semantic_slot])
        mutated_year = str(int(truth_year) + rng.choice([-1, 1]))
        after = render_caption_text(
            data,
            elem,
            context_overrides={semantic_slot: mutated_year},
        )
        candidates.append(
            make_text_op(
                "st.caption",
                elem,
                after,
                "caption_scope_year",
                semantic_slot=semantic_slot,
            )
        )

    city = context.get("Geo_City_Name")
    city_donors = [c for c in ["Beijing", "Guangzhou", "Shenzhen"] if c != city]
    if city and city_donors:
        after = render_caption_text(
            data,
            elem,
            context_overrides={"Geo_City_Name": rng.choice(city_donors)},
        )
        candidates.append(
            make_text_op(
                "st.caption",
                elem,
                after,
                "caption_scope_city",
                semantic_slot="Geo_City_Name",
            )
        )

    object_op = mutate_caption_scope_object(data, elem, rng)
    if object_op:
        candidates.append(object_op)

    return rng.choice(candidates) if candidates else None


def mutate_caption_scope_object(
    data: dict[str, Any], elem: dict[str, Any], rng: random.Random
) -> dict[str, Any] | None:
    """将 caption 模板中的 block scope 替换为同城市的另一个真实 block。"""
    context = caption_context(data)
    city = str(context.get("Geo_City_Name", "")).strip()
    block = str(context.get("Geo_Block_Name", "")).strip()
    if not city or not block:
        return None

    donor_blocks = [
        candidate for candidate in load_ground_truth_blocks(city) if candidate != block
    ]
    if not donor_blocks:
        return None

    wrong_block = rng.choice(donor_blocks)
    after = render_caption_text(
        data,
        elem,
        context_overrides={"Geo_Block_Name": wrong_block},
    )
    return make_text_op(
        "st.caption",
        elem,
        after,
        "caption_scope_object",
        semantic_slot="Geo_Block_Name",
    )


def mutate_caption_chart_type(
    data: dict[str, Any], elem: dict[str, Any], rng: random.Random
) -> dict[str, Any] | None:
    """将 caption 绑定的可见图表/表格类型标签替换为另一个类型。"""
    labels = ["Bar chart", "Line chart", "Pie chart", "Table"]
    binding = caption_binding(data, elem)
    current_label = binding["view_label"]
    if current_label not in labels:
        return None
    wrong_label = rng.choice(
        [candidate for candidate in labels if candidate != current_label]
    )
    after = render_caption_text(data, elem, view_label_override=wrong_label)
    return make_text_op(
        "st.caption",
        elem,
        after,
        "caption_chart_type_mismatch",
        semantic_slot="Chart_View_Label",
    )


def caption_context(data: dict[str, Any]) -> dict[str, str]:
    """从 query_filters 构造 caption 模板所需的 scope context。"""
    query_filters = data.get("query_filters", {})
    if not isinstance(query_filters, dict):
        return {}
    return {
        "Geo_City_Name": str(query_filters.get("city", "")),
        "Geo_Block_Name": str(query_filters.get("block", "")),
        "Temporal_Start_Year": str(query_filters.get("start_date", ""))[:4],
        "Temporal_End_Year": str(query_filters.get("end_date", ""))[:4],
    }


def render_caption_text(
    data: dict[str, Any],
    elem: dict[str, Any],
    *,
    context_overrides: dict[str, str] | None = None,
    view_label_override: str | None = None,
) -> str:
    """从 template_id/layout 推导 caption 绑定，并重新渲染 caption 文本。"""
    binding = caption_binding(data, elem)
    context = caption_context(data)
    if context_overrides:
        context.update(context_overrides)
    caption = resource_manager.render_text(
        binding["theme_key"],
        binding["function_key"],
        "caption",
        context,
    )
    view_label = view_label_override or binding["view_label"]
    return f"{caption} ({view_label})"


def caption_binding(data: dict[str, Any], elem: dict[str, Any]) -> dict[str, Any]:
    """根据 caption 元素在 slide 中的位置，推导其模板函数和数据槽绑定。"""
    template_id = YAMLImporter.resolve_template_id(data, "<memory>")
    template_meta = resource_manager.get_template(template_id)
    if template_meta is None:
        resource_manager.load_all()
        template_meta = resource_manager.get_template(template_id)
    if template_meta is None:
        raise ValueError(f"Template not found: {template_id}")

    captions = find_text_elements(data, "caption")
    elem_id = str(elem.get("id", ""))
    caption_index = next(
        (
            idx
            for idx, caption in enumerate(captions)
            if str(caption.get("id", "")) == elem_id
        ),
        None,
    )
    if caption_index is None:
        raise ValueError(f"Caption element not found in template_slide: {elem_id}")

    caption_slots = [
        slot
        for slot in layout_manager.get_text_slots(template_meta.layout_type)
        if slot.part == "caption"
    ]
    if caption_index >= len(caption_slots):
        raise ValueError(
            f"Caption element index {caption_index} exceeds caption slots for {template_id}"
        )
    caption_slot = caption_slots[caption_index]
    function_index = caption_slot.function_index
    if function_index is None:
        raise ValueError(f"Caption slot missing function_index for {template_id}")
    if function_index >= len(template_meta.function_key):
        raise ValueError(
            f"Caption function_index={function_index} out of range for {template_id}"
        )

    data_slots = layout_manager.get_layout_slots(template_meta.layout_type)
    if function_index >= len(data_slots):
        raise ValueError(
            f"Caption function_index={function_index} has no matching data slot for {template_id}"
        )
    data_slot = data_slots[function_index]
    data_key = template_meta.data_keys.get(data_slot.name)
    if not data_key:
        raise ValueError(
            f"Missing data mapping for caption slot '{data_slot.name}' in {template_id}"
        )

    return {
        "theme_key": template_meta.theme_key,
        "function_index": function_index,
        "function_key": template_meta.function_key[function_index],
        "data_key": data_key,
        "view_label": view_label_for_data_slot(data_slot),
    }


def view_label_for_data_slot(slot) -> str:
    """根据 layout data slot 推导 caption 末尾可见的视图类型标签。"""
    slot_type = getattr(slot.type, "value", slot.type)
    if slot_type == "table":
        return "Table"
    if slot_type != "chart":
        raise ValueError(f"Unsupported caption data slot type: {slot.type}")

    role = slot.role.lower()
    if "bar" in role:
        return "Bar chart"
    if "line" in role:
        return "Line chart"
    if "pie" in role:
        return "Pie chart"
    return "Chart"


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
    return make_text_op(
        "title",
        elem,
        rng.choice(donors),
        "title_theme_drift",
        semantic_slot="title",
    )


def apply_text_op(data: dict[str, Any], op: dict[str, Any]) -> None:
    """将文本操作应用到 YAML 中匹配的 textBox 元素。"""
    for elem in find_text_elements(data):
        if str(elem.get("id", "")) == str(op.get("element_id", "")):
            elem["text"] = op["_after"]
            return
    raise ValueError(f"Text element not found: {op.get('element_id')}")


def find_summary_element(data: dict[str, Any]) -> dict[str, Any] | None:
    """返回当前 slide 中承载 Summary 的正文文本元素。"""
    elems = find_text_elements(data, "body-text")
    return elems[0] if elems else None


def derive_summary_truth(data: dict[str, Any]) -> dict[str, Any]:
    """从模板、查询条件和数据库即时推导 Summary 模板与真值 slot。"""
    template_id = YAMLImporter.resolve_template_id(data, "<memory>")
    template_meta = resource_manager.get_template(template_id)
    if template_meta is None:
        resource_manager.load_all()
        template_meta = resource_manager.get_template(template_id)
    if template_meta is None:
        raise ValueError(f"Template not found: {template_id}")

    summary_function_key = (
        template_meta.summary_function_key or template_meta.function_key[0]
    )
    summary_template = resource_manager.get_summary_template(
        template_meta.theme_key,
        summary_function_key,
        template_meta.summary_item,
    )
    template_keys = extract_template_variables(summary_template)
    conclusion_vars = fetch_summary_conclusion_vars(data, summary_function_key)
    fixed_context = summary_fixed_context(data, template_keys)
    truth_slots = {
        key: conclusion_vars[key] for key in template_keys if key in conclusion_vars
    }

    return {
        "summary_template": summary_template,
        "template_keys": template_keys,
        "truth_slots": truth_slots,
        "fixed_context": fixed_context,
    }


def extract_template_variables(template_text: str) -> list[str]:
    """提取 Jinja 模板变量名，保持模板中的首次出现顺序。"""
    pattern = r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}"
    ordered = []
    seen = set()
    for match in re.findall(pattern, template_text):
        if match not in seen:
            seen.add(match)
            ordered.append(match)
    return ordered


def fetch_summary_conclusion_vars(
    data: dict[str, Any],
    summary_function_key: str,
) -> dict[str, Any]:
    """按 Summary 对应 function_key 重查数据库，得到当前 GT 的结论变量。"""
    query_filters = data.get("query_filters", {})
    slide_filter = find_slide_filter(data, summary_function_key)
    if not isinstance(query_filters, dict) or not isinstance(slide_filter, dict):
        raise ValueError("query_filters and slide_filters are required for summary")

    city = str(query_filters.get("city", "Beijing"))
    block = str(query_filters.get("block", "Unknown"))
    start_year = str(query_filters.get("start_date", "2020-01-01"))[:4]
    end_year = str(query_filters.get("end_date", "2024-12-31"))[:4]
    table_name = str(slide_filter.get("connection", {}).get("table", [""])[0])

    provider = RealEstateDataProvider(
        city=city,
        block=block,
        start_year=start_year,
        end_year=end_year,
        table_name=table_name,
    )
    fun_tool = slide_filter.get("fun_tool", {})
    fun_args = fun_tool.get("args", {})
    if not isinstance(fun_args, dict):
        fun_args = {}
    valid_args = filter_function_args(summary_function_key, fun_args)
    _, conclusion_vars, _ = provider.execute_by_function_key(
        summary_function_key,
        **valid_args,
    )
    return conclusion_vars


def find_slide_filter(
    data: dict[str, Any],
    function_key: str,
) -> dict[str, Any] | None:
    """在 slide_filters 中查找 Summary 对应的数据查询配置。"""
    slide_filters = data.get("slide_filters", [])
    if not isinstance(slide_filters, list) or not slide_filters:
        return None
    for slide_filter in slide_filters:
        if not isinstance(slide_filter, dict):
            continue
        fun_tool = slide_filter.get("fun_tool", {})
        if isinstance(fun_tool, dict) and fun_tool.get("fun") == function_key:
            return slide_filter
    first = slide_filters[0]
    return first if isinstance(first, dict) else None


def summary_fixed_context(
    data: dict[str, Any],
    template_keys: list[str],
) -> dict[str, str]:
    """从 query_filters 生成 Summary 渲染需要的固定 scope 变量。"""
    query_filters = data.get("query_filters", {})
    if not isinstance(query_filters, dict):
        return {}
    values = {
        "Geo_City_Name": str(query_filters.get("city", "")),
        "Geo_Block_Name": str(query_filters.get("block", "")),
        "Temporal_Start_Year": str(query_filters.get("start_date", ""))[:4],
        "Temporal_End_Year": str(query_filters.get("end_date", ""))[:4],
    }
    return {key: values[key] for key in template_keys if key in values and values[key]}


def render_summary_text(
    summary_truth: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> str:
    """用真值 slot 和本次 override 渲染 Summary 文本，不写回 YAML。"""
    render_context = {}
    for section in ("truth_slots", "fixed_context"):
        values = summary_truth.get(section, {})
        if isinstance(values, dict):
            render_context.update(values)
    if overrides:
        render_context.update(overrides)
    return Template(str(summary_truth["summary_template"])).render(**render_context)


def mutate_summary(
    data: dict[str, Any],
    rng: random.Random,
    forced_slot: str | None = None,
    forced_value: Any | None = None,
) -> dict[str, Any] | None:
    """通过 scope 文本替换或即时推导的 summary slot 构造 Summary 错误。"""
    elem = find_summary_element(data)
    if elem is None:
        return None
    summary_truth = derive_summary_truth(data)
    truth_slots = summary_truth.get("truth_slots", {})
    if not isinstance(truth_slots, dict) or not truth_slots:
        return None

    if forced_slot is not None:
        if forced_slot not in truth_slots:
            return None
        slot_name = forced_slot
        after_value = str(forced_value)
        mutation_type = "linked_numeric_delta"
    else:
        scope_ops = mutate_summary_scope(data, elem, summary_truth, rng)
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

    after_text = render_summary_text(summary_truth, {slot_name: str(after_value)})

    op = make_text_op("summary", elem, after_text, mutation_type)
    op["semantic_slot"] = slot_name
    return op


def mutate_summary_scope(
    data: dict[str, Any],
    elem: dict[str, Any],
    summary_truth: dict[str, Any],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """仅对模板真实声明的 scope 变量，生成 Summary-only 即时重渲染错误候选。"""
    ops = []
    fixed_context = summary_truth.get("fixed_context", {})
    if not isinstance(fixed_context, dict):
        return ops

    year_slots = [
        slot
        for slot in ("Temporal_Start_Year", "Temporal_End_Year")
        if fixed_context.get(slot)
    ]
    if year_slots:
        semantic_slot = rng.choice(year_slots)
        truth_year = str(fixed_context[semantic_slot])
        wrong_year = str(int(truth_year) + rng.choice([-1, 1]))
        after = render_summary_text(summary_truth, {semantic_slot: wrong_year})
        ops.append(
            make_text_op(
                "summary",
                elem,
                after,
                "summary_scope_year",
                semantic_slot=semantic_slot,
            )
        )

    city = str(fixed_context.get("Geo_City_Name", "")).strip()
    city_donors = [candidate for candidate in ["Beijing", "Guangzhou", "Shenzhen"] if candidate != city]
    if city and city_donors:
        wrong_city = rng.choice(city_donors)
        after = render_summary_text(summary_truth, {"Geo_City_Name": wrong_city})
        ops.append(
            make_text_op(
                "summary",
                elem,
                after,
                "summary_scope_city",
                semantic_slot="Geo_City_Name",
            )
        )

    block = str(fixed_context.get("Geo_Block_Name", "")).strip()
    if block and city:
        donor_blocks = [
            candidate
            for candidate in load_ground_truth_blocks(city)
            if candidate != block
        ]
        if donor_blocks:
            wrong_block = rng.choice(donor_blocks)
            after = render_summary_text(summary_truth, {"Geo_Block_Name": wrong_block})
            ops.append(
                make_text_op(
                    "summary",
                    elem,
                    after,
                    "summary_scope_object",
                    semantic_slot="Geo_Block_Name",
                )
            )

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
    slots = derive_summary_truth(data).get("truth_slots", {})
    result = {}
    if not isinstance(slots, dict):
        return result
    for name, value in slots.items():
        key = number_key(value)
        if key is not None:
            result[key] = (name, str(value))
    return result


def load_truth_data(data: dict[str, Any]) -> tuple[list[pd.DataFrame], list[str]]:
    """基于 YAML filters 重算 GT 数据，并忽略已有 mutated_data。"""
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

    overrides = data.get("mutated_data", {})
    if not isinstance(overrides, dict):
        overrides = {}
    overrides = dict(overrides)
    overrides[data_key] = dataframe_to_split_payload(df)
    data["mutated_data"] = overrides

    elem = data_elems[data_idx] if data_idx < len(data_elems) else {}
    op = {
        "target": "st.body",
        "element_id": str(elem.get("id", "")),
        "role": elem.get("role"),
        "data_key": data_key,
        "semantic_slot": "data_cell",
        "cell": {
            "row_index": row_pos,
            "row_label": scalar_to_json(df.index[row_pos]),
            "column_index": col_pos,
            "column": scalar_to_json(df.columns[col_pos]),
        },
        "mutation_type": "data_numeric_delta",
    }
    slot_name = linked_slot[0] if linked_slot else None
    slot_after = (
        format_like_number(parse_number(after_value), linked_slot[1])
        if linked_slot
        else None
    )
    return op, slot_name, slot_after


def apply_ops(data: dict[str, Any], ops: list[dict[str, Any]]) -> None:
    """在 mutated_data 准备完成后应用所有文本操作。"""
    for op in ops:
        if op["target"] in {"title", "summary", "st.caption"}:
            apply_text_op(data, op)


def public_operation(op: dict[str, Any]) -> dict[str, Any]:
    """移除内部执行字段，得到写入 corruption.json 的最小 operation。"""
    return {
        key: copy.deepcopy(value)
        for key, value in op.items()
        if not key.startswith("_")
    }


def build_corruption(
    dataset_root: Path,
    sample_row: dict[str, Any],
    family: str,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any], str] | None:
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
    artifact_id = f"{sample_id}-{family}-{hashlib.md5(raw_id.encode()).hexdigest()[:8]}"  # noqa: S324
    corruption = {
        "operations": [public_operation(op) for op in operations],
        "expected_repair_yaml": sample_row["gt_yaml"],
    }
    return data, corruption, artifact_id
