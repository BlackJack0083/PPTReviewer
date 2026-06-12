import re
from typing import Any

from loguru import logger

from core import (
    LayoutModel,
    PresentationContext,
    TemplateMeta,
    layout_manager,
    resource_manager,
)
from core.schemas import (
    ChartElement,
    ElementType,
    RenderableElement,
    SlideRenderConfig,
    SlotDefinition,
    TableElement,
    TextElement,
    TextSlotDefinition,
)

TEMPLATE_VARIABLE_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")
SCOPE_FIELDS = {
    "Geo_City_Name": "city",
    "Geo_Block_Name": "block",
    "Temporal_Start_Year": "start_year",
    "Temporal_End_Year": "end_year",
}


def _template_slots(template: str, variables: dict[str, Any]) -> dict[str, dict[str, Any]]:
    slots = {}
    for name in _template_variables(template):
        if name not in variables:
            raise ValueError(f"Missing text binding variable: {name}")
        slots[name] = _slot_binding(name, variables[name])
    return slots


def _template_variables(template: str) -> list[str]:
    names = []
    seen = set()
    for name in TEMPLATE_VARIABLE_RE.findall(template):
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _slot_binding(name: str, value: Any) -> dict[str, Any]:
    binding = {
        "category": _slot_category(name),
        "value": str(value),
        "value_type": _slot_value_type(name, value),
    }
    if name in SCOPE_FIELDS:
        binding["field"] = SCOPE_FIELDS[name]
    return binding


def _slot_category(name: str) -> str:
    if name in SCOPE_FIELDS:
        return "scope"
    if name.startswith(("Trend_", "Enum_", "Text_")):
        return "claim"
    return "value"


def _slot_value_type(name: str, value: Any) -> str:
    if name.startswith(("Trend_", "Enum_", "Text_")):
        return "trend"
    text = str(value).replace(",", "").replace("%", "").strip()
    try:
        float(text)
    except ValueError:
        return "string"
    return "number"


class SlideElementBuilder:
    """幻灯片元素构建器，负责构建不同类型的元素配置"""

    @staticmethod
    def build_text_element(
        text: str,
        role: str,
        layout: LayoutModel,
        text_binding: dict[str, Any] | None = None,
    ) -> TextElement:
        """通用的文本元素构建方法"""
        return TextElement(
            role=role,
            text=str(text),
            layout=layout,
            text_binding=text_binding,
        )

    @staticmethod
    def build_data_element(
        element_type: str,  # "chart" or "table"
        role: str,
        layout: LayoutModel,
        data_key: str,
        context: PresentationContext,
    ) -> ChartElement | TableElement:
        """通用的数据元素构建方法 (合并了图表和表格)"""
        try:
            data_payload = context.get_dataset(data_key)
        except ValueError as e:
            logger.error(f"Failed to get data for key '{data_key}': {e}")
            raise e

        # 从 context 获取配置（用于 YAML 导出）
        config = context.get_config(data_key)

        if element_type == ElementType.CHART:
            return ChartElement(
                role=role,
                layout=layout,
                data_key=data_key,
                data_payload=data_payload,
                config=config,
            )
        elif element_type == ElementType.TABLE:
            return TableElement(
                role=role, layout=layout, data_key=data_key, data_payload=data_payload
            )
        else:
            raise ValueError(f"Unsupported data element type: {element_type}")


