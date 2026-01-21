# ppt_schemas.py
from enum import StrEnum
from typing import Any, Literal

import pandas as pd
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pydantic import BaseModel, ConfigDict, Field


class QueryFilter(BaseModel):
    """
    查询过滤条件对象
    """

    city: str
    block: str
    start_date: str
    end_date: str
    table_name: str

    @property
    def sql_params(self) -> dict:
        """转换为 SQL 参数"""
        return {
            "city": self.city,
            "block": self.block,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "table_name": self.table_name,
        }


class Align(StrEnum):
    LEFT = "左对齐"
    CENTER = "居中"
    RIGHT = "右对齐"

    @property
    def pptx_val(self) -> PP_ALIGN:
        """转换为 python-pptx 的枚举值"""
        mapping = {
            self.LEFT: PP_ALIGN.LEFT,
            self.CENTER: PP_ALIGN.CENTER,
            self.RIGHT: PP_ALIGN.RIGHT,
        }
        return mapping[self]


class Color(StrEnum):
    """统一颜色枚举，包含常用颜色定义"""

    BLACK = "黑色"
    WHITE = "白色"
    RED = "红色"
    GREEN = "绿色"
    BLUE = "蓝色"
    YELLOW = "黄色"
    GRAY = "灰色"
    LIGHT_BLUE = "浅蓝"
    DARK_BLUE = "深蓝"
    ORANGE = "橙色"

    @property
    def rgb(self) -> RGBColor:
        mapping = {
            self.BLACK: RGBColor(0, 0, 0),
            self.WHITE: RGBColor(255, 255, 255),
            self.RED: RGBColor(192, 0, 0),
            self.GREEN: RGBColor(0, 176, 80),
            self.BLUE: RGBColor(0, 0, 255),
            self.YELLOW: RGBColor(255, 255, 0),
            self.GRAY: RGBColor(128, 128, 128),
            self.LIGHT_BLUE: RGBColor(212, 228, 255),
            self.DARK_BLUE: RGBColor(0, 30, 80),
            self.ORANGE: RGBColor(255, 192, 0),
        }
        # 默认返回黑色防止KeyError
        return mapping.get(self, RGBColor(0, 0, 0))


class LayoutType(StrEnum):
    """版式类型枚举"""

    SINGLE_COLUMN_BAR = "single_column_bar"
    SINGLE_COLUMN_LINE = "single_column_line"
    DOUBLE_COLUMN_BAR = "double_column_bar"
    DOUBLE_COLUMN_LINE = "double_column_line"
    SINGLE_COLUMN_TABLE = "single_column_table"


class LayoutModel(BaseModel):
    """General layout model for positioning elements on a slide.

    Args:
        left (float): 左边距 (cm)
        top (float): 上边距 (cm)
        width (float): 宽度 (cm)
        height (float): 高度 (cm)
        alignment (Align): 对齐方式
    """

    model_config = ConfigDict(validate_by_name=True)

    left: float = Field(..., alias="x", description="左边距 (cm)")
    top: float = Field(..., alias="y", description="上边距 (cm)")
    width: float = Field(..., description="宽度 (cm)")
    height: float | None = Field(None, description="高度 (cm)")
    alignment: Align | None = Field(Align.LEFT, description="对齐方式")  # 文本对齐方式


class SlotDefinition(LayoutModel):
    """槽位定义，继承了坐标信息"""

    name: str
    type: str
    role: str


class LayoutConfig(BaseModel):
    slots: list[SlotDefinition]


class GlobalLayoutConfig(BaseModel):
    common: dict[str, LayoutModel]  # 通用元素也直接用 LayoutModel
    layouts: dict[str, LayoutConfig]


class TextStyleDefinition(BaseModel):
    """
    纯样式定义 (不包含具体文本内容)
    用于 styles.yaml 加载配置
    """

    font_size: int = Field(18, description="字号")
    font_bold: bool = Field(True, description="是否加粗")
    font_name: str = Field("方正兰亭黑_GBK", description="字体名称")
    font_color: Color = Field(Color.BLACK, description="字体颜色")
    word_wrap: bool = Field(True, description="是否自动换行")


class TextContentModel(TextStyleDefinition):
    """
    文本内容模型 = 样式 + 文本
    继承自 TextStyleDefinition，自动拥有 font_size 等字段
    """

    text: str = Field(..., description="文本内容")


class BaseChartConfig(BaseModel):
    """Level 1: 所有图表的绝对基类 (仅包含通用的视觉元素)"""

    style_name: str = Field("", description="配色风格名")
    font_name: str = Field("Arial", description="图表字体")
    font_size: int = Field(10, description="图表字体大小")
    has_legend: bool = Field(True, description="是否显示图例")
    has_data_labels: bool = Field(True, description="是否显示数值标签")
    title: str | None = Field(None, description="图表标题，None则不显示")


class AxisChartConfig(BaseChartConfig):
    """Level 2: 带有坐标轴的图表基类 (柱状图, 折线图, 散点图, 面积图)"""

    y_axis_visible: bool = Field(True, description="Y轴是否可见")
    value_axis_max: float | None = Field(None, description="Y轴最大刻度")
    x_axis_visible: bool = Field(True, description="X轴是否可见")
    value_axis_format: str | None = Field(None, description="数值轴格式")


