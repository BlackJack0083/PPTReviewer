#!/usr/bin/env python3
"""
测试新架构的PPT生成系统
"""

from pathlib import Path

import pandas as pd
from loguru import logger

from ppt_engine import PPTDataHelper, PPTGenerationEngine
from template_system.catalog import load_templates


def load_csv_data():
    """简单加载CSV数据"""
    file_path = "BeijingLiangxiang_slide1_chart1.csv"

    try:
        df = pd.read_csv(file_path)
        logger.info(f"CSV数据加载成功: {df.shape}")

        # 设置第一列为索引
        df = df.set_index(df.columns[0])
        logger.info(f"数据预览:\n{df.head()}")

        return df
    except Exception as e:
        logger.error(f"加载CSV失败: {e}")
        return None


def test_basic_functionality():
    """测试基本功能"""
    logger.info("=== 测试基本功能 ===")

    # 1. 加载模板
    try:
        load_templates()
        from template_system.catalog import TEMPLATE_CATALOG

        logger.info(f"模板加载成功，共 {len(TEMPLATE_CATALOG)} 个模板")

        # 查看可用模板
        for uid, template in TEMPLATE_CATALOG.items():
            logger.info(f"模板: {uid} -> {template.theme_key}.{template.function_key}")

    except Exception as e:
        logger.error(f"模板加载失败: {e}")
        return False

    # 2. 加载CSV数据
    csv_data = load_csv_data()
    if csv_data is None:
        logger.error("无法加载CSV数据")
        return False

    # 3. 测试text_manager
    try:
        from template_system.text_manager import text_manager

        # 测试变量
        test_vars = {
            "Temporal_Start_Year": "2023",
            "Temporal_End_Year": "2024",
            "Geo_City_Name": "北京",
            "Geo_Block_Name": "良乡",
        }

        # 尝试渲染文本
        title = text_manager.render(
            "Block Area Segment Distribution",
            "Supply-Transaction Unit Statistic",
            "title",
            test_vars,
        )
        logger.info(f"标题渲染成功: {title}")

        summary = text_manager.render(
            "Block Area Segment Distribution",
            "Supply-Transaction Unit Statistic",
            "summary",
            test_vars,
            0,
        )
        logger.info(f"摘要渲染成功: {summary}")

    except Exception as e:
        logger.error(f"文本渲染失败: {e}")
        return False

    return True


def test_ppt_generation():
    """测试PPT生成"""
    logger.info("=== 测试PPT生成 ===")

    try:
        # 准备上下文
        context = PPTDataHelper.create_context()

        # 加载CSV数据
        csv_data = load_csv_data()
        if csv_data is None:
            return False

        # 添加数据到上下文
        context.add_dataset("supply_trans_data", csv_data)

        # 添加变量
        context.add_variable("Temporal_Start_Year", "2023")
        context.add_variable("Temporal_End_Year", "2024")
        context.add_variable("Geo_City_Name", "北京")
        context.add_variable("Geo_Block_Name", "良乡")

        # 使用新模板生成PPT
        template_id = "T01_Supply_Trans_Bar"
        output_file = "output/test_new_system.pptx"

        engine = PPTGenerationEngine(output_file)

        # 直接测试builder
        from template_system.builder import SlideConfigBuilder

        builder = SlideConfigBuilder()

        slide_config = builder.build(template_id, context)
        logger.info(f"幻灯片配置构建成功: {slide_config['layout_type']}")

        # 生成PPT
        engine.generate_single_slide(template_id, context)

        logger.success(f"PPT生成成功: {output_file}")
        return True

    except Exception as e:
        logger.error(f"PPT生成失败: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """主测试函数"""
    logger.info("开始测试新架构系统...")

    # 确保输出目录存在
    Path("output").mkdir(exist_ok=True)

    # 测试基本功能
    if not test_basic_functionality():
        logger.error("基本功能测试失败")
        return

    # 测试PPT生成
    if not test_ppt_generation():
        logger.error("PPT生成测试失败")
        return

    logger.success("所有测试通过！")


if __name__ == "__main__":
    main()
