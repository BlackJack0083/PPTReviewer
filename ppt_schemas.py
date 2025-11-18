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
    BLACK = "黑色"
    WHITE = "白色"
    RED = "红色"
    GREEN = "绿色"
    BLUE = "蓝色"
    YELLOW = "黄色"
    GRAY = "灰色"

    @property
    def rgb(self) -> RGBColor:
        """转换为 RGBColor 对象"""
        mapping = {
            self.BLACK: RGBColor(0, 0, 0),
            self.WHITE: RGBColor(255, 255, 255),
            self.RED: RGBColor(255, 0, 0),
            self.GREEN: RGBColor(0, 128, 0),  # 使用深绿色
            self.BLUE: RGBColor(0, 0, 255),
            self.YELLOW: RGBColor(255, 255, 0),
            self.GRAY: RGBColor(128, 128, 128),
        }
        return mapping[self]


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
    height: float | None = Field(..., description="高度 (cm)")
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


class ChartConfigModel(BaseModel):
    """图表配置模型

    Args:
        style_name (str): 配色风格名，如 2_orange_green
        font_size (int): 图表字体大小
        has_legend (bool): 是否显示图例
        has_data_labels (bool): 是否显示数值标签
        y_axis_visible (bool): Y轴是否可见
        value_axis_max (float | None): Y轴最大刻度
    """

    style_name: str = Field("", description="配色风格名，如 2_orange_green")
    font_size: int = Field(10, description="图表字体大小")
    has_legend: bool = Field(True, description="是否显示图例")
    has_data_labels: bool = Field(True, description="是否显示数值标签")
    y_axis_visible: bool = Field(True, description="Y轴是否可见")
    value_axis_max: float | None = Field(None, description="Y轴最大刻度")


class RectangleStyleModel(BaseModel):
    """矩形样式模型

    Args:
        fore_color (str): 填充色
        line_width (float): 边框宽度
        rotation (float): 旋转角度
        is_background (bool): 是否作为背景
    """

    fore_color: str = Field("gray", description="填充色")
    line_width: float = Field(0, description="边框宽度")
    rotation: float = Field(0, description="旋转角度")
    is_background: bool = Field(False, description="是否作为背景")
