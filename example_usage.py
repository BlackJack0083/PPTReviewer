"""
PPT操作API使用示例
演示如何使用PPT操作接口创建和编辑PowerPoint文件
"""

import os
import pandas as pd
from ppt_operations import create_slide, add_title, add_content, add_table


def example_basic_usage():
    """基本使用示例"""
    print("=== 基本使用示例 ===")

    # 1. 创建新的PPT文件
    ppt_name = "演示文稿示例"
    page_num = 2
    slide_width = 25.4  # 标准A4宽度（厘米）
    slide_height = 19.05  # 标准A4高度（厘米）
    ppt_path = "./output/example.pptx"

    # 确保输出目录存在
    os.makedirs(os.path.dirname(ppt_path), exist_ok=True)

    # 创建PPT
    create_slide(ppt_name, page_num, slide_width, slide_height, ppt_path)

    # 2. 在第一页添加标题
    title_content = {
        'text': 'Python PPT操作示例',
        'font_size': 28,
        'font_bold': True,
        'font_name': '方正兰亭黑_GBK',
        'font_color': '黑色'
    }

    title_layout = {
        'left': 2.0,
        'top': 1.5,
        'width': 20.0,
        'height': 3.0,
        'alignment': '居中',
        'word_wrap': True
    }

    add_title(ppt_path, 1, title_content, title_layout)

    # 3. 在第一页添加内容
    content_text = {
        'text': '这是一个使用python-pptx库创建的演示文稿示例。\n\n主要功能包括：\n• 创建新的PPT文件\n• 添加标题文本框\n• 添加内容文本框\n• 添加数据表格\n• 自定义字体、颜色和布局',
        'font_size': 16,
        'font_bold': False,
        'font_name': '方正兰亭黑_GBK',
        'font_color': '黑色'
    }

    content_layout = {
        'left': 2.0,
        'top': 5.0,
        'width': 20.0,
        'height': 8.0,
        'alignment': '左对齐',
        'word_wrap': True
    }

    add_content(ppt_path, 1, content_text, content_layout)

    # 4. 在第二页添加数据表格
    sales_data = pd.DataFrame({
        '产品名称': ['笔记本电脑', '台式机', '平板电脑', '智能手机', '智能手表'],
        '第一季度': [120, 80, 150, 200, 90],
        '第二季度': [135, 75, 165, 220, 105],
        '第三季度': [145, 85, 175, 240, 120],
        '第四季度': [160, 90, 190, 260, 140]
    })

    table_layout = {
        'left': 1.5,
        'top': 2.0,
        'width': 22.0,
        'height': 12.0
    }

    add_table(ppt_path, 2, table_layout, sales_data, '方正兰亭黑_GBK', 10)

    print(f"示例PPT已创建: {ppt_path}")
    return ppt_path


def example_advanced_usage():
    """高级使用示例"""
    print("\n=== 高级使用示例 ===")

    # 创建一个更复杂的演示文稿
    ppt_name = "高级演示文稿"
    page_num = 3
    slide_width = 25.4
    slide_height = 19.05
    ppt_path = "./output/advanced_example.pptx"

    os.makedirs(os.path.dirname(ppt_path), exist_ok=True)

    # 创建PPT
    create_slide(ppt_name, page_num, slide_width, slide_height, ppt_path)

    # 第一页：封面
    cover_title = {
        'text': '年度销售报告',
        'font_size': 36,
        'font_bold': True,
        'font_name': '方正兰亭黑_GBK',
        'font_color': '黑色'
    }

    cover_title_layout = {
        'left': 3.0,
        'top': 4.0,
        'width': 18.0,
        'height': 4.0,
        'alignment': '居中',
        'word_wrap': True
    }

    add_title(ppt_path, 1, cover_title, cover_title_layout)

    subtitle = {
        'text': '2024年业绩回顾与展望\n销售部门',
        'font_size': 20,
        'font_bold': False,
        'font_name': '方正兰亭黑_GBK',
        'font_color': '黑色'
    }

    subtitle_layout = {
        'left': 5.0,
        'top': 9.0,
        'width': 14.0,
        'height': 4.0,
        'alignment': '居中',
        'word_wrap': True
    }

    add_content(ppt_path, 1, subtitle, subtitle_layout)

    # 第二页：数据概览
    page2_title = {
        'text': '销售数据概览',
        'font_size': 24,
        'font_bold': True,
        'font_name': '方正兰亭黑_GBK',
        'font_color': '黑色'
    }

    page2_title_layout = {
        'left': 2.0,
        'top': 1.0,
        'width': 15.0,
        'height': 2.0,
        'alignment': '居中',
        'word_wrap': True
    }

    add_title(ppt_path, 2, page2_title, page2_title_layout)

    # 创建季度销售数据
    quarterly_data = pd.DataFrame({
        '季度': ['Q1', 'Q2', 'Q3', 'Q4'],
        '销售额（万元）': [850, 920, 1050, 1180],
        '同比增长（%）': [12.5, 8.2, 14.1, 12.4],
        '客户满意度': [4.2, 4.3, 4.5, 4.6]
    })

    quarterly_table_layout = {
        'left': 2.0,
        'top': 4.0,
        'width': 20.0,
        'height': 8.0
    }

    add_table(ppt_path, 2, quarterly_table_layout, quarterly_data, '方正兰亭黑_GBK', 12)

    # 第三页：产品分析
    page3_title = {
        'text': '产品销售分析',
        'font_size': 24,
        'font_bold': True,
        'font_name': '方正兰亭黑_GBK',
        'font_color': '黑色'
    }

    page3_title_layout = {
        'left': 2.0,
        'top': 1.0,
        'width': 15.0,
        'height': 2.0,
        'alignment': '居中',
        'word_wrap': True
    }

    add_title(ppt_path, 3, page3_title, page3_title_layout)

    # 产品分析数据
    product_data = pd.DataFrame({
        '产品类别': ['电子产品', '家居用品', '服装配饰', '食品饮料', '其他'],
        '销售数量': [1520, 890, 1200, 2100, 450],
        '销售收入（万元）': [456, 178, 240, 315, 89],
        '利润率（%）': [15.2, 22.1, 18.5, 12.8, 19.6]
    })

    product_table_layout = {
        'left': 1.5,
        'top': 3.5,
        'width': 22.0,
        'height': 10.0
    }

    add_table(ppt_path, 3, product_table_layout, product_data, '方正兰亭黑_GBK', 10)

    print(f"高级示例PPT已创建: {ppt_path}")
    return ppt_path


if __name__ == "__main__":
    # 运行基本示例
    basic_ppt = example_basic_usage()

    # 运行高级示例
    advanced_ppt = example_advanced_usage()

    print("\n所有示例已创建完成！")
    print(f"基本示例: {basic_ppt}")
    print(f"高级示例: {advanced_ppt}")
    print("\n请打开生成的PPT文件查看效果。")