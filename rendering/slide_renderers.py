from typing import Any

import pandas as pd
from loguru import logger

from core.ppt_operations import PPTOperations
from core.ppt_schemas import (
    Align,
    BarChartConfig,
    Color,
    LayoutModel,
    LineChartConfig,
    RectangleStyleModel,
    TextContentModel,
)


class BaseSlideRenderer:
    """所有版式渲染器的基类

    职责：
    1. 提供统一的渲染接口和元素分发逻辑
    2. 定义通用的文本、图表、表格渲染方法
    3. 管理PPT操作对象的引用
    4. 解耦数据获取逻辑，专注于渲染逻辑
    """

    def __init__(self, ppt_operations: PPTOperations):
        """
        初始化渲染器

        Args:
            ppt_operations: PPT操作对象
        """
        self.ppt_operations = ppt_operations

    def render(self, slide_configuration: dict[str, Any], page_number: int) -> None:
        """
        主渲染入口

        Args:
            slide_configuration: 幻灯片配置字典
            page_number: 幻灯片页码（从1开始）
        """
        elements = slide_configuration.get("elements", [])
        if not elements:
            logger.warning(f"No elements to render for page {page_number}")
            return

        logger.info(f"Rendering page {page_number} with {len(elements)} elements")

        for element in elements:
            try:
                self._render_element(page_number, element)
            except Exception as e:
                logger.error(f"Failed to render element on page {page_number}: {e}")
                # 继续渲染其他元素，不因单个元素失败而中断整个渲染过程

    def _render_element(self, page_number: int, element: dict[str, Any]) -> None:
        """
        根据元素类型分发到具体的渲染方法

        Args:
            page_number: 幻灯片页码
            element: 元素配置字典
        """
        element_type = element.get("type")

        if element_type == "textBox":
            self._render_text_box(page_number, element)
        elif element_type == "chart":
            self._render_chart(page_number, element)
        elif element_type == "table":
            self._render_table(page_number, element)
        elif element_type == "rectangle":
            self._render_rectangle(page_number, element)
        elif element_type == "picture":
            self._render_picture(page_number, element)
        else:
            logger.warning(f"Unknown element type: {element_type}")

    def _map_layout(self, layout_config: dict[str, Any]) -> LayoutModel:
        """
        将布局配置转换为 LayoutModel

        Args:
            layout_config: 布局配置字典

        Returns:
            LayoutModel: 标准化的布局模型
        """
        return LayoutModel(
            left=layout_config.get("x", 0),
            top=layout_config.get("y", 0),
            width=layout_config.get("width", 0),
            height=layout_config.get("height", 0),
            alignment=Align.LEFT,
        )

    def _render_text_box(self, page_number: int, element: dict[str, Any]) -> None:
        """
        渲染文本框

        Args:
            page_number: 幻灯片页码
            element: 文本框元素配置
        """
        text_content = element.get("text", "")
        element_role = element.get("role", "")
        layout = self._map_layout(element.get("layout", {}))

        # 根据角色确定样式
        font_size, font_bold, font_color = self._get_text_style_by_role(element_role)

        content_model = TextContentModel(
            text=str(text_content),
            font_size=font_size,
            font_bold=font_bold,
            font_color=font_color,
            word_wrap=True,
        )

        self.ppt_operations.add_text_box(page_number, content_model, layout)

    def _get_text_style_by_role(
        self, role: str
    ) -> tuple[int, bool, Color]:  # noqa: SIM116
        """
        根据角色获取文本样式

        Args:
            role: 元素角色

        Returns:
            tuple: (字体大小, 是否加粗, 字体颜色)
        """
        if role == "slide-title":
            return 24, True, Color.BLACK
        elif role == "body-text":
            return 14, False, Color.DARK_BLUE
        elif role == "caption":
            return 10, False, Color.GRAY
        else:
            return 12, False, Color.BLACK  # noqa: SIM116

    def _render_chart(self, page_number: int, element: dict[str, Any]) -> None:
        """
        渲染图表（基类默认实现）

        Args:
            page_number: 幻灯片页码
            element: 图表元素配置
        """
        chart_role = element.get("role", "")
        layout = self._map_layout(element.get("layout", {}))

        # 获取图表数据，优先使用 data_payload（向后兼容），否则使用 data_key
        chart_data = element.get("data_payload")
        if chart_data is None:
            logger.warning(f"No data provided for chart element: {chart_role}")
            return

        if not isinstance(chart_data, pd.DataFrame):
            logger.error(f"Chart data must be a DataFrame, got {type(chart_data)}")
            return

        # 根据角色选择图表类型和配置
        if "bar" in chart_role.lower():
            config = self._get_bar_chart_config(chart_role)
            self.ppt_operations.add_bar_chart(page_number, chart_data, layout, config)
        elif "line" in chart_role.lower():
            config = self._get_line_chart_config(chart_role)
            self.ppt_operations.add_line_chart(page_number, chart_data, layout, config)
        else:
            logger.warning(f"Unknown chart role: {chart_role}")

    def _get_bar_chart_config(self, role: str) -> BarChartConfig:
        """获取柱状图配置"""
        return BarChartConfig(
            style_name="supply_trade",
            font_name="Arial",
            font_size=11,
            has_legend=True,
            has_data_labels=True,
            title=None,
            y_axis_visible=False,
            gap_width=150,
            overlap=0,
            grouping="clustered",
        )

    def _get_line_chart_config(self, role: str) -> LineChartConfig:
        """获取折线图配置"""
        return LineChartConfig(
            style_name="growth_trend",
            font_name="Arial",
            font_size=11,
            has_legend=True,
            has_data_labels=True,
            title=None,
            y_axis_visible=True,
            has_markers=True,
            smooth_line=True,
            line_width=2.25,
        )

    def _render_table(self, page_number: int, element: dict[str, Any]) -> None:
        """
        渲染表格

        Args:
            page_number: 幻灯片页码
            element: 表格元素配置
        """
        table_role = element.get("role", "")
        layout = self._map_layout(element.get("layout", {}))

        # 获取表格数据
        table_data = element.get("data_payload")
        if table_data is None:
            logger.warning(f"No data provided for table element: {table_role}")
            return

        if not isinstance(table_data, pd.DataFrame):
            logger.error(f"Table data must be a DataFrame, got {type(table_data)}")
            return

        # 默认表格样式
        font_name = "微软雅黑"
        font_size = 11

        self.ppt_operations.add_table(
            page_number=page_number,
            layout=layout,
            data=table_data,
            font_name=font_name,
            font_size=font_size,
        )

    def _render_rectangle(self, page_number: int, element: dict[str, Any]) -> None:
        """
        渲染矩形

        Args:
            page_number: 幻灯片页码
            element: 矩形元素配置
        """
        layout = self._map_layout(element.get("layout", {}))

        # 默认矩形样式
        style = RectangleStyleModel(
            fore_color=Color.GRAY,
            line_color=Color.GRAY,
            line_width=0,
            rotation=0,
            is_background=False,
        )

        self.ppt_operations.add_rectangle(page_number, layout, style)

    def _render_picture(self, page_number: int, element: dict[str, Any]) -> None:
        """
        渲染图片

        Args:
            page_number: 幻灯片页码
            element: 图片元素配置
        """
        image_path = element.get("image_path", "")
        layout = self._map_layout(element.get("layout", {}))

        if not image_path:
            logger.warning("No image path provided")
            return

        self.ppt_operations.add_picture(page_number, image_path, layout)


