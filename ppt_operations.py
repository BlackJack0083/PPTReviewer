"""
PPT操作API模块
使用python-pptx包实现基本的PPT操作功能
"""

import os

import pandas as pd
import pptx_ea_font
from loguru import logger
from pptx import Presentation
from pptx.chart.data import ChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_DATA_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Cm, Pt

# 引入 Pydantic 模型
from ppt_schemas import (
    ChartConfigModel,
    LayoutModel,
    RectangleStyleModel,
    TextContentModel,
)


class PPTOperations:
    """PPT操作类，封装基本的PPT创建和编辑功能"""

    COLORS_COLLECTION = {
        "2_orange_green": [RGBColor(255, 192, 0), RGBColor(0, 176, 80)],
        "2_green_orange": [RGBColor(0, 176, 80), RGBColor(255, 192, 0)],
        "2_orange_olive": [RGBColor(255, 192, 0), RGBColor(0, 176, 180)],
        "2_olive_green": [RGBColor(0, 176, 180), RGBColor(0, 176, 80)],
        "2_white_olive": [RGBColor(255, 255, 255), RGBColor(0, 176, 180)],
        "2_blue_lightblue": [RGBColor(0, 176, 240), RGBColor(169, 227, 255)],
        "2_olive_orange": [RGBColor(0, 176, 180), RGBColor(255, 192, 0)],
        "2_gray_lightblue2": [RGBColor(182, 191, 197), RGBColor(169, 227, 255)],
        "1_olive": [RGBColor(0, 176, 180)],
        "1_orange": [RGBColor(255, 192, 0)],
        "1_gray": [RGBColor(182, 191, 197)],
        "1_lightblue": [RGBColor(0, 176, 240)],
        "1_tangerine": [RGBColor(255, 102, 153)],
        "2_tangerine_gray": [RGBColor(255, 102, 153), RGBColor(182, 191, 197)],
        "2_gray_tangerine": [RGBColor(182, 191, 197), RGBColor(255, 102, 153)],
        "2_gray_lightblue": [RGBColor(182, 191, 197), RGBColor(0, 176, 240)],
        "2_green_gray": [RGBColor(0, 176, 80), RGBColor(182, 191, 197)],
        "2_olive_gray": [RGBColor(0, 176, 180), RGBColor(182, 191, 197)],
    }

    def __init__(self):
        self.presentation = None
        self.ppt_path = None

    def _load_presentation(self, ppt_script: str) -> None:
        """加载现有的PPT文件"""
        if self.ppt_path != ppt_script or self.presentation is None:
            try:
                self.presentation = Presentation(ppt_script)
                self.ppt_path = ppt_script
                logger.info(f"成功加载 PPT: {ppt_script}")
            except Exception as e:
                logger.error(f"加载 PPT 失败: {e}")
                raise

    def _get_slide(self, ppt_script: str, page_num: int):
        """获取指定页码的幻灯片"""
        self._load_presentation(ppt_script)
        try:
            # page_num 是从1开始，索引是从0开始
            return self.presentation.slides[page_num - 1]
        except IndexError as e:
            logger.error(
                f"页码 {page_num} 超出范围 (总页数: {len(self.presentation.slides)})"
            )
            raise ValueError(
                f"页码 {page_num} 不存在，总页数为 {len(self.presentation.slides)}"
            ) from e

    def get_slide_count(self, ppt_script: str) -> int:
        """获取PPT页数 (对应原 ppt_slide_number)"""
        self._load_presentation(ppt_script)
        return len(self.presentation.slides)

    def create_slide(
        self,
        ppt_name: str,
        page_num: int,
        slide_width: float,
        slide_height: float,
        ppt_script: str,
    ) -> None:
        """
        创建新的PPT文件

        Args:
            ppt_name (str): PPT文件名
            page_num (int): 页数
            slide_width (float): 幻灯片宽度（厘米）
            slide_height (float): 幻灯片高度（厘米）
            ppt_script (str): PPT保存路径
        """
        # 创建新的演示文稿
        self.presentation = Presentation()

        # 设置幻灯片大小
        self.presentation.slide_width = Cm(slide_width)
        self.presentation.slide_height = Cm(slide_height)

        # 创建指定数量的空白幻灯片
        for _ in range(page_num):
            # 使用空白布局
            blank_slide_layout = self.presentation.slide_layouts[6]  # 空白布局
            self.presentation.slides.add_slide(blank_slide_layout)

        # 保存文件
        self.ppt_path = ppt_script
        os.makedirs(os.path.dirname(ppt_script), exist_ok=True)
        self.presentation.save(ppt_script)
        logger.info(f"成功创建PPT文件: {ppt_script}")

    def add_title(
        self,
        ppt_script: str,
        page_num: int,
        content: TextContentModel,
        layout: LayoutModel,
    ) -> None:
        """
        添加标题文本框

        Args:
            ppt_script (str): PPT文件路径
            page_num (int): 幻灯片页码（从1开始）
            content (TextContentModel): 文本内容配置
            layout (LayoutModel): 布局配置
        """
        slide = self._get_slide(ppt_script, page_num)

        # 1. 使用 layout 对象的数据
        text_box = slide.shapes.add_textbox(
            Cm(layout.left), Cm(layout.top), Cm(layout.width), Cm(layout.height)
        )
        text_frame = text_box.text_frame
        text_frame.text = content.text  # 直接访问属性

        text_frame.word_wrap = content.word_wrap

        # 2. 设置样式
        for paragraph in text_frame.paragraphs:
            # 调用我们在 Model 里写好的辅助属性，直接拿到枚举值
            paragraph.alignment = layout.alignment.pptx_val

            for run in paragraph.runs:
                run.font.size = Pt(content.font_size)
                run.font.bold = content.font_bold
                run.font.color.rgb = content.font_color.rgb  # 使用 Enum 属性
                pptx_ea_font.set_font(run, content.font_name)

        # 保存文件
        self.presentation.save(ppt_script)
        logger.info(f"成功在第{page_num}页添加标题")

    def add_content(
        self,
        ppt_script: str,
        page_num: int,
        content: TextContentModel,
        layout: LayoutModel,
    ) -> None:
        """
        添加内容文本框

        Args:
            ppt_script (str): PPT文件路径
            page_num (int): 幻灯片页码（从1开始）
            content (TextContentModel): 文本内容配置
            layout (LayoutModel): 布局配置
        """
        # 获取指定页面
        if page_num > len(self.presentation.slides) or page_num < 1:
            raise ValueError(f"页码 {page_num} 超出范围")

        slide = self.presentation.slides[page_num - 1]

        # 1. 使用 layout 对象的数据
        text_box = slide.shapes.add_textbox(
            Cm(layout.left), Cm(layout.top), Cm(layout.width), Cm(layout.height)
        )
        text_frame = text_box.text_frame
        text_frame.text = content.text  # 直接访问属性
        text_frame.word_wrap = content.word_wrap

        # 2. 设置样式
        for paragraph in text_frame.paragraphs:
            # 调用我们在 Model 里写好的辅助属性，直接拿到枚举值
            paragraph.alignment = layout.alignment.pptx_val

            for run in paragraph.runs:
                run.font.size = Pt(content.font_size)
                run.font.bold = content.font_bold
                run.font.color.rgb = content.font_color.rgb
                pptx_ea_font.set_font(run, content.font_name)

        # 保存文件
        self.presentation.save(ppt_script)
        logger.info(f"成功在第{page_num}页添加内容: {content.text}")

    def add_table(
        self,
        ppt_script: str,
        page_num: int,
        layout: LayoutModel,
        data: pd.DataFrame,
        font_name: str = "方正兰亭黑_GBK",
        fontsize: int = 6,
    ) -> None:
        """
        添加表格

        Args:
            ppt_script (str): PPT文件路径
            page_num (int): 幻灯片页码（从1开始）
            layout (LayoutModel): 布局配置
            data (pd.DataFrame): 表格数据
            fontname (str): 字体名称，默认'方正兰亭黑_GBK'
            fontsize (int): 字体大小，默认6
        """
        slide = self._get_slide(ppt_script, page_num)

        rows, cols = data.shape
        table_shape = slide.shapes.add_table(
            rows + 1,
            cols,
            Cm(layout.left),
            Cm(layout.top),
            Cm(layout.width),
            Cm(layout.height),
        )
        table = table_shape.table

        # 设置标题行
        for col_idx, col_name in enumerate(data.columns):
            cell = table.cell(0, col_idx)
            cell.text = str(col_name)
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    pptx_ea_font.set_font(run, font_name)
                    run.font.size = Pt(fontsize)
                    run.font.bold = True

        # 设置数据行
        for row_idx in range(rows):
            for col_idx in range(cols):
                cell = table.cell(row_idx + 1, col_idx)
                cell.text = str(data.iloc[row_idx, col_idx])
                for paragraph in cell.text_frame.paragraphs:
                    for run in paragraph.runs:
                        # run.font.name = font_name
                        pptx_ea_font.set_font(run, font_name)
                        run.font.size = Pt(fontsize)
                        run.font.bold = False

        # 保存文件
        self.presentation.save(ppt_script)
        logger.info(f"成功在第{page_num}页添加表格")

    def add_rectangle(
        self,
        ppt_script: str,
        page_num: int,
        layout: LayoutModel,
        style: RectangleStyleModel | None = None,
    ) -> None:
        """添加矩形色块"""
        slide = self._get_slide(ppt_script, page_num)

        # 添加形状
        shape = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Cm(layout.left),
            Cm(layout.top),
            Cm(layout.width),
            Cm(layout.height),
        )
        shape.rotation = style.rotation

        fill = shape.fill
        fill.solid()
        line = shape.line

        # 矩形颜色逻辑
        color_map = {
            "gray": RGBColor(242, 242, 242),
            "gray1": RGBColor(127, 127, 127),
            "blue": RGBColor(0, 30, 80),
            "red": RGBColor(192, 0, 0),
            "white": RGBColor(255, 255, 255),
            "lightblue": RGBColor(212, 228, 255),
        }
        rgb = color_map.get(style.fore_color, RGBColor(242, 242, 242))

        fill.fore_color.rgb = rgb
        line.color.rgb = rgb

        if style.is_background:
            shape.fill.background()

        line.width = Pt(style.line_width)

        self.presentation.save(ppt_script)
        logger.info(f"成功在第{page_num}页添加矩形")

    def add_picture(
        self, ppt_script: str, page_num: int, img_path: str, layout: LayoutModel
    ) -> None:
        """
        添加图片

        Args:
            img_path (str): 图片路径
            layout (LayoutModel): 布局配置
        """
        slide = self._get_slide(ppt_script, page_num)

        slide.shapes.add_picture(
            img_path, Cm(layout.left), Cm(layout.top), Cm(layout.width)
        )

        self.presentation.save(ppt_script)
        logger.info(f"成功在第{page_num}页添加图片")

    def add_chart(
        self,
        ppt_script: str,
        page_num: int,
        df: pd.DataFrame,
        layout: LayoutModel,
        config: ChartConfigModel | None = None,
    ) -> None:
        """
        添加柱状图

        Args:
            df (pd.DataFrame):
                - Index (索引) -> 变为图例 (系列)
                - Columns (列名) -> 变为 X 轴标签 (类别)
            layout (LayoutModel): Pydantic 布局模型
            config (ChartConfigModel): Pydantic 图表配置模型
        """
        slide = self._get_slide(ppt_script, page_num)

        # 1. 准备数据
        chart_data = ChartData()
        chart_data.categories = df.columns  # 列名作为 X 轴
        for i in range(df.shape[0]):
            chart_data.add_series(str(df.index[i]), df.iloc[i])  # 索引作为图例

        # 2. 添加图表 (使用 Pydantic layout 对象属性)
        x, y, w, h = (
            Cm(layout.left),
            Cm(layout.top),
            Cm(layout.width),
            Cm(layout.height),
        )

        graphic_frame = slide.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED, x, y, w, h, chart_data
        )
        chart = graphic_frame.chart

        # 3. 设置颜色
        if config.style_name in self.COLORS_COLLECTION:
            colors = self.COLORS_COLLECTION[config.style_name]
            for idx, series in enumerate(chart.series):
                if idx < len(colors):
                    fill = series.format.fill
                    fill.solid()
                    fill.fore_color.rgb = colors[idx]

        # 4. 基础样式设置
        chart.has_title = False

        # X轴 (类别轴)
        cat_axis = chart.category_axis
        cat_axis.tick_labels.font.size = Pt(config.font_size)
        # TODO: 为图表字体设置中文字体 (pptx_ea_font 不直接支持)
        # cat_axis.tick_labels.font.name = config.font_name

        # Y轴 (值轴)
        val_axis = chart.value_axis
        val_axis.visible = config.y_axis_visible

        # 检查是否设置了最大值 (不再是检查 dict key)
        if config.value_axis_max is not None:
            val_axis.maximum_scale = config.value_axis_max

        val_axis.tick_labels.font.size = Pt(config.font_size)
        # val_axis.tick_labels.font.name = config.font_name

        # 数据标签
        if config.has_data_labels:
            plot = chart.plots[0]
            plot.has_data_labels = True
            data_labels = plot.data_labels
            data_labels.font.size = Pt(config.font_size)
            # data_labels.font.name = config.font_name
            data_labels.position = XL_DATA_LABEL_POSITION.CENTER

        # 图例
        chart.has_legend = config.has_legend
        if chart.has_legend:
            chart.legend.position = XL_LEGEND_POSITION.TOP
            chart.legend.font.size = Pt(config.font_size)
            # chart.legend.font.name = config.font_name
            chart.legend.include_in_layout = False

        self.presentation.save(ppt_script)
        logger.info(f"成功在第{page_num}页添加图表")
