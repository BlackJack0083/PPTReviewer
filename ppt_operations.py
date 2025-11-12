"""
PPT操作API模块
使用python-pptx包实现基本的PPT操作功能
"""

from pptx import Presentation
from pptx.util import Inches, Pt, Cm
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
from pptx.oxml.xmlchemy import OxmlElement
import pandas as pd
import os
from typing import Dict, Any, Optional
import pptx_ea_font


class PPTOperations:
    """PPT操作类，封装基本的PPT创建和编辑功能"""

    def __init__(self):
        self.presentation = None
        self.ppt_path = None

    def create_slide(self, ppt_name: str, page_num: int, slide_width: float,
                    slide_height: float, ppt_script: str) -> None:
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
        print(f"成功创建PPT文件: {ppt_script}")

    def _load_presentation(self, ppt_script: str) -> None:
        """加载现有的PPT文件"""
        if self.ppt_path != ppt_script or self.presentation is None:
            self.presentation = Presentation(ppt_script)
            self.ppt_path = ppt_script

    def _get_font_color(self, color_str: str) -> RGBColor:
        """将颜色字符串转换为RGBColor对象"""
        color_map = {
            '黑色': RGBColor(0, 0, 0),
            '白色': RGBColor(255, 255, 255),
            '红色': RGBColor(255, 0, 0),
            '绿色': RGBColor(0, 128, 0),
            '蓝色': RGBColor(0, 0, 255),
            '黄色': RGBColor(255, 255, 0)
        }
        return color_map.get(color_str, RGBColor(0, 0, 0))

    def _get_alignment(self, alignment_str: str) -> PP_ALIGN:
        """将对齐方式字符串转换为PP_ALIGN对象"""
        alignment_map = {
            '左对齐': PP_ALIGN.LEFT,
            '居中': PP_ALIGN.CENTER,
            '右对齐': PP_ALIGN.RIGHT
        }
        return alignment_map.get(alignment_str, PP_ALIGN.LEFT)

    def add_title(self, ppt_script: str, page_num: int, content: Dict[str, Any],
                 layout: Dict[str, Any]) -> None:
        """
        添加标题文本框

        Args:
            ppt_script (str): PPT文件路径
            page_num (int): 幻灯片页码（从1开始）
            content (dict): 文本内容配置
            layout (dict): 布局配置
        """
        self._load_presentation(ppt_script)

        # 获取指定页面
        if page_num > len(self.presentation.slides) or page_num < 1:
            raise ValueError(f"页码 {page_num} 超出范围")

        slide = self.presentation.slides[page_num - 1]

        # 提取内容参数
        text = content.get('text', '')
        font_size = content.get('font_size', 18)
        font_bold = content.get('font_bold', True)
        font_name = content.get('font_name', '方正兰亭黑_GBK')
        font_color = content.get('font_color', '黑色')

        # 提取布局参数
        left = layout.get('left', 1)
        top = layout.get('top', 1)
        width = layout.get('width', 10)
        height = layout.get('height', 2)
        alignment = layout.get('alignment', '左对齐')
        word_wrap = layout.get('word_wrap', True)

        # 添加文本框
        text_box = slide.shapes.add_textbox(
            Cm(left), Cm(top), Cm(width), Cm(height)
        )
        text_frame = text_box.text_frame
        text_frame.text = text

        # 设置字体属性
        for paragraph in text_frame.paragraphs:
            paragraph.alignment = self._get_alignment(alignment)
            for run in paragraph.runs:
                run.font.size = Pt(font_size)
                run.font.bold = font_bold
                # run.font.name = font_name
                pptx_ea_font.set_font(run, font_name)
                run.font.color.rgb = self._get_font_color(font_color)

        text_frame.word_wrap = word_wrap

        # 保存文件
        self.presentation.save(ppt_script)
        print(f"成功在第{page_num}页添加标题")

    def add_content(self, ppt_script: str, page_num: int, content: Dict[str, Any],
                   layout: Dict[str, Any]) -> None:
        """
        添加内容文本框

        Args:
            ppt_script (str): PPT文件路径
            page_num (int): 幻灯片页码（从1开始）
            content (dict): 文本内容配置
            layout (dict): 布局配置
        """
        self._load_presentation(ppt_script)

        # 获取指定页面
        if page_num > len(self.presentation.slides) or page_num < 1:
            raise ValueError(f"页码 {page_num} 超出范围")

        slide = self.presentation.slides[page_num - 1]

        # 提取内容参数
        text = content.get('text', '')
        font_size = content.get('font_size', 18)
        font_bold = content.get('font_bold', True)
        font_name = content.get('font_name', '方正兰亭黑_GBK')
        font_color = content.get('font_color', '黑色')

        # 提取布局参数
        left = layout.get('left', 1)
        top = layout.get('top', 1)
        width = layout.get('width', 10)
        height = layout.get('height', 5)
        alignment = layout.get('alignment', '左对齐')
        word_wrap = layout.get('word_wrap', True)

        # 添加文本框
        text_box = slide.shapes.add_textbox(
            Cm(left), Cm(top), Cm(width), Cm(height)
        )
        text_frame = text_box.text_frame
        text_frame.text = text

        # 设置字体属性
        for paragraph in text_frame.paragraphs:
            paragraph.alignment = self._get_alignment(alignment)
            for run in paragraph.runs:
                run.font.size = Pt(font_size)
                run.font.bold = font_bold
                # run.font.name = font_name
                pptx_ea_font.set_font(run, font_name)
                run.font.color.rgb = self._get_font_color(font_color)

        text_frame.word_wrap = word_wrap

        # 保存文件
        self.presentation.save(ppt_script)
        print(f"成功在第{page_num}页添加内容")

    def add_table(self, ppt_script: str, page_num: int, layout: Dict[str, Any],
                 data: pd.DataFrame, font_name: str = '方正兰亭黑_GBK',
                 fontsize: int = 6) -> None:
        """
        添加表格

        Args:
            ppt_script (str): PPT文件路径
            page_num (int): 幻灯片页码（从1开始）
            layout (dict): 布局配置
            data (pd.DataFrame): 表格数据
            fontname (str): 字体名称，默认'方正兰亭黑_GBK'
            fontsize (int): 字体大小，默认6
        """
        self._load_presentation(ppt_script)

        # 获取指定页面
        if page_num > len(self.presentation.slides) or page_num < 1:
            raise ValueError(f"页码 {page_num} 超出范围")

        slide = self.presentation.slides[page_num - 1]

        # 提取布局参数
        left = layout.get('left', 1)
        top = layout.get('top', 1)
        width = layout.get('width', 15)
        height = layout.get('height', 8)

        # 获取表格行数和列数
        rows, cols = data.shape

        # 添加表格
        table_shape = slide.shapes.add_table(
            rows + 1, cols,  # +1 为了包含标题行
            Cm(left), Cm(top), Cm(width), Cm(height)
        )
        table = table_shape.table

        # 设置表格内容
        # 设置标题行
        for col_idx, col_name in enumerate(data.columns):
            cell = table.cell(0, col_idx)
            cell.text = str(col_name)
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    # run.font.name = fontname
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
        print(f"成功在第{page_num}页添加表格")


