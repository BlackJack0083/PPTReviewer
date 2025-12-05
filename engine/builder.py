from dataclasses import dataclass
from typing import Any

from loguru import logger

from config import LayoutCoordinates
from core import LayoutType, PresentationContext, TemplateMeta, resource_manager


class SlideElementBuilder:
    """幻灯片元素构建器，负责构建不同类型的元素配置"""

    @staticmethod
    def build_text_element(text: str, role: str, layout: dict) -> dict[str, Any]:
        """通用的文本元素构建方法"""
        return {
            "type": "textBox",
            "role": role,
            "text": text,
            "layout": layout,
        }

    @staticmethod
    def build_data_element(
        element_type: str,  # "chart" or "table"
        role: str,
        layout: dict[str, Any],
        data_key: str,
        context: PresentationContext,
    ) -> dict[str, Any]:
        """通用的数据元素构建方法 (合并了图表和表格)"""
        try:
            data_payload = context.get_dataset(data_key)
        except ValueError as e:
            logger.error(f"Failed to get data for key '{data_key}': {e}")
            data_payload = None

        return {
            "type": element_type,
            "role": role,
            "layout": layout,
            "data_key": data_key,
            "data_payload": data_payload,
        }


@dataclass
class DataSlotConfig:
    """定义一个数据槽位的配置"""

    key_name_in_meta: str  # 在 TemplateMeta.data_keys 中的键名 (e.g., "chart_main")
    layout: dict  # 布局坐标
    element_type: str  # "chart" or "table"
    role: str  # 元素的角色 (e.g., "chart-bar")


class LayoutStrategyManager:
    """版式策略管理器：定义每种 LayoutType 需要填充哪些槽位"""

    # 定义布局映射表
    _STRATEGIES: dict[LayoutType, list[DataSlotConfig]] = {
        LayoutType.SINGLE_COLUMN_BAR: [
            DataSlotConfig(
                "chart_main", LayoutCoordinates.CHART_SINGLE, "chart", "chart-bar"
            )
        ],
        LayoutType.SINGLE_COLUMN_LINE: [
            DataSlotConfig(
                "chart_main", LayoutCoordinates.CHART_SINGLE, "chart", "chart-line"
            )
        ],
        LayoutType.DOUBLE_COLUMN_BAR: [
            DataSlotConfig(
                "chart_left", LayoutCoordinates.CHART_DOUBLE_LEFT, "chart", "chart-bar"
            ),
            DataSlotConfig(
                "chart_right",
                LayoutCoordinates.CHART_DOUBLE_RIGHT,
                "chart",
                "chart-bar",
            ),
        ],
        LayoutType.DOUBLE_COLUMN_LINE: [
            DataSlotConfig(
                "chart_left", LayoutCoordinates.CHART_DOUBLE_LEFT, "chart", "chart-line"
            ),
            DataSlotConfig(
                "chart_right",
                LayoutCoordinates.CHART_DOUBLE_RIGHT,
                "chart",
                "chart-line",
            ),
        ],
        LayoutType.SINGLE_COLUMN_TABLE: [
            DataSlotConfig(
                "table_main", LayoutCoordinates.TABLE_MAIN, "table", "table-main"
            )
        ],
    }

    @classmethod
    def get_slots(cls, layout_type: LayoutType) -> list[DataSlotConfig]:
        return cls._STRATEGIES.get(layout_type, [])


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
    ) -> dict[str, Any]:
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

        return {
            "layout_type": template_metadata.layout_type,
            "template_slide": {"elements": elements},
        }

    def _build_static_elements(
        self, meta: TemplateMeta, ctx: PresentationContext
    ) -> list[dict[str, Any]]:
        """构建标题、描述等静态文本"""
        # 定义需要渲染的文本字段
        text_fields = [
            ("slide_title", "slide-title", LayoutCoordinates.TITLE, None),
            ("caption", "caption", LayoutCoordinates.CAPTION, None),
            ("summary", "body-text", LayoutCoordinates.DESCRIPTION, meta.summary_item),
        ]

        elements = []
        for func_role, element_role, layout, item_key in text_fields:
            text_content = resource_manager.render_text(
                meta.theme_key, meta.function_key, func_role, ctx.variables, item_key
            )
            elements.append(
                SlideElementBuilder.build_text_element(
                    text_content, element_role, layout
                )
            )
        return elements

    def _inject_data_elements(
        self,
        elements: list[dict[str, Any]],
        meta: TemplateMeta,
        ctx: PresentationContext,
    ) -> None:
        """
        核心优化点：
        不再写一堆 if-else，而是根据 LayoutType 获取槽位配置列表，通用处理。
        """
        slots = LayoutStrategyManager.get_slots(meta.layout_type)

        if not slots:
            logger.warning(f"No layout strategy defined for: {meta.layout_type}")
            return

        for slot in slots:
            # 从模板元数据的 data_keys 中查找实际的数据 Key
            # 例如: meta.data_keys["chart_main"] -> "Actual_Dataset_Key_001"
            actual_data_key = meta.data_keys.get(slot.key_name_in_meta)

            if actual_data_key:
                element = SlideElementBuilder.build_data_element(
                    element_type=slot.element_type,
                    role=slot.role,
                    layout=slot.layout,
                    data_key=actual_data_key,
                    context=ctx,
                )
                elements.append(element)
            else:
                logger.warning(
                    f"Missing data mapping for slot '{slot.key_name_in_meta}' in template {meta.uid}"
                )
