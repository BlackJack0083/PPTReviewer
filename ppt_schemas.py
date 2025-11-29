# ppt_schemas.py
from enum import StrEnum

from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pydantic import BaseModel, Field


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


class LayoutModel(BaseModel):
    """General layout model for positioning elements on a slide.

    Args:
        left (float): 左边距 (cm)
        top (float): 上边距 (cm)
        width (float): 宽度 (cm)
        height (float): 高度 (cm)
        alignment (Align): 对齐方式
    """

    left: float = Field(..., description="左边距 (cm)")
    top: float = Field(..., description="上边距 (cm)")
    width: float = Field(..., description="宽度 (cm)")
    height: float | None = Field(None, description="高度 (cm)")
    alignment: Align | None = Field(Align.LEFT, description="对齐方式")  # 文本对齐方式


class TextContentModel(BaseModel):
    """文本内容模型

    Args:
        text (str): 文本内容
        font_size (int): 字号
        font_bold (bool): 是否加粗
        font_name (str): 字体名称
        font_color (str): 字体颜色
        word_wrap (bool): 是否自动换行
    """

    text: str = Field(..., description="文本内容")
    font_size: int = Field(18, description="字号")
    font_bold: bool = Field(True, description="是否加粗")
    font_name: str = Field("方正兰亭黑_GBK", description="字体名称")
    font_color: Color = Field(Color.BLACK, description="字体颜色")
    word_wrap: bool = Field(True, description="是否自动换行")


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
        fore_color (str): 填充色
        line_color (str): 边框色
        line_width (float): 边框宽度
        rotation (float): 旋转角度
        is_background (bool): 是否作为背景
    """

    fore_color: Color = Field(Color.GRAY, description="填充色")  # 引用 Color 枚举
    line_color: Color = Field(Color.GRAY, description="边框色")
    line_width: float = Field(0, description="边框宽度")
    rotation: float = Field(0, description="旋转角度")
    is_background: bool = Field(False, description="是否作为背景")
