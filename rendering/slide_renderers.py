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
from template_system.catalog import LayoutType


class StyleConfigManager:
    """样式配置管理器"""

    @staticmethod
    def get_bar_chart_config(layout_type: LayoutType) -> BarChartConfig:
        """根据版式类型返回对应的柱状图配置"""
        # 默认基础配置
        base_config = {
            "font_name": "Arial",
            "has_legend": True,
            "has_data_labels": True,
            "title": None,
            "grouping": "clustered",
            "overlap": 0,
        }

        if layout_type == LayoutType.SINGLE_COLUMN_BAR:
            return BarChartConfig(
                style_name="supply_trade",
                font_size=11,
                y_axis_visible=False,
                gap_width=150,
                **base_config,
            )
        elif layout_type == LayoutType.DOUBLE_COLUMN_BAR:
            return BarChartConfig(
                style_name="business_blue",
                font_size=12,
                y_axis_visible=False,
                gap_width=100,
                **base_config,
            )
        # 默认回退配置
        return BarChartConfig(
            style_name="default",
            font_size=11,
            y_axis_visible=True,
            gap_width=150,
            **base_config,
        )

    @staticmethod
    def get_line_chart_config(layout_type: LayoutType) -> LineChartConfig:
        """根据版式类型返回对应的折线图配置"""
        base_config = {
            "font_name": "Arial",
            "has_legend": True,
            "has_data_labels": True,
            "title": None,
            "y_axis_visible": True,
            "has_markers": True,
        }

        if layout_type == LayoutType.SINGLE_COLUMN_LINE:
            return LineChartConfig(
                style_name="growth_trend",
                font_size=11,
                smooth_line=True,
                line_width=2.25,
                **base_config,
            )
        elif layout_type == LayoutType.DOUBLE_COLUMN_LINE:
            return LineChartConfig(
                style_name="business_blue",
                font_size=12,
                smooth_line=False,
                line_width=2.0,
                **base_config,
            )
        return LineChartConfig(
            style_name="default",
            font_size=11,
            smooth_line=True,
            line_width=2.25,
            **base_config,
        )


class BaseSlideRenderer:
    """所有版式渲染器的基类

    职责：
    1. 提供统一的渲染接口和元素分发逻辑
    2. 定义通用的文本、图表、表格渲染方法
    3. 管理PPT操作对象的引用
    4. 解耦数据获取逻辑，专注于渲染逻辑
    """

    def __init__(self, ppt_operations: PPTOperations, layout_type: LayoutType):
        """
        初始化渲染器

        Args:
            ppt_operations: PPT操作对象
            layout_type: 版式类型
        """
        self.ppt_operations = ppt_operations
        self.layout_type = layout_type

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
        根据元素类型分发到具体的渲染方法，使用字典分发

        Args:
            page_number: 幻灯片页码
            element: 元素配置字典
        """
        render_methods = {
            "textBox": self._render_text_box,
            "chart": self._render_chart,
            "table": self._render_table,
            "rectangle": self._render_rectangle,
            "picture": self._render_picture,
        }

        element_type = element.get("type")
        handler = render_methods.get(element_type)

        if handler:
            handler(page_number, element)
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

    # --- 辅助方法：统一数据校验 ---
    def _validate_and_get_data(
        self, element: dict[str, Any], role: str
    ) -> pd.DataFrame | None:
        """统一的数据获取与校验逻辑"""
        data = element.get("data_payload")
        if data is None:
            logger.warning(f"No data provided for element: {role}")
            return None
        if not isinstance(data, pd.DataFrame):
            logger.error(f"Data must be a DataFrame, got {type(data)} for {role}")
            return None
        return data

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
    ) -> tuple[int, bool, Color]:  # noqa: SIM11
        """
        根据角色获取文本样式

        Args:
            role: 元素角色

        Returns:
            tuple: (字体大小, 是否加粗, 字体颜色)
        """

        role_styles = {
            "slide-title": (24, True, Color.BLACK),
            "body-text": (14, False, Color.DARK_BLUE),
            "caption": (10, False, Color.GRAY),
        }

        return role_styles.get(role, (12, False, Color.BLACK))

    def _render_chart(self, page_number: int, element: dict[str, Any]) -> None:
        """
        渲染图表（基类默认实现）

        Args:
            page_number: 幻灯片页码
            element: 图表元素配置
        """
        chart_role = element.get("role", "")
        layout = self._map_layout(element.get("layout", {}))

        # 获取并校验数据
        chart_data = self._validate_and_get_data(element, chart_role)
        if chart_data is None:
            return

        # 2. 根据 layout_type 或 role 路由到具体的图表类型
        if "bar" in chart_role.lower():
            config = StyleConfigManager.get_bar_chart_config(self.layout_type)
            self.ppt_operations.add_bar_chart(page_number, chart_data, layout, config)
        elif "line" in chart_role.lower():
            config = StyleConfigManager.get_line_chart_config(self.layout_type)
            self.ppt_operations.add_line_chart(page_number, chart_data, layout, config)
        else:
            logger.warning(f"Unknown chart role: {chart_role}")

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
        table_data = self._validate_and_get_data(element, table_role)
        if table_data is None:
            return

        # 默认表格样式
        font_name = "微软雅黑"
        # 根据版式决定字体大小（如果需要在不同版式下有不同表格样式，也可以移入 ConfigManager）
        font_size = 12 if self.layout_type == LayoutType.DOUBLE_COLUMN_LINE else 11

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


class RendererFactory:
    """渲染器工厂类"""

    @staticmethod
    def get_renderer(
        layout_type: LayoutType, ppt_operations: PPTOperations
    ) -> BaseSlideRenderer:
        """
        现在的工厂不再需要返回不同的子类，
        而是返回同一个类，但注入了不同的 layout_type 上下文。
        """
        logger.info(f"Initializing renderer for layout: {layout_type}")
        return BaseSlideRenderer(ppt_operations, layout_type)

    @staticmethod
    def get_supported_layout_types() -> list[str]:
        return [t.value for t in LayoutType]
