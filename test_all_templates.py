# test_all_templates.py
"""
完整测试所有 PPT 模板
测试所有表、所有block、所有模板ID是否能正常工作
"""
import traceback

from loguru import logger

from core import resource_manager
from core.context import PresentationContext
from core.data_provider import RealEstateDataProvider
from engine import PPTGenerationEngine

# 测试数据配置
TEST_CONFIGS = [
    {
        "table": "Beijing_new_house",
        "blocks": ["Liangxiang", "Yongfeng", "Beiqijia"],
        "city": "Beijing",
    },
    {
        "table": "Guangzhou_new_house",
        "blocks": ["Yonghe", "Zhongxin Town"],
        "city": "Guangzhou",
    },
    {
        "table": "Guangzhou_resale_house",
        "blocks": ["Old Town", "Qifu New Village"],
        "city": "Guangzhou",
    },
    {
        "table": "Shenzhen_new_house",
        "blocks": ["Guangming Subdistrict", "Longgang Central City"],
        "city": "Shenzhen",
    },
    {
        "table": "Shenzhen_resale_house",
        "blocks": ["Buji New Town", "Nanshan CBE"],
        "city": "Shenzhen",
    },
]

# 所有模板ID
ALL_TEMPLATES = [
    # ReSlide_01
    # "T01_Supply_Trans_Bar",
    # "T01_Supply_Trans_Line",
    # ReSlide_02
    # 打不开
    # "T02_Cross_Pivot_Bar",
    "T02_Cross_Pivot_Table",
    "T02_Area_Dist_Bar",
    "T02_Area_Dist_Table",
    "T02_Price_Dist_Bar",
    "T02_Price_Dist_Line",
    # ReSlide_03
    # 打不开
    # "T03_Resale_Area_Dist_Bar",
    # "T03_Resale_Area_Dist_Line",
    # "T03_Resale_Area_Dist_Table",
    # "T03_Resale_Price_Dist_Bar",
    # "T03_Resale_Price_Dist_Line",
    # "T03_Resale_Price_Dist_Table",
    # ReSlide_04
    # 缺结论
    # "T04_Historical_Capacity_Bar",
    # "T04_Historical_Capacity_Line",
    # "T04_Historical_Capacity_Table",
    # "T04_Annual_Supply_Demand_Bar",
    # "T04_Annual_Supply_Demand_Line",
    # "T04_Supply_Trans_Area_Bar",
    # "T04_Supply_Trans_Area_Line",
    # "T04_Supply_Trans_Area_Table",
]


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
            provider.get_supply_transaction_stats_with_conclusion()
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
                provider.get_area_price_cross_stats_with_conclusion()
            )
            context.add_dataset("cross_analysis_data", df_cross)
            for key, value in cross_conclusion.items():
                context.add_variable(key, value)

        elif function == "Area":
            logger.info("准备 T02 数据: 面积分布")
            df_area, area_conclusion = provider.get_area_distribution_with_conclusion()
            context.add_dataset("newhouse_area_dist_data", df_area)
            for key, value in area_conclusion.items():
                context.add_variable(key, value)

        elif function == "Price":
            logger.info("准备 T02 数据: 价格分布")
            df_price, price_conclusion = (
                provider.get_price_distribution_with_conclusion()
            )
            context.add_dataset("newhouse_price_dist_data", df_price)
            for key, value in price_conclusion.items():
                context.add_variable(key, value)

    elif template_type == "T03":
        # ReSlide_03: Resale-House Cross-Structure Analysis (已注释，暂不使用)
        pass

    elif template_type == "T04":
        # ReSlide_04: New-House Market Capacity Analysis (已注释，暂不使用)
        pass

    return context


