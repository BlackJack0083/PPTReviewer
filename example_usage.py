"""
PPT操作API使用示例 (适配 Refactor 后的新接口)
演示如何使用 Context Manager 和 Pydantic 模型
"""

import os

import pandas as pd
from loguru import logger

from ppt_operations import PPTOperations
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
        logger.warning("未安装 PIL 库，跳过图片生成。")
    except Exception as e:
        logger.error(f"创建测试图片失败: {e}")


# --- 测试函数 ---


def example_basic_usage():
    """基本使用示例"""
    logger.info("=== 运行基本使用示例 ===")
    ppt_path = os.path.join(OUTPUT_DIR, "basic_example.pptx")

    # 1: 使用 with 语句管理上下文，自动保存
    with PPTOperations(ppt_path) as ppt:

        # 2: 使用 init_slides 替代 create_slide
        # 确保至少有2页
        ppt.init_slides(count=2)

        # --- 第一页：标题 ---
        title_content = TextContentModel(
            text="Python PPT操作示例 (Refactored)",
            font_size=28,
            font_bold=True,
            font_color="黑色",  # 使用 Enum
            font_name="方正兰亭黑_GBK",
        )
        title_layout = LayoutModel(
            left=2.0, top=1.5, width=20.0, height=3.0, alignment=Align.CENTER
        )

        ppt.add_title(1, title_content, title_layout)

        # --- 第一页：正文 ---
        content_text = TextContentModel(
            text="这是一个使用 Pydantic 模型驱动的示例。\n\n主要改进：\n• 上下文管理器 (with)\n• 内存中操作，一次性保存\n• 统一 API 接口",
            font_size=16,
            font_bold=False,
            font_color="灰色",
        )
        content_layout = LayoutModel(
            left=2.0, top=5.0, width=20.0, height=8.0, alignment=Align.LEFT
        )
        ppt.add_content(1, content_text, content_layout)

        # --- 第二页：表格 ---
        sales_data = pd.DataFrame(
            {
                "产品名称": ["笔记本", "台式机", "平板电脑", "智能手机"],
                "Q1": [120, 80, 150, 200],
                "Q2": [135, 75, 165, 220],
                "Q3": [145, 85, 175, 240],
            }
        )
        table_layout = LayoutModel(
            left=1.5, top=2.0, width=22.0, height=12.0, alignment=Align.CENTER
        )
        # 参数顺序：页码, 布局, 数据
        ppt.add_table(2, table_layout, sales_data, font_size=10)

    logger.info(f"基础示例PPT已保存至: {ppt_path}")
    return ppt_path


def example_full_features():
    """完整功能示例 (矩形, 图片, 图表)"""
    logger.info("\n=== 运行完整功能示例 ===")
    ppt_path = os.path.join(OUTPUT_DIR, "full_features_example.pptx")

    with PPTOperations(ppt_path) as ppt:
        # 初始化3页
        ppt.init_slides(3)

        # --- 第一页：矩形背景 ---
        rect_style = RectangleStyleModel(
            # CHANGE 4: 必须传入 Color 枚举，不能传字符串 "lightblue"
            fore_color=Color.LIGHT_BLUE,
            line_color=Color.BLUE,
            line_width=2.0,
            rotation=15,
        )
        rect_layout = LayoutModel(left=2, top=2, width=10, height=10)
        ppt.add_rectangle(1, rect_layout, rect_style)

        # 添加一个文字说明覆盖在矩形上
        title_content = TextContentModel(text="完整功能测试页", font_size=32)
        title_layout = LayoutModel(left=2, top=2, width=20, height=3)
        ppt.add_title(1, title_content, title_layout)

        # --- 第二页：图片 ---
        if os.path.exists(TEST_IMAGE_PATH):
            pic_layout = LayoutModel(left=5, top=3, width=15, height=10)
            ppt.add_picture(2, TEST_IMAGE_PATH, pic_layout)
        else:
            logger.warning("测试图片不存在，跳过图片添加")

        # --- 第三页：图表 ---
        chart_df = pd.DataFrame(
            {
                "系列1": [10, 25, 7],
                "系列2": [15, 30, 12],
            },
            index=["类别A", "类别B", "类别C"],
        )

        chart_layout = LayoutModel(left=3, top=3, width=20, height=14)
        chart_config = ChartConfigModel(
            style_name="2_orange_green",
            font_size=12,
            has_data_labels=True,
            value_axis_max=40.0,
        )
        ppt.add_chart(3, chart_df, chart_layout, chart_config)

    logger.info(f"完整功能PPT已保存至: {ppt_path}")
    return ppt_path


if __name__ == "__main__":
    # 1. 创建辅助素材
    create_dummy_image()

    # 2. 运行测试
    try:
        basic_ppt = example_basic_usage()
        full_ppt = example_full_features()

        logger.info("\n=== 所有示例已创建完成！ ===")
        logger.info("请打开 output 文件夹查看生成的PPT文件。")
    except Exception as e:
        logger.exception(f"运行过程中发生错误: {e}")
