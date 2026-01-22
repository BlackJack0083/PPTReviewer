# ppt_operations.py - PPT操作核心类
from pathlib import Path
from typing import Self

import pandas as pd
import pptx_ea_font
from loguru import logger
from pptx import Presentation
from pptx.chart.data import ChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_DATA_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.slide import Slide
from pptx.util import Cm, Pt

from config import CHART_THEMES
from utils import parse_markdown_style

# 引入 Pydantic 模型
from .schemas import (
    AxisChartConfig,
    BarChartConfig,
    BaseChartConfig,
    LayoutModel,
    LineChartConfig,
    RectangleStyleModel,
    TableConfig,
    TextContentModel,
)


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
    DEFAULT_SLIDE_WIDTH_CM = 25.4
    DEFAULT_SLIDE_HEIGHT_CM = 14.29
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
        self.output_path = Path(output_file_path)
        self.template_path = Path(template_file_path) if template_file_path else None
        self.presentation = self._load_presentation()

    def _load_presentation(self) -> Presentation:
        """加载或新建 Presentation 对象"""
        if self.template_path and self.template_path.exists():
            logger.info(f"Loading template: {self.template_path}")
            return Presentation(str(self.template_path))

        if self.output_path.exists():
            logger.info(f"Loading existing PPT: {self.output_path}")
            return Presentation(str(self.output_path))

        logger.info("Creating new blank Presentation")
        return Presentation()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.save()
        else:
            logger.error(f"操作过程中发生异常，未保存: {exc_val}")

    def save(self) -> None:
        """保存文件，自动创建父目录"""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.presentation.save(str(self.output_path))
            logger.info(f"PPT saved to: {self.output_path}")
        except Exception as e:
            logger.error(f"Failed to save PPT: {e}")
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
        width_cm = slide_width_cm or self.DEFAULT_SLIDE_WIDTH_CM
        height_cm = slide_height_cm or self.DEFAULT_SLIDE_HEIGHT_CM

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

        # 获取第一个段落
        p = tf.paragraphs[0]
        p.alignment = layout.alignment.pptx_val
        p.clear()  # 清除默认产生的空字符，准备从头填充

        for segment in parse_markdown_style(content.text):
            # 为每一段创建一个新的 Run
            run = p.add_run()
            run.text = segment.text

            run.font.size = Pt(content.font_size)
            run.font.color.rgb = content.font_color.rgb
            try:
                # pptx_ea_font.set_font(run, content.font_name)  # 设置中文字体
                run.font.name = content.font_name
            except Exception as e:
                logger.warning(f"字体 {content.font_name} 设置失败: {e}, 使用默认字体")
            run.font.bold = segment.is_bold or content.font_bold

        logger.info(f"Page {page_num}: 添加富文本 '{content.text[:50]}...'")

    def add_table(
        self,
        page_num: int,
        layout: LayoutModel,
        data: pd.DataFrame,
        config: TableConfig | None = None,
    ) -> None:
        """
        添加表格

        Args:
            page_num (int): 幻灯片页码（从1开始）
            layout (LayoutModel): 布局配置
            data (pd.DataFrame): 表格数据
            config (TableConfig): 表格样式配置，None则使用默认样式
        """
        # 使用默认样式（向后兼容）
        if config is None:
            config = TableConfig()

        # 重置索引为列,以便在表格中显示
        # data_reset = data.reset_index()
        data_reset = data
        rows, cols = data_reset.shape

        slide = self._get_slide(page_num)

        # 表格尺寸: 数据行 + 1行表头
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
        def _set_cell_text(cell, text, font_size, font_color, bg_color, is_bold=False):
            cell.text = str(text)
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(font_size)
                    run.font.color.rgb = font_color.rgb
                    run.font.bold = is_bold
                    try:
                        pptx_ea_font.set_font(run, config.font_name)
                    except Exception:
                        logger.warning(f"字体 {config.font_name} 不存在，使用默认字体")

            # 设置单元格背景色
            cell.fill.solid()
            cell.fill.fore_color.rgb = bg_color.rgb

        # 设置表头
        for col_idx, col_name in enumerate(data_reset.columns):
            _set_cell_text(
                table.cell(0, col_idx),
                str(col_name),
                config.header_font_size,
                config.header_font_color,
                config.header_bg_color,
                config.header_font_bold,
            )

        # 设置数据
        for row_idx in range(rows):
            for col_idx in range(cols):
                val = data_reset.iloc[row_idx, col_idx]
                _set_cell_text(
                    table.cell(row_idx + 1, col_idx),
                    str(val),
                    config.body_font_size,
                    config.body_font_color,
                    config.body_bg_color,
                    config.body_font_bold,
                )

        # 设置列宽
        # TODO: 更灵活的列宽配置，目前简单实现首列较窄，其余均分
        first_col_ratio = 0.07  # 第一列宽度比例
        other_cols_ratio = 1 - first_col_ratio 

        # 设置第一列宽度
        table.columns[0].width = Cm(layout.width * first_col_ratio)

        # 设置其余列宽度（平分剩余宽度）
        if cols > 1:
            other_col_width = (layout.width * other_cols_ratio) / (cols - 1)
            for col_idx in range(1, cols):
                table.columns[col_idx].width = Cm(other_col_width)

        logger.debug(
            f"Page {page_num}: 添加 {rows}x{cols} 表格 (首列: {layout.width * first_col_ratio:.2f}cm, 其他: {(layout.width * other_cols_ratio / (cols - 1) if cols > 1 else 0):.2f}cm)"
        )

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

        if style is None:
            style = RectangleStyleModel()

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
        path = Path(img_path)
        if not path.exists():
            logger.warning(f"Image not found: {path}")
            return

        slide.shapes.add_picture(
            str(path),
            Cm(layout.left),
            Cm(layout.top),
            width=Cm(layout.width),  # 高度可选，按比例缩放
        )
        logger.info(f"Page {page_num}: 添加图片{path.name}")

    def _prepare_chart_data(self, df: pd.DataFrame) -> ChartData:
        """
        内部工具：将 DataFrame 转换为 ChartData
        强制将 numpy 类型转换为 python 原生类型 (list, int, float)

        约定:
            DataFrame Index -> Series Names (图例)
            DataFrame Columns -> Categories (X轴)
        """
        chart_data = ChartData()

        # 1. 转换 Categories: 确保它是纯字符串/数字列表，而不是 Index 对象
        chart_data.categories = list(df.columns)

        for i in range(len(df)):
            # 2. 转换 Values: 使用 .tolist() 将 numpy 数组转为 python list
            # 重要，python-pptx 要求数据类型是 python 原生类型
            series_data = df.iloc[i].fillna(0).tolist()

            # 3. 确保 Series Name 是字符串
            series_name = str(df.index[i])

            chart_data.add_series(series_name, series_data)

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
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
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

    def _create_base_chart(
        self,
        page_num: int,
        layout: LayoutModel,
        df: pd.DataFrame,
        chart_type: XL_CHART_TYPE,
    ):
        """通用：创建图表骨架"""
        slide = self._get_slide(page_num)
        chart_data = self._prepare_chart_data(df)

        graphic_frame = slide.shapes.add_chart(
            chart_type,
            Cm(layout.left),
            Cm(layout.top),
            Cm(layout.width),
            Cm(layout.height),
            chart_data,
        )
        return graphic_frame.chart

    def _configure_axes(self, chart, config: AxisChartConfig):
        """通用：配置坐标轴"""
        try:
            # Y轴
            val_axis = chart.value_axis
            val_axis.visible = config.y_axis_visible
            # 关闭网格线
            val_axis.has_major_gridlines = False
            
            val_axis.tick_labels.font.size = Pt(config.font_size)
            if config.value_axis_max:
                val_axis.maximum_scale = config.value_axis_max
            if config.value_axis_format:
                val_axis.tick_labels.number_format = config.value_axis_format

            # X轴
            cat_axis = chart.category_axis
            cat_axis.visible = config.x_axis_visible
            cat_axis.tick_labels.font.size = Pt(config.font_size)

        except ValueError:
            # 某些图表类型（如饼图）没有坐标轴，忽略错误
            pass

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
        # 1. 确定类型
        c_type = (
            XL_CHART_TYPE.COLUMN_STACKED
            if config.grouping == "stacked"
            else XL_CHART_TYPE.COLUMN_CLUSTERED
        )

        # 2. 创建骨架
        chart = self._create_base_chart(page_num, layout, df, c_type)

        # 3. 应用通用样式 & 坐标轴
        self._apply_chart_formatting(chart, config)
        self._configure_axes(chart, config)

        # 4. 应用柱状图特有属性
        if chart.plots:
            plot = chart.plots[0]
            plot.gap_width = config.gap_width
            plot.overlap = config.overlap

            plot.vary_by_categories = False
            
            if config.has_data_labels:
                plot.has_data_labels = True
                labels = plot.data_labels
                labels.font.size = Pt(config.font_size - 1)
                labels.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
            else:
                plot.has_data_labels = False

        logger.debug(f"Page {page_num}: Added Bar Chart")

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
        # 1. 确定类型
        c_type = (
            XL_CHART_TYPE.LINE_MARKERS if config.has_markers else XL_CHART_TYPE.LINE
        )

        # 2. 创建骨架
        chart = self._create_base_chart(page_num, layout, df, c_type)

        # 3. 应用通用样式 & 坐标轴
        self._apply_chart_formatting(chart, config)
        self._configure_axes(chart, config)

        # 4. 应用折线图特有属性
        if chart.plots:
            plot = chart.plots[0]
            if config.has_data_labels:
                plot.has_data_labels = True
                data_labels = plot.data_labels
                data_labels.font.size = Pt(config.font_size)
                data_labels.position = XL_DATA_LABEL_POSITION.ABOVE
            else:
                plot.has_data_labels = False

            # 平滑与线宽 (需遍历 series)
            for series in chart.series:
                series.smooth = config.smooth_line
                series.format.line.width = Pt(config.line_width)

        logger.debug(f"Page {page_num}: Added Line Chart")