# 创建全局实例
ppt_ops = PPTOperations()


def create_slide(ppt_name: str, page_num: int, slide_width: float,
                slide_height: float, ppt_script: str) -> None:
    """
    创建新的PPT文件

    Args:
        ppt_name (str): PPT文件名
        page_num (int): 页数
        slide_width (float): 幻灯片宽度（厘米）
        slide_height (float): 幻灯片高度（厘米）
        ppt_script (str): PPT保存路径
    """
    ppt_ops.create_slide(ppt_name, page_num, slide_width, slide_height, ppt_script)


def add_title(ppt_script: str, page_num: int, content: Dict[str, Any],
             layout: Dict[str, Any]) -> None:
    """
    添加标题文本框

    Args:
        ppt_script (str): PPT文件路径
        page_num (int): 幻灯片页码（从1开始）
        content (dict): 文本内容配置，包含以下键：
            - 'text' (str): 文本内容
            - 'font_size' (int, 可选): 字体大小，默认18
            - 'font_bold' (bool, 可选): 是否加粗，默认True
            - 'font_name' (str, 可选): 字体名称，默认'方正兰亭黑_GBK'
            - 'font_color' (str, 可选): 字体颜色，默认黑色
        layout (dict): 布局配置，包含以下键：
            - left (float): 文本框左上角的水平位置（单位：厘米）
            - top (float): 文本框左上角的垂直位置（单位：厘米）
            - width (float): 文本框宽度（单位：厘米）
            - height (float): 文本框高度（单位：厘米）
            - alignment (str): 对齐方式（支持'左对齐', '居中'）
            - word_wrap (bool): 是否自动换行
    """
    ppt_ops.add_title(ppt_script, page_num, content, layout)


def add_content(ppt_script: str, page_num: int, content: Dict[str, Any],
               layout: Dict[str, Any]) -> None:
    """
    添加内容文本框

    Args:
        ppt_script (str): PPT文件路径
        page_num (int): 幻灯片页码（从1开始）
        content (dict): 文本内容配置，包含以下键：
            - 'text' (str): 文本内容
            - 'font_size' (int, 可选): 字体大小，默认18
            - 'font_bold' (bool, 可选): 是否加粗，默认True
            - 'font_name' (str, 可选): 字体名称，默认'方正兰亭黑_GBK'
            - 'font_color' (str, 可选): 字体颜色，默认黑色
        layout (dict): 布局配置，包含以下键：
            - left (float): 文本框左上角的水平位置（单位：厘米）
            - top (float): 文本框左上角的垂直位置（单位：厘米）
            - width (float): 文本框宽度（单位：厘米）
            - height (float): 文本框高度（单位：厘米）
            - alignment (str): 对齐方式（支持'左对齐', '居中'）
            - word_wrap (bool): 是否自动换行
    """
    ppt_ops.add_content(ppt_script, page_num, content, layout)


def add_table(ppt_script: str, page_num: int, layout: Dict[str, Any],
             data: pd.DataFrame, fontname: str = '方正兰亭黑_GBK',
             fontsize: int = 6) -> None:
    """
    添加表格

    Args:
        ppt_script (str): PPT文件路径
        page_num (int): 幻灯片页码（从1开始）
        layout (dict): 布局配置，包含以下键：
            - left (float): 文本框左上角的水平位置（单位：厘米）
            - top (float): 文本框左上角的垂直位置（单位：厘米）
            - width (float): 文本框宽度（单位：厘米）
            - height (float): 文本框高度（单位：厘米）
        data (pd.DataFrame): 表格数据
        fontname (str): 字体名称，默认'方正兰亭黑_GBK'
        fontsize (int): 字体大小，默认6
    """
    ppt_ops.add_table(ppt_script, page_num, layout, data, fontname, fontsize)