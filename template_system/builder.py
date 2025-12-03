from typing import Any

from loguru import logger

from data_manager.context import PresentationContext

from .catalog import LayoutType, TemplateMeta, get_template_by_id
from .text_manager import TextTemplateManager

# 初始化文本管理器
text_manager = TextTemplateManager("template_system/text_pattern.yaml")


class SlideElementBuilder:
    """幻灯片元素构建器，负责构建不同类型的元素配置"""

    # 默认布局常量
    TITLE_LAYOUT = {"x": 0.5, "y": 1.0, "width": 18.0, "height": 1.1}
    DESCRIPTION_LAYOUT = {"x": 0.5, "y": 2.0, "width": 18.0, "height": 0.85}
    CHART_SINGLE_LAYOUT = {"x": 1.1, "y": 3.5, "width": 20.0, "height": 7.0}
    CHART_DOUBLE_LEFT_LAYOUT = {"x": 0.75, "y": 4.94, "width": 10.5, "height": 6.5}
    CHART_DOUBLE_RIGHT_LAYOUT = {"x": 12.75, "y": 4.94, "width": 10.5, "height": 6.5}
    TABLE_LAYOUT = {"x": 1.5, "y": 3.5, "width": 18.0, "height": 8.0}

    @staticmethod
    def build_title_element(title_text: str) -> dict[str, Any]:
        """构建标题元素"""
        return {
            "type": "textBox",
            "role": "slide-title",
            "text": title_text,
            "layout": SlideElementBuilder.TITLE_LAYOUT,
        }

    @staticmethod
    def build_description_element(description_text: str) -> dict[str, Any]:
        """构建描述元素"""
        return {
            "type": "textBox",
            "role": "body-text",
            "text": description_text,
            "layout": SlideElementBuilder.DESCRIPTION_LAYOUT,
        }

    @staticmethod
    def build_chart_element(
        role: str, layout: dict[str, Any], data_key: str, context: PresentationContext
    ) -> dict[str, Any]:
        """构建图表元素"""
        try:
            chart_data = context.get_dataset(data_key)
        except ValueError as e:
            logger.error(f"Failed to get chart data for key '{data_key}': {e}")
            chart_data = None

        return {
            "type": "chart",
            "role": role,
            "layout": layout,
            "data_key": data_key,  # 存储数据键，而不是直接存储DataFrame
            "data_payload": chart_data,  # 保持向后兼容
        }

    @staticmethod
    def build_table_element(
        role: str, layout: dict[str, Any], data_key: str, context: PresentationContext
    ) -> dict[str, Any]:
        """构建表格元素"""
        try:
            table_data = context.get_dataset(data_key)
        except ValueError as e:
            logger.error(f"Failed to get table data for key '{data_key}': {e}")
            table_data = None

        return {
            "type": "table",
            "role": role,
            "layout": layout,
            "data_key": data_key,
            "data_payload": table_data,
        }


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
        variant_idx: int = 0,
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
        template_metadata = get_template_by_id(template_id)
        if not template_metadata:
            raise ValueError(f"未找到模板 ID: {template_id}")

        logger.info(f"Building slide config for template: {template_id}")

        # 1. 动态生成文本内容
        title_text = text_manager.render(
            template_metadata.theme_key,
            template_metadata.function_key,
            "title",
            presentation_context.variables,
        )
        desc_text = text_manager.render(
            template_metadata.theme_key,
            template_metadata.function_key,
            "summary",
            presentation_context.variables,
            variant_idx,
        )

        # 2. 构建基础元素
        elements = [
            self.element_builder.build_title_element(title_text),
            self.element_builder.build_description_element(desc_text),
        ]

        # 3. 根据版式类型添加数据元素
        self._inject_data_elements(elements, template_metadata, presentation_context)

        return {
            "layout_type": template_metadata.layout_type,  # 动态决定版式
            "template_slide": {"elements": elements},
        }

    def _inject_data_elements(
        self,
        elements: list[dict[str, Any]],
        template_metadata: TemplateMeta,
        presentation_context: PresentationContext,
    ) -> None:
        """
        根据版式类型和数据映射注入数据元素

        Args:
            elements: 元素列表，会直接修改此列表
            template_metadata: 模板元数据
            presentation_context: 数据上下文
        """
        layout_type = template_metadata.layout_type
        data_keys = template_metadata.data_keys

        try:
            if layout_type == LayoutType.SINGLE_COLUMN_BAR:
                self._build_single_column_bar(elements, data_keys, presentation_context)
            elif layout_type == LayoutType.SINGLE_COLUMN_LINE:
                self._build_single_column_line(
                    elements, data_keys, presentation_context
                )
            elif layout_type == LayoutType.DOUBLE_COLUMN_BAR:
                self._build_double_column_bar(elements, data_keys, presentation_context)
            elif layout_type == LayoutType.DOUBLE_COLUMN_LINE:
                self._build_double_column_line(
                    elements, data_keys, presentation_context
                )
            elif layout_type == LayoutType.SINGLE_COLUMN_TABLE:
                self._build_single_column_table(
                    elements, data_keys, presentation_context
                )
            else:
                logger.warning(f"Unsupported layout type: {layout_type}")

        except Exception as e:
            logger.error(
                f"Failed to inject data elements for layout {layout_type}: {e}"
            )
            raise

    def _build_single_column_bar(
        self,
        elements: list[dict[str, Any]],
        data_keys: dict[str, str],
        presentation_context: PresentationContext,
    ) -> None:
        """构建单栏柱状图元素"""
        main_data_key = data_keys.get("chart_main")
        if main_data_key:
            chart_element = self.element_builder.build_chart_element(
                role="chart-bar",
                layout=self.element_builder.CHART_SINGLE_LAYOUT,
                data_key=main_data_key,
                context=presentation_context,
            )
            elements.append(chart_element)

    def _build_single_column_line(
        self,
        elements: list[dict[str, Any]],
        data_keys: dict[str, str],
        presentation_context: PresentationContext,
    ) -> None:
        """构建单栏折线图元素"""
        main_data_key = data_keys.get("chart_main")
        if main_data_key:
            chart_element = self.element_builder.build_chart_element(
                role="chart-line",
                layout=self.element_builder.CHART_SINGLE_LAYOUT,
                data_key=main_data_key,
                context=presentation_context,
            )
            elements.append(chart_element)

    def _build_double_column_bar(
        self,
        elements: list[dict[str, Any]],
        data_keys: dict[str, str],
        presentation_context: PresentationContext,
    ) -> None:
        """构建双栏柱状图元素"""
        left_data_key = data_keys.get("chart_left")
        if left_data_key:
            chart_element = self.element_builder.build_chart_element(
                role="chart-bar",
                layout=self.element_builder.CHART_DOUBLE_LEFT_LAYOUT,
                data_key=left_data_key,
                context=presentation_context,
            )
            elements.append(chart_element)

        right_data_key = data_keys.get("chart_right")
        if right_data_key:
            chart_element = self.element_builder.build_chart_element(
                role="chart-bar",
                layout=self.element_builder.CHART_DOUBLE_RIGHT_LAYOUT,
                data_key=right_data_key,
                context=presentation_context,
            )
            elements.append(chart_element)

    def _build_double_column_line(
        self,
        elements: list[dict[str, Any]],
        data_keys: dict[str, str],
        presentation_context: PresentationContext,
    ) -> None:
        """构建双栏折线图元素"""
        left_data_key = data_keys.get("chart_left")
        if left_data_key:
            chart_element = self.element_builder.build_chart_element(
                role="chart-line",
                layout=self.element_builder.CHART_DOUBLE_LEFT_LAYOUT,
                data_key=left_data_key,
                context=presentation_context,
            )
            elements.append(chart_element)

        right_data_key = data_keys.get("chart_right")
        if right_data_key:
            chart_element = self.element_builder.build_chart_element(
                role="chart-line",
                layout=self.element_builder.CHART_DOUBLE_RIGHT_LAYOUT,
                data_key=right_data_key,
                context=presentation_context,
            )
            elements.append(chart_element)

    def _build_single_column_table(
        self,
        elements: list[dict[str, Any]],
        data_keys: dict[str, str],
        presentation_context: PresentationContext,
    ) -> None:
        """构建单栏表格元素"""
        table_data_key = data_keys.get("table_main")
        if table_data_key:
            table_element = self.element_builder.build_table_element(
                role="table-main",
                layout=self.element_builder.TABLE_LAYOUT,
                data_key=table_data_key,
                context=presentation_context,
            )
            elements.append(table_element)