class BarChartConfig(AxisChartConfig):
    """Level 3: 柱状图专用配置"""

    gap_width: int = Field(150, description="柱间隙宽度 (0-500)")
    overlap: int = Field(0, description="重叠比例 (-100 到 100)")
    grouping: str = Field("clustered", description="clustered(簇状) or stacked(堆积)")


class LineChartConfig(AxisChartConfig):
    """Level 3: 折线图专用配置"""

    has_markers: bool = Field(True, description="折线图: 是否显示数据标记点")
    smooth_line: bool = Field(False, description="折线图: 是否使用平滑曲线")
    line_width: float = Field(2.25, description="线宽")


class PieChartConfig(BaseChartConfig):
    """Level 3: 饼图专用配置 (直接继承 Base，没有坐标轴)"""

    # 饼图特有属性示例
    first_slice_angle: int = Field(0, description="第一扇区起始角度 (0-360)")
    hole_size: int = Field(0, description="圆环图孔径大小 (0-90), 0为实心饼图")


class RectangleStyleModel(BaseModel):
    """矩形样式模型

    Args:
        fore_color (Color): 填充色
        line_color (Color): 边框色
        line_width (float): 边框宽度
        rotation (float): 旋转角度
        is_background (bool): 是否作为背景
    """

    fore_color: Color = Field(Color.GRAY, description="填充色")  # 引用 Color 枚举
    line_color: Color = Field(Color.GRAY, description="边框色")
    line_width: float = Field(0, description="边框宽度")
    rotation: float = Field(0, description="旋转角度")
    is_background: bool = Field(False, description="是否作为背景")


class ElementType(StrEnum):
    TEXT = "textBox"
    CHART = "chart"
    TABLE = "table"
    RECTANGLE = "rectangle"
    PICTURE = "picture"


class BaseSlideElement(BaseModel):
    """所有幻灯片元素的基类"""

    role: str
    layout: LayoutModel

    # 允许 Pydantic 接受 pandas DataFrame 这种非标准 JSON 类型
    model_config = ConfigDict(arbitrary_types_allowed=True)


class TextElement(BaseSlideElement):
    """文本元素模型"""

    type: Literal[ElementType.TEXT] = ElementType.TEXT
    text: str


class DataElement(BaseSlideElement):
    """数据驱动元素 (图表/表格) 模型"""

    # 这里定义 data_key 必须存在，防止你在 Builder 里拼错
    data_key: str
    # 强制要求 payload 是 DataFrame，而不是随便什么 list 或 dict
    data_payload: pd.DataFrame


class ChartElement(DataElement):
    type: Literal[ElementType.CHART] = ElementType.CHART


class TableElement(DataElement):
    type: Literal[ElementType.TABLE] = ElementType.TABLE


class RectangleElement(BaseSlideElement):
    type: Literal[ElementType.RECTANGLE] = ElementType.RECTANGLE
    # 可以添加 specific 属性，如 color, border 等


class PictureElement(BaseSlideElement):
    type: Literal[ElementType.PICTURE] = ElementType.PICTURE
    image_path: str


RenderableElement = (
    TextElement | ChartElement | TableElement | RectangleElement | PictureElement
)


class SlideRenderConfig(BaseModel):
    """单页幻灯片的完整渲染配置"""

    layout_type: LayoutType
    style_id: str
    elements: list[RenderableElement]


class BinningRule(BaseModel):
    """
    定义分箱/维度规则
    """

    source_col: str = Field(..., description="原始数据列名，如 dim_area")
    target_col: str = Field(..., description="目标列名，如 area_range")
    method: Literal["range", "period"] = Field(
        ..., description="分箱方式：数值区间(range)或时间周期(period)"
    )

    # Optional fields
    step: float | int | None = Field(None, description="分箱步长，如 20")
    format_str: str | None = Field(None, description="格式化模板，如 '{}-{}m²'")
    time_granularity: Literal["year", "month"] | None = Field(
        None, description="时间粒度"
    )


class MetricRule(BaseModel):
    """
    定义指标计算规则
    """

    name: str = Field(..., description="指标显示名称，也是结果列名")
    source_col: str = Field(..., description="数据源数值列，如 supply_sets")
    agg_func: Literal["sum", "count", "mean", "max", "min"] = Field(
        "sum", description="聚合函数"
    )

    # 使用 Dict[str, Any] 允许传入如 {"supply_sets": 1} 的过滤条件
    filter_condition: dict[str, Any] | None = Field(None, description="前置过滤条件")


class TableAnalysisConfig(BaseModel):
    """
    总体的表格分析配置
    """

    table_type: Literal["field-constraint", "constraint-filed", "cross-constraint"] = (
        Field(..., description="表格类型")
    )

    # 使用 default_factory=list 防止可变默认参数问题
    dimensions: list[BinningRule] = Field(
        default_factory=list, description="X轴/行维度列表"
    )
    metrics: list[MetricRule] = Field(
        default_factory=list, description="Y轴/数值指标列表"
    )

    # 交叉表专用配置
    crosstab_row: str | None = Field(None, description="交叉表-行维度字段名")
    crosstab_col: str | None = Field(None, description="交叉表-列维度字段名")

    model_config = {"extra": "ignore"}  # 如果传入了多余的参数，自动忽略而不是报错
