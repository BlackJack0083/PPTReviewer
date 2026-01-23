# test_all_templates.py
"""
完整测试所有 PPT 模板
测试所有表、所有block、所有模板ID是否能正常工作
"""
import traceback

from loguru import logger

from core import ContextBuilder, resource_manager
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
        "table": "Shenzhen_new_house",
        "blocks": ["Guangming Subdistrict", "Longgang Central City"],
        "city": "Shenzhen",
    }
]

# 所有模板ID
ALL_TEMPLATES = [
    # ReSlide_01
    "T01_Supply_Trans_Bar",
    "T01_Supply_Trans_Line",
    # ReSlide_02
    "T02_Cross_Pivot_Table",
    "T02_Area_Dist_Bar",
    "T02_Area_Dist_Line",
    "T02_Price_Dist_Bar",
    "T02_Price_Dist_Line",
]


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

        # 获取模板元数据
        template_meta = resource_manager.get_template(template_id)
        if not template_meta:
            raise ValueError(f"模板不存在: {template_id}")

        logger.info(f"模板信息: function_key='{template_meta.function_key}'")

        # 初始化DataProvider
        provider = RealEstateDataProvider(
            config["city"], block, start_year, end_year, config["table"]
        )

        # 使用 ContextBuilder 自动构建 Context
        context = ContextBuilder.build_context(
            template_meta=template_meta,
            provider=provider,
            city=config["city"],
            block=block,
            start_year=start_year,
            end_year=end_year,
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
