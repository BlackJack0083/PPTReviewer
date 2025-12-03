# ppt_operations.py - PPT操作核心类
import os
import re
from pathlib import Path
from typing import Self

import pandas as pd
import pptx_ea_font
from loguru import logger
from pptx import Presentation
from pptx.chart.data import ChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_DATA_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.slide import Slide
from pptx.util import Cm, Pt

# 引入 Pydantic 模型
from core.ppt_schemas import (
    BarChartConfig,
    BaseChartConfig,
    LayoutModel,
    LineChartConfig,
    RectangleStyleModel,
    TextContentModel,
)

CHART_THEMES = {
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


class PPTOperations:
    """
    PPT操作核心类

    提供统一的PPT文件操作接口，支持从模板创建或新建空白PPT。
    使用上下文管理器确保文件正确保存。

    Usage:
        with PPTOperations("output.pptx") as ppt_manager:
            ppt_manager.init_slides(5)
            ppt_manager.add_text_box(1, content_model, layout_model)
            # 退出时自动保存
    """

    # 常量定义
    DEFAULT_SLIDE_WIDTH_CM = 33.867  # 16:9 宽屏
    DEFAULT_SLIDE_HEIGHT_CM = 19.05  # 16:9 宽屏
    BLANK_LAYOUT_INDEX = 6  # 空白布局索引

    def __init__(
        self, output_file_path: str | Path, template_file_path: str | Path | None = None
    ):
        """
        初始化PPT操作类

        Args:
            output_file_path: PPT 保存的目标路径
            template_file_path: 模板路径，如果存在则基于模板加载，否则新建空白 PPT
        """
        self.output_file_path = str(output_file_path)
        self.presentation = None

        # 初始化加载逻辑
        if template_file_path and os.path.exists(template_file_path):
            logger.info(f"Loading template PPT: {template_file_path}")
            self.presentation = Presentation(template_file_path)
        elif os.path.exists(self.output_file_path):
            logger.info(f"Loading existing PPT: {self.output_file_path}")
            self.presentation = Presentation(self.output_file_path)
        else:
            logger.info("Creating new blank Presentation object")
            self.presentation = Presentation()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.save()
        else:
            logger.error(f"操作过程中发生异常，未保存: {exc_val}")

    def save(self, output_path: str | None = None) -> None:
        """保存 PPT 文件"""
        target_path = output_path or self.output_file_path
        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        try:
            self.presentation.save(target_path)
            logger.info(f"成功保存 PPT 至: {target_path}")
        except Exception as e:
            logger.error(f"保存 PPT 失败: {e}")
            raise

    def _get_slide(self, page_number: int) -> Slide:
        """
        获取指定页码的幻灯片

        Args:
            page_number (int): 页码，从 1 开始

        Returns:
            Slide: 指定页码的幻灯片对象

        Raises:
            IndexError: 页码超出范围时抛出异常
        """
        total_slides = len(self.presentation.slides)
        if not (1 <= page_number <= total_slides):
            raise IndexError(
                f"页码 {page_number} 超出范围 (当前总页数: {total_slides})"
            )
        return self.presentation.slides[page_number - 1]

    def init_slides(
        self,
        slide_count: int,
        slide_width_cm: float = None,  # 使用类常量作为默认值
        slide_height_cm: float = None,
    ) -> None:
        """
        初始化/重置幻灯片尺寸并创建空白页

        Args:
            slide_count (int): 目标总页数
            slide_width_cm (float): 幻灯片宽度（厘米），默认使用16:9宽屏
            slide_height_cm (float): 幻灯片高度（厘米），默认使用16:9宽屏
        """
        # 使用类常量作为默认值
        width_cm = (
            slide_width_cm
            if slide_width_cm is not None
            else self.DEFAULT_SLIDE_WIDTH_CM
        )
        height_cm = (
            slide_height_cm
            if slide_height_cm is not None
            else self.DEFAULT_SLIDE_HEIGHT_CM
        )

        # 设置幻灯片尺寸
        self.presentation.slide_width = Cm(width_cm)
        self.presentation.slide_height = Cm(height_cm)

        # 确保有足够的页面
        current_slide_count = len(self.presentation.slides)
        slides_needed = slide_count - current_slide_count

        blank_layout = self.presentation.slide_layouts[
            self.BLANK_LAYOUT_INDEX
        ]  # 空白布局

        for _ in range(slides_needed):
            self.presentation.slides.add_slide(blank_layout)

        logger.info(
            f"PPT 已调整为 {len(self.presentation.slides)} 页 (尺寸: {width_cm}x{height_cm}cm)"
        )

    def add_text_box(
        self, page_num: int, content: TextContentModel, layout: LayoutModel
    ) -> None:
        """
        通用文本框添加方法

        Args:
            page_num (int): 幻灯片页码（从1开始）
            content (TextContentModel): 文本内容配置
            layout (LayoutModel): 布局配置
        """
        slide = self._get_slide(page_num)
        shape = slide.shapes.add_textbox(
            Cm(layout.left), Cm(layout.top), Cm(layout.width), Cm(layout.height or 1.0)
        )
        tf = shape.text_frame
        tf.word_wrap = content.word_wrap
        # tf.text = content.text

        # # 样式应用
        # for p in tf.paragraphs:
        #     p.alignment = layout.alignment.pptx_val
        #     for run in p.runs:
        #         run.font.size = Pt(content.font_size)
        #         run.font.bold = content.font_bold
        #         run.font.color.rgb = content.font_color.rgb
        #         pptx_ea_font.set_font(run, content.font_name)

        # logger.info(f"Page {page_num}: 添加文本 '{content.text[:50]}...'")

        # 获取第一个段落
        p = tf.paragraphs[0]
        p.alignment = layout.alignment.pptx_val
        p.clear()  # 清除默认产生的空字符，准备从头填充

        # === 核心修改：解析 Markdown 语法 ===
        # 使用正则将文本按 ** 分割
        # 例如: "A **B** C" -> ['A ', 'B', ' C']

        parts = re.split(r"\*\*(.*?)\*\*", content.text)

        for i, part in enumerate(parts):
            # 跳过空字符串
            if not part:
                continue

            # 为每一段创建一个新的 Run
            run = p.add_run()
            run.text = part

            # --- 应用通用样式 (应用到每一个片段) ---
            run.font.size = Pt(content.font_size)
            run.font.color.rgb = content.font_color.rgb
            pptx_ea_font.set_font(run, content.font_name)  # 设置字体

            # --- 应用动态加粗逻辑 ---
            # 如果索引是奇数 (1, 3, 5...)，说明它原本是在 **...** 里面的，强制加粗
            if i % 2 == 1:
                run.font.bold = True
            else:
                # 否则使用 content 对象里定义的默认加粗设置
                run.font.bold = content.font_bold

        logger.info(f"Page {page_num}: 添加富文本 '{content.text[:50]}...'")

    def add_table(
        self,
        page_num: int,
        layout: LayoutModel,
        data: pd.DataFrame,
        font_name: str = "方正兰亭黑_GBK",
        font_size: int = 6,
    ) -> None:
        """
        添加表格

        Args:
            page_num (int): 幻灯片页码（从1开始）
            layout (LayoutModel): 布局配置
            data (pd.DataFrame): 表格数据
            font_name (str): 字体名称，默认'方正兰亭黑_GBK'
            font_size (int): 字体大小，默认6
        """
        slide = self._get_slide(page_num)
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

        # 内部辅助函数：设置单元格样式
        def _set_cell_text(cell, text, is_bold=False):
            cell.text = str(text)
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(font_size)
                    run.font.bold = is_bold
                    try:
                        pptx_ea_font.set_font(run, font_name)
                    except Exception:
                        logger.warning(f"字体 {font_name} 不存在，使用默认字体")

        # 设置表头
        for col_idx, col_name in enumerate(data.columns):
            _set_cell_text(table.cell(0, col_idx), col_name, is_bold=True)

        # 设置数据
        for row_idx in range(rows):
            for col_idx in range(cols):
                val = data.iloc[row_idx, col_idx]
                _set_cell_text(table.cell(row_idx + 1, col_idx), val, is_bold=False)

        logger.info(f"Page {page_num}: 添加 {rows}x{cols} 表格")

    def add_rectangle(
        self,
        page_num: int,
        layout: LayoutModel,
        style: RectangleStyleModel | None = None,
    ) -> None:
        """添加矩形色块

        Args:
            page_num (int): 幻灯片页码（从1开始）
            layout (LayoutModel): 布局配置
            style (RectangleStyleModel): 矩形样式配置
        """
        slide = self._get_slide(page_num)

        # 添加形状
        shape = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Cm(layout.left),
            Cm(layout.top),
            Cm(layout.width),
            Cm(layout.height),
        )
        shape.rotation = style.rotation

        # 填充
        shape.fill.solid()
        shape.fill.fore_color.rgb = style.fore_color.rgb  # 直接使用 Enum 属性

        # 边框
        if style.line_width > 0:
            shape.line.color.rgb = style.line_color.rgb
            shape.line.width = Pt(style.line_width)
        else:
            shape.line.fill.background()

        if style.is_background:
            shape.fill.background()

        logger.info(f"Page {page_num}: 添加矩形")

    def add_picture(self, page_num: int, img_path: str, layout: LayoutModel) -> None:
        """
        添加图片

        Args:
            page_num (int): 幻灯片页码（从1开始）
            img_path (str): 图片路径
            layout (LayoutModel): 布局配置
        """
        slide = self._get_slide(page_num)
        if not os.path.exists(img_path):
            logger.error(f"图片不存在: {img_path}")
            return

        slide.shapes.add_picture(
            img_path,
            Cm(layout.left),
            Cm(layout.top),
            width=Cm(layout.width),  # 高度可选，按比例缩放
        )
        logger.info(f"Page {page_num}: 添加图片 {os.path.basename(img_path)}")

    def _prepare_chart_data(self, df: pd.DataFrame) -> ChartData:
        """
        内部工具：将 DataFrame 转换为 ChartData
        约定:
        DataFrame Index -> Series Names (图例)
        DataFrame Columns -> Categories (X轴)
        """
        chart_data = ChartData()
        chart_data.categories = df.columns
        for i in range(len(df)):
            series_data = df.iloc[i].fillna(0)
            chart_data.add_series(str(df.index[i]), series_data)
        return chart_data

    def _apply_chart_formatting(self, chart, config: BaseChartConfig) -> None:
        """
        应用通用图表格式

        Args:
            chart: 图表对象
            config(BaseChartConfig): 图表配置对象
        """
        # 字体
        if hasattr(chart, "font"):
            chart.font.name = config.font_name
            chart.font.size = Pt(config.font_size)

        # 图例
        chart.has_legend = config.has_legend
        if config.has_legend:
            chart.legend.position = XL_LEGEND_POSITION.TOP
            chart.legend.include_in_layout = False
            chart.legend.font.size = Pt(config.font_size)

        # 标题
        chart.has_title = bool(config.title)
        if chart.has_title:
            chart.chart_title.text_frame.text = config.title

        # 配色
        if config.style_name in CHART_THEMES:
            colors = CHART_THEMES[config.style_name]
            for i, series in enumerate(chart.series):
                if i < len(colors):
                    # 针对柱状图/折线图通用的填充设置
                    if hasattr(series.format.fill, "solid"):
                        series.format.fill.solid()
                        series.format.fill.fore_color.rgb = colors[i]
                    # 针对折线图的线条设置
                    if hasattr(series.format.line, "color"):
                        series.format.line.color.rgb = colors[i]

    def add_bar_chart(
        self,
        page_num: int,
        df: pd.DataFrame,
        layout: LayoutModel,
        config: BarChartConfig,
    ) -> None:
        """
        添加柱状图

        Args:
            page_num (int): 幻灯片页码（从1开始）
            df (pd.DataFrame):
                - Index (索引) -> 变为图例 (系列)
                - Columns (列名) -> 变为 X 轴标签 (类别)
            layout (LayoutModel): Pydantic 布局模型
            config (BarChartConfig): Pydantic 图表配置模型
        """
        slide = self._get_slide(page_num)
        chart_data = self._prepare_chart_data(df)

        chart_type = XL_CHART_TYPE.COLUMN_CLUSTERED
        if config.grouping == "stacked":
            chart_type = XL_CHART_TYPE.COLUMN_STACKED

        graphic_frame = slide.shapes.add_chart(
            chart_type,
            Cm(layout.left),
            Cm(layout.top),
            Cm(layout.width),
            Cm(layout.height),
            chart_data,
        )
        chart = graphic_frame.chart

        self._apply_chart_formatting(chart, config)

        # 柱状图特有设置
        if len(chart.plots) > 0:
            chart.plots[0].gap_width = config.gap_width
            chart.plots[0].overlap = config.overlap
            if config.has_data_labels:
                chart.plots[0].has_data_labels = True
                data_label = chart.plots[0].data_labels
                data_label.font.size = Pt(config.font_size - 1)
                data_label.position = XL_DATA_LABEL_POSITION.OUTSIDE_END

        # 坐标轴
        try:
            val_axis = chart.value_axis
            val_axis.visible = config.y_axis_visible
            val_axis.tick_labels.font.size = Pt(config.font_size)
            if config.value_axis_max:
                val_axis.maximum_scale = config.value_axis_max

            cat_axis = chart.category_axis
            cat_axis.visible = config.x_axis_visible
            cat_axis.tick_labels.font.size = Pt(config.font_size)
        except Exception as e:
            logger.warning(f"设置图表坐标轴时发生异常: {e}")

        logger.debug(f"Page {page_num}: 添加柱状图")

    def add_line_chart(
        self,
        page_num: int,
        df: pd.DataFrame,
        layout: LayoutModel,
        config: LineChartConfig,
    ) -> None:
        """
        添加折线图

        Args:
            page_num (int): 幻灯片页码（从1开始）
            df (pd.DataFrame):
                - Index (索引) -> 变为图例 (系列)
                - Columns (列名) -> 变为 X 轴标签 (类别)
            layout (LayoutModel): Pydantic 布局模型
            config (LineChartConfig): Pydantic 图表配置模型
        """
        slide = self._get_slide(page_num)
        chart_data = self._prepare_chart_data(df)

        chart_type = (
            XL_CHART_TYPE.LINE_MARKERS if config.has_markers else XL_CHART_TYPE.LINE
        )
        graphic_frame = slide.shapes.add_chart(
            chart_type,
            Cm(layout.left),
            Cm(layout.top),
            Cm(layout.width),
            Cm(layout.height),
            chart_data,
        )
        chart = graphic_frame.chart

        self._apply_chart_formatting(chart, config)

        if len(chart.plots) > 0:
            if config.has_data_labels:
                plot = chart.plots[0]
                plot.has_data_labels = True
                data_labels = plot.data_labels
                data_labels.font.size = Pt(config.font_size)
                data_labels.position = XL_DATA_LABEL_POSITION.ABOVE
            # 平滑曲线设置
            for series in chart.series:
                series.smooth = config.smooth_line
                series.format.line.width = Pt(config.line_width)