def test_single_template(template_id, config, block, start_year, end_year):
    """
    测试单个模板

    Args:
        template_id: 模板ID
        config: 表配置
        block: 板块名
        start_year: 起始年份
        end_year: 结束年份

    Returns:
        dict: 测试结果
    """
    result = {
        "template_id": template_id,
        "table": config["table"],
        "block": block,
        "success": False,
        "error": None,
    }

    try:
        logger.info(f"\n{'='*60}")
        logger.info(f"测试模板: {template_id}")
        logger.info(f"表: {config['table']}, 板块: {block}")
        logger.info(f"{'='*60}")

        # 初始化DataProvider
        provider = RealEstateDataProvider(
            config["city"], block, start_year, end_year, config["table"]
        )

        # 准备Context
        context = prepare_context_for_template(
            template_id, provider, start_year, end_year, config["city"], block
        )

        # 生成PPT
        output_file = f"output/test_{template_id}_{config['table']}_{block.replace(' ', '_')}.pptx"
        engine = PPTGenerationEngine(output_file)

        engine.generate_multiple_slides(
            [{"template_id": template_id, "context": context}]
        )

        logger.success(f"✓ 模板 {template_id} 测试成功！")
        logger.success(f"✓ 输出文件: {output_file}")

        result["success"] = True

    except Exception as e:
        logger.error(f"✗ 模板 {template_id} 测试失败: {e}")
        logger.error(traceback.format_exc())
        result["error"] = str(e)

    return result


def test_specific_template(template_id):
    """
    测试特定模板在所有表和板块上的表现

    Args:
        template_id: 要测试的模板ID
    """
    logger.info(f"\n{'#'*80}")
    logger.info(f"开始测试模板: {template_id}")
    logger.info(f"{'#'*80}")

    start_year = "2020"
    end_year = "2022"

    results = []
    success_count = 0
    fail_count = 0

    for config in TEST_CONFIGS:
        for block in config["blocks"]:
            result = test_single_template(
                template_id, config, block, start_year, end_year
            )
            results.append(result)

            if result["success"]:
                success_count += 1
            else:
                fail_count += 1

    # 打印总结
    logger.info(f"\n{'='*80}")
    logger.info(f"模板 {template_id} 测试总结")
    logger.info(f"{'='*80}")
    logger.info(f"总测试数: {len(results)}")
    logger.success(f"成功: {success_count}")
    logger.error(f"失败: {fail_count}")

    if fail_count > 0:
        logger.error("\n失败的测试:")
        for result in results:
            if not result["success"]:
                logger.error(
                    f"  - {result['table']}/{result['block']}: {result['error']}"
                )

    return results


def test_all_templates_sample():
    """
    快速测试：每个模板类型只测试一个表和一个板块
    """
    logger.info(f"\n{'#'*80}")
    logger.info("快速测试模式：每个模板测试一个样本")
    logger.info(f"{'#'*80}")

    start_year = "2020"
    end_year = "2022"

    # 选择第一个表和第一个板块作为样本
    sample_config = TEST_CONFIGS[0]  # Beijing_new_house
    sample_block = sample_config["blocks"][0]  # Liangxiang

    results = []
    success_count = 0
    fail_count = 0

    for template_id in ALL_TEMPLATES:
        result = test_single_template(
            template_id, sample_config, sample_block, start_year, end_year
        )
        results.append(result)

        if result["success"]:
            success_count += 1
        else:
            fail_count += 1

    # 打印总结
    logger.info(f"\n{'='*80}")
    logger.info("快速测试总结")
    logger.info(f"{'='*80}")
    logger.info(f"总测试数: {len(results)}")
    logger.success(f"成功: {success_count}")
    logger.error(f"失败: {fail_count}")

    if fail_count > 0:
        logger.error("\n失败的模板:")
        for result in results:
            if not result["success"]:
                logger.error(f"  - {result['template_id']}: {result['error']}")

    return results


