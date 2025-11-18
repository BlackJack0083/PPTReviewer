"""
PPT操作API使用示例
演示如何使用 Pydantic 模型驱动的 PPT 操作接口
"""

import os

import pandas as pd
from loguru import logger

# 2. 导入封装好的操作函数
from ppt_operations import PPTOperations

# 1. 导入 Pydantic 模型
from ppt_schemas import (
    Align,
    ChartConfigModel,
    Color,
    LayoutModel,
    RectangleStyleModel,
    TextContentModel,
)

# --- 准备工作 ---
OUTPUT_DIR = "./output"
os.makedirs(OUTPUT_DIR, exist_ok=True)
logger.add(os.path.join(OUTPUT_DIR, "test_log.log"))

# 准备一个用于测试的图片
TEST_IMAGE_PATH = os.path.join(OUTPUT_DIR, "test_image.png")


def create_dummy_image():
    """创建一个用于测试的图片文件"""
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (200, 150), color="skyblue")
        d = ImageDraw.Draw(img)
        d.text((10, 10), "测试图片", fill="white")
        img.save(TEST_IMAGE_PATH)
        logger.info(f"创建测试图片: {TEST_IMAGE_PATH}")
    except ImportError:
        logger.warning("未安装 PIL 库，无法创建测试图片。")
        logger.warning(
            f"请手动放置一张图片到 {TEST_IMAGE_PATH} 以测试 add_picture 功能。"
        )
        # 即使失败也继续，允许测试其他功能
    except Exception as e:
        logger.error(f"创建测试图片失败: {e}")


# --- 测试函数 ---


def example_basic_usage():
    """基本使用示例 (已更新为 Pydantic)"""
    logger.info("=== 运行基本使用示例 ===")
    ppt_path = os.path.join(OUTPUT_DIR, "basic_example.pptx")

    easyppt = PPTOperations()

    # 1. 创建PPT
    easyppt.create_slide(
        ppt_name="基础示例",
        page_num=2,
        slide_width=25.4,
        slide_height=19.05,
        ppt_script=ppt_path,
    )

    # 2. 在第一页添加标题
    title_content = TextContentModel(
        text="Python PPT操作示例 (Pydantic)",
        font_size=28,
        font_bold=True,
        font_color=Color.BLACK,
        font_name="方正兰亭黑_GBK",
    )
    title_layout = LayoutModel(
        left=2.0, top=1.5, width=20.0, height=3.0, alignment=Align.CENTER
    )
    easyppt.add_title(ppt_path, 1, title_content, title_layout)

    # 3. 在第一页添加内容
    content_text = TextContentModel(
        text="这是一个使用 Pydantic 模型驱动的示例。\n\n主要功能包括：\n• 创建PPT\n• 添加标题\n• 添加内容\n• 添加表格",
        font_size=16,
        font_bold=False,
        font_color=Color.GRAY,
    )
    content_layout = LayoutModel(
        left=2.0, top=5.0, width=20.0, height=8.0, alignment=Align.LEFT
    )
    easyppt.add_content(ppt_path, 1, content_text, content_layout)

    # 4. 在第二页添加数据表格
    sales_data = pd.DataFrame(
        {
            "产品名称": ["笔记本", "台式机", "平板电脑", "智能手机"],
            "Q1": [120, 80, 150, 200],
            "Q2": [135, 75, 165, 220],
            "Q3": [145, 85, 175, 240],
        }
    )
    table_layout = LayoutModel(
        left=1.5,
        top=2.0,
        width=22.0,
        height=12.0,
        alignment=Align.CENTER,  # (此处的 alignment 对表格无效)
    )
    easyppt.add_table(ppt_path, 2, table_layout, sales_data, "方正兰亭黑_GBK", 10)

    logger.info(f"基础示例PPT已创建: {ppt_path}")
    return ppt_path


def example_full_features():
    """完整功能示例 (矩形, 图片, 图表)"""
    logger.info("\n=== 运行完整功能示例 ===")
    ppt_path = os.path.join(OUTPUT_DIR, "full_features_example.pptx")

    easyppt = PPTOperations()

    # 1. 创建PPT (3页)
    easyppt.create_slide(
        ppt_name="完整功能",
        page_num=3,
        slide_width=25.4,
        slide_height=19.05,
        ppt_script=ppt_path,
    )

    # 2. 第一页: 添加矩形作为背景
    rect_style = RectangleStyleModel(
        fore_color="lightblue",  # 使用 color_map 中的预设键
        line_width=0,
        rotation=15,  # 旋转15度
    )
    rect_layout = LayoutModel(left=0, top=0, width=10, height=10)
    easyppt.add_rectangle(ppt_path, 1, rect_layout, rect_style)

    page1_title = TextContentModel(text="完整功能测试页", font_size=32)
    page1_layout = LayoutModel(left=2, top=2, width=20, height=3, alignment=Align.LEFT)
    easyppt.add_title(ppt_path, 1, page1_title, page1_layout)

    # 3. 第二页: 添加图片
    try:
        pic_layout = LayoutModel(left=5, top=3, width=15)  # height 会被忽略，自动缩放
        easyppt.add_picture(ppt_path, 2, TEST_IMAGE_PATH, pic_layout)
        logger.info("成功添加图片")
    except Exception as e:
        logger.error(f"添加图片失败 (请检查 {TEST_IMAGE_PATH} 是否存在): {e}")

    # 4. 第三页: 添加图表
    chart_df = pd.DataFrame(
        {
            "系列1": [10, 25, 7],
            "系列2": [15, 30, 12],
        },
        index=["类别A", "类别B", "类别C"],
    )  # Index 变为图例, Columns 变为 X 轴

    chart_layout = LayoutModel(left=3, top=3, width=20, height=14)
    chart_config = ChartConfigModel(
        style_name="2_orange_green",  # 使用你定义的配色
        font_size=12,
        has_data_labels=True,
        value_axis_max=35.0,  # 强制Y轴最大值
    )
    easyppt.add_chart(ppt_path, 3, chart_df, chart_layout, chart_config)

    logger.info(f"完整功能PPT已创建: {ppt_path}")
    return ppt_path


if __name__ == "__main__":

    # 尝试创建测试图片
    create_dummy_image()

    # 运行基本示例
    basic_ppt = example_basic_usage()

    # 运行完整功能示例
    full_ppt = example_full_features()

    logger.info("\n=== 所有示例已创建完成！ ===")
    logger.info(f"基础示例: {basic_ppt}")
    logger.info(f"完整功能: {full_ppt}")
    logger.info("请打开 output 文件夹查看生成的PPT文件。")