class SingleColumnBarRenderer(BaseSlideRenderer):
    """版式 1: 单栏柱状图渲染器"""

    def _render_chart(self, page_number: int, element: dict[str, Any]) -> None:
        """渲染单栏柱状图"""
        chart_role = element.get("role", "")
        layout = self._map_layout(element.get("layout", {}))

        chart_data = element.get("data_payload")
        if chart_data is None or not isinstance(chart_data, pd.DataFrame):
            logger.error(f"Invalid chart data for single column bar: {chart_role}")
            return

        config = BarChartConfig(
            style_name="supply_trade",
            font_name="Arial",
            font_size=11,
            has_legend=True,
            has_data_labels=True,
            title=None,
            y_axis_visible=False,  # 单栏大图通常隐藏Y轴
            gap_width=150,
            overlap=0,
            grouping="clustered",
        )

        self.ppt_operations.add_bar_chart(page_number, chart_data, layout, config)


class SingleColumnLineRenderer(BaseSlideRenderer):
    """版式 2: 单栏折线图渲染器"""

    def _render_chart(self, page_number: int, element: dict[str, Any]) -> None:
        """渲染单栏折线图"""
        chart_role = element.get("role", "")
        layout = self._map_layout(element.get("layout", {}))

        chart_data = element.get("data_payload")
        if chart_data is None or not isinstance(chart_data, pd.DataFrame):
            logger.error(f"Invalid chart data for single column line: {chart_role}")
            return

        config = LineChartConfig(
            style_name="growth_trend",
            font_name="Arial",
            font_size=11,
            has_legend=True,
            has_data_labels=True,
            title=None,
            y_axis_visible=True,
            has_markers=True,
            smooth_line=True,
            line_width=2.25,
        )

        self.ppt_operations.add_line_chart(page_number, chart_data, layout, config)


