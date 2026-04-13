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
    TableElement,
    TextElement,
    TextSlotDefinition,
)


class SlideElementBuilder:
    """幻灯片元素构建器，负责构建不同类型的元素配置"""

    @staticmethod
    def build_text_element(text: str, role: str, layout: LayoutModel) -> TextElement:
        """通用的文本元素构建方法"""
        return TextElement(role=role, text=str(text), layout=layout)  # 强转确保类型安全

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
            layout_model = LayoutModel.model_validate(slot.model_dump(by_alias=True))
            elements.append(
                SlideElementBuilder.build_text_element(
                    text_content,
                    slot.role,
                    layout_model,
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
            assert slot.function_index is not None
            function_keys = meta.function_key
            if slot.function_index >= len(function_keys):
                raise ValueError(
                    f"caption text slot function_index={slot.function_index} "
                    f"out of range for template {meta.uid} with function_keys={function_keys}"
                )
            return resource_manager.render_text(
                meta.theme_key,
                function_keys[slot.function_index],
                "caption",
                ctx.variables,
            )

        raise ValueError(f"Unsupported text slot part: {slot.part}")

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
