from typing import Any

from loguru import logger

from data_provider import DataProvider
from ppt_operations import PPTOperations
from ppt_schemas import (
    Align,
    BarChartConfig,
    Color,
    LayoutModel,
    LineChartConfig,
    TextContentModel,
)


class BaseSlideRenderer:
    """所有版式渲染器的基类"""

    def __init__(self, ppt_ops: PPTOperations):
        self.ppt = ppt_ops

    def render(self, slide_config: dict[str, Any], page_num: int):
        """主渲染入口"""
        # 1. 遍历元素并分发处理
        elements = slide_config.get("elements", [])
        for el in elements:
            self._render_element(page_num, el)

    def _render_element(self, page_num: int, element: dict[str, Any]):
        """根据元素类型分发"""
        el_type = element.get("type")

        if el_type == "textBox":
            self._render_text(page_num, element)
        elif el_type == "chart":
            self._render_chart(page_num, element)
        elif el_type == "table":
            self._render_table(page_num, element)
        else:
            logger.warning(f"Unknown element type: {el_type}")

    def _map_layout(self, yaml_layout: dict) -> LayoutModel:
        return LayoutModel(
            left=yaml_layout.get("x", 0),
            top=yaml_layout.get("y", 0),
            width=yaml_layout.get("width", 0),
            height=yaml_layout.get("height", 0),
            alignment=Align.LEFT,
        )

    def _render_text(self, page_num: int, element: dict):
        role = element.get("role", "")
        text = element.get("text", "")
        layout = self._map_layout(element.get("layout", {}))

        # 默认样式策略
        font_size = 14
        font_color = Color.BLACK
        font_bold = False

        if role == "slide-title":
            font_size = 24
            font_bold = True
            layout.alignment = Align.LEFT
        elif role == "body-text":
            font_size = 14
            font_color = Color.DARK_BLUE
        elif role == "caption":
            font_size = 10
            font_color = Color.GRAY
            layout.alignment = Align.CENTER

        content = TextContentModel(
            text=str(text),
            font_size=font_size,
            font_bold=font_bold,
            font_color=font_color,
        )
        self.ppt.add_text_box(page_num, content, layout)

    def _render_chart(self, page_num: int, element: dict):
        """基类默认图表处理"""
        # 如果没有匹配到特定渲染器，使用一个通用的兜底逻辑
        role = str(element.get("role", ""))
        layout = self._map_layout(element.get("layout", {}))
        df = DataProvider.get_data(role, element.get("args", []))

        if "bar" in role.lower():
            config = BarChartConfig(style_name="default", font_size=10)
            self.ppt.add_bar_chart(page_num, df, layout, config)
        elif "line" in role.lower():
            config = LineChartConfig(style_name="default", font_size=10)
            self.ppt.add_line_chart(page_num, df, layout, config)

    def _render_table(self, page_num: int, element: dict):
        """基类默认表格处理"""
        role = str(element.get("role", ""))
        layout = self._map_layout(element.get("layout", {}))
        df = DataProvider.get_data(role, element.get("args", []))

        # 默认表格样式
        font_name = "微软雅黑"
        font_size = 9

        self.ppt.add_table(
            page_num=page_num,
            layout=layout,
            data=df,
            font_name=font_name,
            font_size=font_size,
        )


class SingleColumnBarRenderer(BaseSlideRenderer):
    """版式 1: 单栏柱状图"""

    def _render_chart(self, page_num: int, element: dict):
        layout = self._map_layout(element.get("layout", {}))
        role = str(element.get("role", ""))
        df = DataProvider.get_data(role, element.get("args", []))

        chart_config = BarChartConfig(
            style_name="supply_trade",
            font_size=11,
            has_legend=True,
            has_data_labels=True,
            gap_width=150,
            y_axis_visible=False,  # 单栏大图通常隐藏Y轴
        )
        self.ppt.add_bar_chart(page_num, df, layout, chart_config)


class SingleColumnLineRenderer(BaseSlideRenderer):
    """版式 2: 单栏折线图"""

    def _render_chart(self, page_num: int, element: dict):
        layout = self._map_layout(element.get("layout", {}))
        role = str(element.get("role", ""))
        df = DataProvider.get_data(role, element.get("args", []))

        config = LineChartConfig(
            style_name="growth_trend",
            font_size=11,
            has_markers=True,
            smooth_line=True,
            has_data_labels=True,
            y_axis_visible=True,
        )
        self.ppt.add_line_chart(page_num, df, layout, config)


class DoubleColumnLineRenderer(BaseSlideRenderer):
    """版式 4: 双栏折线图 (针对左右两张折线图的布局优化)"""

    def _render_chart(self, page_num: int, element: dict):
        layout = self._map_layout(element.get("layout", {}))
        role = str(element.get("role", ""))
        df = DataProvider.get_data(role, element.get("args", []))

        # 双栏图通常较小，调整字体和标签策略
        config = LineChartConfig(
            style_name="business_blue",  # 使用商务蓝风格
            font_size=9,  # 字号稍小
            has_markers=True,
            smooth_line=False,  # 双栏较窄，平滑曲线可能产生误导，建议直线
            has_data_labels=False,  # 空间有限，可能关闭数值标签或仅显示关键点
            y_axis_visible=True,  # 必须显示Y轴，因为没有数值标签
        )
        self.ppt.add_line_chart(page_num, df, layout, config)


class DoubleColumnBarRenderer(BaseSlideRenderer):
    """版式 3: 双栏柱状图"""

    def _render_chart(self, page_num: int, element: dict):
        layout = self._map_layout(element.get("layout", {}))
        role = str(element.get("role", ""))
        df = DataProvider.get_data(role, element.get("args", []))

        config = BarChartConfig(
            style_name="business_blue",
            font_size=9,
            gap_width=100,  # 柱子紧凑一点
            has_data_labels=True,  # 柱状图还是尽量显示标签
            y_axis_visible=False,
        )
        self.ppt.add_bar_chart(page_num, df, layout, config)


class SingleColumnTableRenderer(BaseSlideRenderer):
    """版式 5: 单栏表格"""

    def _render_table(self, page_num: int, element: dict):
        layout = self._map_layout(element.get("layout", {}))
        role = str(element.get("role", ""))
        df = DataProvider.get_data(role, element.get("args", []))

        # 单栏表格可以使用更大的字体和更宽松的布局
        font_name = "微软雅黑"
        font_size = 11

        self.ppt.add_table(
            page_num=page_num,
            layout=layout,
            data=df,
            font_name=font_name,
            font_size=font_size,
        )


# 工厂模式更新
class RendererFactory:
    @staticmethod
    def get_renderer(layout_type: str, ppt_ops: PPTOperations) -> BaseSlideRenderer:
        logger.info(f"Initializing renderer for layout: {layout_type}")

        if layout_type == "single_column_bar":
            return SingleColumnBarRenderer(ppt_ops)
        elif layout_type == "single_column_line":
            return SingleColumnLineRenderer(ppt_ops)
        elif layout_type == "double_column_line":
            return DoubleColumnLineRenderer(ppt_ops)
        elif layout_type == "double_column_bar":
            return DoubleColumnBarRenderer(ppt_ops)
        elif layout_type == "single_column_table":
            return SingleColumnTableRenderer(ppt_ops)
        # 混合布局可以使用基类，或者专门定义 MixRenderer
        else:
            return BaseSlideRenderer(ppt_ops)