class DoubleColumnBarRenderer(BaseSlideRenderer):
    """版式 3: 双栏柱状图渲染器"""

    def _render_chart(self, page_number: int, element: dict[str, Any]) -> None:
        """渲染双栏柱状图"""
        chart_role = element.get("role", "")
        layout = self._map_layout(element.get("layout", {}))

        chart_data = element.get("data_payload")
        if chart_data is None or not isinstance(chart_data, pd.DataFrame):
            logger.error(f"Invalid chart data for double column bar: {chart_role}")
            return

        config = BarChartConfig(
            style_name="business_blue",
            font_name="Arial",
            font_size=12,  # 双栏图字体调整到正常大小
            has_legend=True,
            has_data_labels=True,
            title=None,
            y_axis_visible=False,
            gap_width=100,  # 柱子紧凑一点
            overlap=0,
            grouping="clustered",
        )

        self.ppt_operations.add_bar_chart(page_number, chart_data, layout, config)


class DoubleColumnLineRenderer(BaseSlideRenderer):
    """版式 4: 双栏折线图渲染器"""

    def _render_chart(self, page_number: int, element: dict[str, Any]) -> None:
        """渲染双栏折线图"""
        chart_role = element.get("role", "")
        layout = self._map_layout(element.get("layout", {}))

        chart_data = element.get("data_payload")
        if chart_data is None or not isinstance(chart_data, pd.DataFrame):
            logger.error(f"Invalid chart data for double column line: {chart_role}")
            return

        config = LineChartConfig(
            style_name="business_blue",
            font_name="Arial",
            font_size=12,  # 调整到正常大小
            has_legend=True,
            has_data_labels=True,  # 重新启用数值标签
            title=None,
            y_axis_visible=True,
            has_markers=True,
            smooth_line=False,  # 双栏较窄，建议直线
            line_width=2.0,
        )

        self.ppt_operations.add_line_chart(page_number, chart_data, layout, config)


class SingleColumnTableRenderer(BaseSlideRenderer):
    """版式 5: 单栏表格渲染器"""

    def _render_table(self, page_number: int, element: dict[str, Any]) -> None:
        """渲染单栏表格"""
        table_role = element.get("role", "")
        layout = self._map_layout(element.get("layout", {}))

        table_data = element.get("data_payload")
        if table_data is None or not isinstance(table_data, pd.DataFrame):
            logger.error(f"Invalid table data for single column table: {table_role}")
            return

        # 单栏表格可以使用更大的字体和更宽松的布局
        font_name = "微软雅黑"
        font_size = 11

        self.ppt_operations.add_table(
            page_number=page_number,
            layout=layout,
            data=table_data,
            font_name=font_name,
            font_size=font_size,
        )


class RendererFactory:
    """渲染器工厂类"""

    @staticmethod
    def get_renderer(
        layout_type: str, ppt_operations: PPTOperations
    ) -> BaseSlideRenderer:
        """
        根据版式类型获取对应的渲染器

        Args:
            layout_type: 版式类型
            ppt_operations: PPT操作对象

        Returns:
            BaseSlideRenderer: 对应的渲染器实例
        """
        logger.info(f"Initializing renderer for layout: {layout_type}")

        renderer_mapping = {
            "single_column_bar": SingleColumnBarRenderer,
            "single_column_line": SingleColumnLineRenderer,
            "double_column_bar": DoubleColumnBarRenderer,
            "double_column_line": DoubleColumnLineRenderer,
            "single_column_table": SingleColumnTableRenderer,
        }

        renderer_class = renderer_mapping.get(layout_type, BaseSlideRenderer)
        return renderer_class(ppt_operations)

    @staticmethod
    def get_supported_layout_types() -> list[str]:
        """获取所有支持的版式类型"""
        return [
            "single_column_bar",
            "single_column_line",
            "double_column_bar",
            "double_column_line",
            "single_column_table",
        ]