class SlideConfigBuilder:
    """幻灯片配置构建器

    职责：
    1. 根据模板ID和数据上下文构建完整的幻灯片渲染配置
    2. 支持动态文本生成和数据注入
    3. 提供统一的配置接口，降低各组件间的耦合度
    """

    def __init__(self):
        self.element_builder = SlideElementBuilder()

    def build(
        self,
        template_id: str,
        presentation_context: PresentationContext,
    ) -> SlideRenderConfig:
        """
        构建幻灯片渲染配置

        Args:
            template_id (str): 模板ID，如 "T01_Area_Supply_Demand"
            presentation_context (PresentationContext): 包含数据和变量的上下文

        Returns:
            Dict[str, Any]: 完整的幻灯片渲染配置

        Raises:
            ValueError: 模板不存在或变量缺失时抛出异常
        """
        template_metadata = resource_manager.get_template(template_id)
        if not template_metadata:
            raise ValueError(f"未找到模板 ID: {template_id}")

        logger.info(f"Building slide config for template: {template_id}")

        # 1. 构建固定文本元素 (标题, 描述, Caption)
        elements = self._build_static_elements(template_metadata, presentation_context)

        # 2. 动态注入数据元素 (根据 LayoutType 自动处理)
        self._inject_data_elements(elements, template_metadata, presentation_context)

        return SlideRenderConfig(
            layout_type=template_metadata.layout_type,
            style_id=template_metadata.style_config_id,
            elements=elements,
        )

    def _build_static_elements(
        self, meta: TemplateMeta, ctx: PresentationContext
    ) -> list[RenderableElement]:
        """按 layout_type 定义的 text_slots 构建静态文本。"""
        text_slots = layout_manager.get_text_slots(meta.layout_type)
        if not text_slots:
            raise ValueError(f"No text slots defined for layout: {meta.layout_type}")

        elements = []
        for slot in text_slots:
            text_content = self._render_text_for_slot(slot, meta, ctx)
            text_binding = self._build_text_binding(slot, meta, ctx)
            layout_model = LayoutModel.model_validate(slot.model_dump(by_alias=True))
            elements.append(
                SlideElementBuilder.build_text_element(
                    text_content,
                    slot.role,
                    layout_model,
                    text_binding,
                )
            )
        return elements

    def _render_text_for_slot(
        self,
        slot: TextSlotDefinition,
        meta: TemplateMeta,
        ctx: PresentationContext,
    ) -> str:
        """根据文本槽位定义渲染具体文本。"""
        if slot.part == "slide_title":
            return resource_manager.render_text(
                meta.theme_key,
                meta.function_key[0],
                "slide_title",
                ctx.variables,
            )

        if slot.part == "summary":
            summary_function_key = meta.summary_function_key or meta.function_key[0]
            return resource_manager.render_text(
                meta.theme_key,
                summary_function_key,
                "summary",
                ctx.variables,
                meta.summary_item,
            )

        if slot.part == "caption":
            if slot.function_index is None:
                raise ValueError(
                    f"caption text slot missing function_index for template {meta.uid}"
                )
            function_keys = meta.function_key
            if slot.function_index >= len(function_keys):
                raise ValueError(
                    f"caption text slot function_index={slot.function_index} "
                    f"out of range for template {meta.uid} with function_keys={function_keys}"
                )
            caption = resource_manager.render_text(
                meta.theme_key,
                function_keys[slot.function_index],
                "caption",
                ctx.variables,
            )
            return self._add_caption_view_label(caption, meta, slot)

        raise ValueError(f"Unsupported text slot part: {slot.part}")

    def _build_text_binding(
        self,
        slot: TextSlotDefinition,
        meta: TemplateMeta,
        ctx: PresentationContext,
    ) -> dict[str, Any] | None:
        if slot.part == "slide_title":
            return None
        if slot.part == "summary":
            function_key = meta.summary_function_key or meta.function_key[0]
            template = resource_manager.get_summary_template(
                meta.theme_key,
                function_key,
                meta.summary_item,
            )
            return {
                "kind": "summary",
                "render": {
                    "theme_key": meta.theme_key,
                    "function_key": function_key,
                    "variant_idx": meta.summary_item,
                },
                "slots": _template_slots(template, ctx.variables),
            }
        if slot.part == "caption":
            if slot.function_index is None:
                raise ValueError(
                    f"caption text slot missing function_index for template {meta.uid}"
                )
            function_key = meta.function_key[slot.function_index]
            template = resource_manager.get_caption_template(meta.theme_key, function_key)
            binding = {
                "kind": "caption",
                "render": {
                    "theme_key": meta.theme_key,
                    "function_key": function_key,
                    "function_index": slot.function_index,
                    "view_label": self._caption_view_label(meta, slot),
                },
                "slots": _template_slots(template, ctx.variables),
            }
            binding["slots"]["Chart_View_Label"] = {
                "category": "claim",
                "field": "presentation_type",
                "value": binding["render"]["view_label"],
                "value_type": "string",
            }
            return binding
        raise ValueError(f"Unsupported text slot part: {slot.part}")

    def _add_caption_view_label(
        self,
        caption: str,
        meta: TemplateMeta,
        slot: TextSlotDefinition,
    ) -> str:
        """Make the ST rendering type visible in the generated PPT caption."""
        return f"{caption} ({self._caption_view_label(meta, slot)})"

    def _caption_view_label(
        self,
        meta: TemplateMeta,
        slot: TextSlotDefinition,
    ) -> str:
        if slot.function_index is None:
            raise ValueError(
                f"caption text slot missing function_index for template {meta.uid}"
            )
        data_slots = layout_manager.get_layout_slots(meta.layout_type)
        if slot.function_index >= len(data_slots):
            raise ValueError(
                f"caption text slot function_index={slot.function_index} "
                f"has no matching data slot for template {meta.uid}"
            )
        return self._view_label_for_data_slot(data_slots[slot.function_index])

    @staticmethod
    def _view_label_for_data_slot(slot: SlotDefinition) -> str:
        if slot.type == ElementType.TABLE:
            return "Table"
        if slot.type != ElementType.CHART:
            raise ValueError(f"Unsupported caption data slot type: {slot.type}")

        role = slot.role.lower()
        if "bar" in role:
            return "Bar chart"
        if "line" in role:
            return "Line chart"
        if "pie" in role:
            return "Pie chart"
        return "Chart"

    def _inject_data_elements(
        self,
        elements: list[RenderableElement],
        meta: TemplateMeta,
        ctx: PresentationContext,
    ) -> None:
        """
        核心优化点：
        不再写一堆 if-else，而是根据 LayoutType 获取槽位配置列表，通用处理。
        """
        slots = layout_manager.get_layout_slots(meta.layout_type)

        for slot in slots:
            # 从模板元数据的 data_keys 中查找实际的数据 Key
            # 例如: meta.data_keys["chart_main"] -> "Actual_Dataset_Key_001"
            actual_data_key = meta.data_keys.get(slot.name)
            layout = LayoutModel.model_validate(
                slot.model_dump(by_alias=False, exclude={"name", "type", "role"})
            )

            if not actual_data_key:
                raise ValueError(
                    f"Missing data mapping for slot '{slot.name}' in template {meta.uid}"
                )

            element = SlideElementBuilder.build_data_element(
                element_type=slot.type,
                role=slot.role,
                layout=layout,
                data_key=actual_data_key,
                context=ctx,
            )
            elements.append(element)
