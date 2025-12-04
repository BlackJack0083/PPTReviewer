#!/usr/bin/env python3
"""
测试新架构的PPT生成系统
"""

from pathlib import Path

import pandas as pd
from loguru import logger

from data_manager.context import PresentationContext
from ppt_engine import PPTGenerationEngine


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


def test_ppt_generation():
    """测试PPT生成"""
    logger.info("=== 测试PPT生成 ===")

    try:
        # 准备上下文
        context = PresentationContext()

        # 加载CSV数据
        csv_data = load_csv_data()
        if csv_data is None:
            return False

        # 添加数据到上下文
        context.add_dataset("supply_trans_data", csv_data)

        # 添加变量
        context.add_variable("Temporal_Start_Year", "2020")
        context.add_variable("Temporal_End_Year", "2022")
        context.add_variable("Geo_City_Name", "Beijing")
        context.add_variable("Geo_Block_Name", "Liangxiang")
        context.add_variable("Seg_SupplyDemand_Core_Area", "80-100")
        context.add_variable("Seg_SupplyDemand_Upgrade_Area", "140-160")

        # 使用新模板生成PPT
        template_id = "T01_Supply_Trans_Bar"
        output_file = "output/test_new_system.pptx"

        engine = PPTGenerationEngine(output_file)

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

    # 测试PPT生成
    if not test_ppt_generation():
        logger.error("PPT生成测试失败")
        return

    logger.success("所有测试通过！")


if __name__ == "__main__":
    main()