def test_specific_table(table_name):
    """
    测试特定表的所有板块和所有模板

    Args:
        table_name: 表名（如 "Beijing_new_house"）
    """
    logger.info(f"\n{'#'*80}")
    logger.info(f"开始测试表: {table_name}")
    logger.info(f"{'#'*80}")

    # 找到对应的配置
    config = None
    for c in TEST_CONFIGS:
        if c["table"] == table_name:
            config = c
            break

    if not config:
        logger.error(f"未找到表 {table_name} 的配置")
        return []

    start_year = "2020"
    end_year = "2022"

    results = []
    success_count = 0
    fail_count = 0

    for block in config["blocks"]:
        for template_id in ALL_TEMPLATES:
            result = test_single_template(
                template_id, config, block, start_year, end_year
            )
            results.append(result)

            if result["success"]:
                success_count += 1
            else:
                fail_count += 1

    # 打印总结
    logger.info(f"\n{'='*80}")
    logger.info(f"表 {table_name} 测试总结")
    logger.info(f"{'='*80}")
    logger.info(f"总测试数: {len(results)}")
    logger.success(f"成功: {success_count}")
    logger.error(f"失败: {fail_count}")

    return results


def generate_test_report(results, report_name="test_report.txt"):
    """
    生成测试报告

    Args:
        results: 测试结果列表
        report_name: 报告文件名
    """
    with open(f"output/{report_name}", "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("PPT 模板测试报告\n")
        f.write("=" * 80 + "\n\n")

        total = len(results)
        success = sum(1 for r in results if r["success"])
        fail = total - success

        f.write(f"总测试数: {total}\n")
        f.write(f"成功: {success}\n")
        f.write(f"失败: {fail}\n")
        f.write(f"成功率: {success/total*100:.1f}%\n\n")

        if fail > 0:
            f.write("\n失败的测试:\n")
            f.write("-" * 80 + "\n")
            for result in results:
                if not result["success"]:
                    f.write(f"模板: {result['template_id']}\n")
                    f.write(f"表: {result['table']}, 板块: {result['block']}\n")
                    f.write(f"错误: {result['error']}\n\n")

        f.write("\n详细的测试结果:\n")
        f.write("-" * 80 + "\n")
        for result in results:
            status = "✓" if result["success"] else "✗"
            f.write(
                f"{status} {result['template_id']} - {result['table']}/{result['block']}\n"
            )

    logger.info(f"\n✓ 测试报告已生成: output/{report_name}")


if __name__ == "__main__":
    # 配置日志
    logger.add("logs/test_all_templates.log", rotation="10 MB")

    # 加载资源
    resource_manager.load_all()

    print("\n" + "=" * 80)
    print("PPT 模板完整测试系统")
    print("=" * 80)
    print("\n请选择测试模式:")
    print("1. 快速测试 - 每个模板测试一个样本（推荐）")
    print("2. 完整测试 - 所有表、所有板块、所有模板")
    print("3. 测试特定模板")
    print("4. 测试特定表")
    print("=" * 80)

    choice = input("\n请输入选项 (1-4): ").strip()

    if choice == "1":
        logger.info("\n开始快速测试...")
        results = test_all_templates_sample()
        generate_test_report(results, "quick_test_report.txt")

    elif choice == "2":
        logger.info("\n开始完整测试（这可能需要较长时间）...")
        all_results = []

        for config in TEST_CONFIGS:
            for block in config["blocks"]:
                for template_id in ALL_TEMPLATES:
                    result = test_single_template(
                        template_id, config, block, "2020", "2022"
                    )
                    all_results.append(result)

        generate_test_report(all_results, "full_test_report.txt")

    elif choice == "3":
        template_id = input("\n请输入模板ID (如 T01_Supply_Trans_Bar): ").strip()
        if template_id in ALL_TEMPLATES:
            results = test_specific_template(template_id)
            generate_test_report(results, f"test_{template_id}_report.txt")
        else:
            logger.error(f"无效的模板ID: {template_id}")
            logger.info(f"可用的模板ID: {', '.join(ALL_TEMPLATES[:5])}...")

    elif choice == "4":
        print("\n可用的表:")
        for i, config in enumerate(TEST_CONFIGS, 1):
            print(f"{i}. {config['table']}")

        table_choice = input("\n请输入表名 (如 Beijing_new_house): ").strip()
        results = test_specific_table(table_choice)
        generate_test_report(results, f"test_{table_choice}_report.txt")

    else:
        logger.error("无效的选项")

    logger.info("\n测试完成！")
    logger.info("请查看 output/ 目录生成的 PPT 文件和测试报告")
