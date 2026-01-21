# test_single.py
"""
单例测试脚本 - 测试单个模板在特定表和板块上的表现
用于快速验证特定配置是否正常工作
"""
import traceback

from loguru import logger

from core import resource_manager
from core.context import PresentationContext
from core.data_provider import RealEstateDataProvider
from engine import PPTGenerationEngine


def prepare_context_for_template(
    template_id, provider, start_year, end_year, city, block
):
    """
    根据模板ID准备对应的Context

    Args:
        template_id: 模板ID
        provider: DataProvider实例
        start_year: 起始年份
        end_year: 结束年份
        city: 城市名
        block: 板块名

    Returns:
        PresentationContext: 准备好的上下文
    """
    context = PresentationContext()

    # 添加基础变量
    context.add_variable("Geo_City_Name", city)
    context.add_variable("Geo_Block_Name", block)
    context.add_variable("Temporal_Start_Year", start_year)
    context.add_variable("Temporal_End_Year", end_year)

    # 根据模板类型准备数据
    template_type = template_id.split("_")[0]  # T01, T02, T03, T04

    if template_type == "T01":
        # ReSlide_01: Block Area Segment Distribution
        logger.info("准备 T01 数据: 供需统计")
        df_supply, supply_conclusion = (
            provider.get_supply_transaction_stats_with_conclusion(area_range_size=20)
        )
        context.add_dataset("supply_trans_data", df_supply)
        for key, value in supply_conclusion.items():
            context.add_variable(key, value)

    elif template_type == "T02":
        # ReSlide_02: New-House Cross-Structure Analysis
        function = template_id.split("_")[1]  # Cross, Area, Price

        if function == "Cross":
            logger.info("准备 T02 数据: 交叉分析")
            df_cross, cross_conclusion = (
                provider.get_area_price_cross_stats_with_conclusion(
                    area_step=20, price_step=5
                )
            )
            context.add_dataset("cross_analysis_data", df_cross)
            for key, value in cross_conclusion.items():
                context.add_variable(key, value)

        elif function == "Area":
            logger.info("准备 T02 数据: 面积分布")
            df_area, area_conclusion = (
                provider.get_newhouse_area_distribution_with_conclusion(step=20)
            )
            context.add_dataset("newhouse_area_dist_data", df_area)
            for key, value in area_conclusion.items():
                context.add_variable(key, value)

        elif function == "Price":
            logger.info("准备 T02 数据: 价格分布")
            df_price, price_conclusion = (
                provider.get_newhouse_price_distribution_with_conclusion(
                    price_range_size=1
                )
            )
            context.add_dataset("newhouse_price_dist_data", df_price)
            for key, value in price_conclusion.items():
                context.add_variable(key, value)

    elif template_type == "T03":
        # ReSlide_03: Resale-House Cross-Structure Analysis
        pass

    elif template_type == "T04":
        # ReSlide_04: New-House Market Capacity Analysis
        pass

    return context


def test_single_case(
    template_id: str,
    start_year: str,
    end_year: str,
    table_config: dict,
):
    """
    测试单个案例

    Args:
        template_id: 模板ID (如 "T02_Cross_Pivot_Table")
        start_year: 起始年份 (如 "2020")
        end_year: 结束年份 (如 "2022")
        table_config: 表配置字典，包含:
            {
                "table": "Beijing_new_house",
                "blocks": ["Beiqijia"],
                "city": "Beijing",
            }
    """
    logger.info(f"\n{'='*80}")
    logger.info("单例测试")
    logger.info(f"{'='*80}")
    logger.info(f"模板ID: {template_id}")
    logger.info(f"时间范围: {start_year} - {end_year}")
    logger.info(f"表: {table_config['table']}")
    logger.info(f"城市: {table_config['city']}")
    logger.info(f"板块: {table_config['blocks']}")
    logger.info(f"{'='*80}\n")

    try:
        # 遍历所有板块
        for block in table_config["blocks"]:
            logger.info(f"\n{'─'*60}")
            logger.info(f"测试板块: {block}")
            logger.info(f"{'─'*60}")

            # 初始化DataProvider
            provider = RealEstateDataProvider(
                table_config["city"], block, start_year, end_year, table_config["table"]
            )

            # 准备Context
            context = prepare_context_for_template(
                template_id, provider, start_year, end_year, table_config["city"], block
            )

            # 生成PPT
            output_file = f"output/single_{template_id}_{table_config['table']}_{block.replace(' ', '_')}.pptx"
            logger.info(f"输出文件: {output_file}")

            engine = PPTGenerationEngine(output_file)
            engine.generate_multiple_slides(
                [{"template_id": template_id, "context": context}]
            )

            logger.success(f"✓ 板块 {block} 测试成功！")
            logger.success(f"✓ 输出文件: {output_file}")

    except Exception as e:
        logger.error(f"✗ 测试失败: {e}")
        logger.error(traceback.format_exc())
        return False

    logger.success(f"\n{'='*80}")
    logger.success("单例测试完成！")
    logger.success(f"{'='*80}")
    return True


if __name__ == "__main__":
    # 配置日志
    logger.add("logs/test_single.log", rotation="10 MB")

    # 加载资源
    resource_manager.load_all()

    # ========== 单例测试配置 ==========
    # 在这里修改你的测试参数

    # 1. 设置模板ID
    TEMPLATE_ID = "T02_Cross_Pivot_Table"

    # 2. 设置时间范围
    START_YEAR = "2020"
    END_YEAR = "2022"

    # 3. 设置表配置
    TABLE_CONFIG = {
        "table": "Beijing_new_house",
        "blocks": ["Beiqijia"],
        "city": "Beijing",
    }

    # ========== 执行测试 ==========
    logger.info("开始单例测试...")
    success = test_single_case(
        template_id=TEMPLATE_ID,
        start_year=START_YEAR,
        end_year=END_YEAR,
        table_config=TABLE_CONFIG,
    )

    if success:
        logger.success("\n✓ 所有测试通过！")
        logger.info("请查看 output/ 目录生成的 PPT 文件")
    else:
        logger.error("\n✗ 测试失败，请查看日志")
