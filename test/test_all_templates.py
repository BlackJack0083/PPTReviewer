# test_all_templates.py
"""
批量测试 PPT 模板。
支持按模板、按 block 或按主题分组执行回归测试。
"""

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from loguru import logger

from core import ContextBuilder, resource_manager
from core.data_provider import RealEstateDataProvider
from engine import PPTGenerationEngine
from engine.ppt_engine import SlideTask

# 测试配置
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
    },
    {
        "table": "Guangzhou_resale_house",
        "blocks": ["Old Town"],
        "city": "Guangzhou",
    },
]

# 测试配置 ID
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
    "T02_Double_Price_Dist_Line",
    "T02_Double_Price_Dist_Bar",
    # ReSlide_03
    "T03_Cross_Pivot_Table",
    "T03_Area_Dist_Bar",
    "T03_Area_Dist_Line",
    "T03_Price_Dist_Bar",
    "T03_Price_Dist_Line",
    "T03_Double_Price_Dist_Line",
    "T03_Double_Price_Dist_Bar",
    # ReSlide_04
    "T04_Annual_Supply_Demand_Bar",
    "T04_Annual_Supply_Demand_Line",
    "T04_Supply_Transaction_Area_Bar",
    "T04_Supply_Transaction_Area_Line",
    # ReSlide_05
    "T05_Resale_Summary_Table",
    "T05_Resale_Summary_Table_Alt",
    "T05_Resale_Double_Bar",
    "T05_Resale_Double_Line",
    "T05_Resale_Count_Bar",
    "T05_Resale_Price_Bar",
    "T05_Resale_Count_Line",
    "T05_Resale_Price_Line",
    # ReSlide_07
    "T07_Price_Share_Pie",
    "T07_Price_Share_Bar",
    # ReSlide_08
    "T08_Area_Share_Pie",
    "T08_Area_Share_Bar",
    # ReSlide_09
    "T09_Monthly_Supply_Bar",
    "T09_Monthly_Supply_Line",
    # ReSlide_10
    "T10_Price_Growth_Bar",
    "T10_Price_Growth_Line",
    # ReSlide_11
    "T11_Supply_Ratio_Bar",
    "T11_Supply_Ratio_Line",
    # ReSlide_12
    "T12_Area_Pivot_Table",
    "T12_Area_Pivot_Stacked_Bar",
]

T05_TEMPLATES = [
    "T05_Resale_Summary_Table",
    "T05_Resale_Summary_Table_Alt",
    "T05_Resale_Double_Bar",
    "T05_Resale_Double_Line",
    "T05_Resale_Count_Bar",
    "T05_Resale_Price_Bar",
    "T05_Resale_Count_Line",
    "T05_Resale_Price_Line",
]

T07_T08_TEMPLATES = [
    "T07_Price_Share_Pie",
    "T07_Price_Share_Bar",
    "T08_Area_Share_Pie",
    "T08_Area_Share_Bar",
]

T09_T10_TEMPLATES = [
    "T09_Monthly_Supply_Bar",
    "T09_Monthly_Supply_Line",
    "T10_Price_Growth_Bar",
    "T10_Price_Growth_Line",
]

T11_T12_TEMPLATES = [
    "T11_Supply_Ratio_Bar",
    "T11_Supply_Ratio_Line",
    "T12_Area_Pivot_Table",
    "T12_Area_Pivot_Stacked_Bar",
]


def get_applicable_configs(template_id):
    """Return matching table configs for a given template."""
    if template_id.startswith("T03_") or template_id.startswith("T05_"):
        return [
            config for config in TEST_CONFIGS if config["table"] == "Guangzhou_resale_house"
        ]
    return [
        config for config in TEST_CONFIGS if config["table"] != "Guangzhou_resale_house"
    ]


def test_single_template(template_id, config, block, start_year, end_year):
    """输出测试汇总。"""
    result = {
        "template_id": template_id,
        "table": config["table"],
        "block": block,
        "success": False,
        "error": None,
    }

    try:
        logger.info(f"\n{'=' * 60}")
        logger.info(f"测试指定模板: {template_id}")
        logger.info(f"表: {config['table']}, 板块: {block}")
        logger.info(f"{'=' * 60}")

        template_meta = resource_manager.get_template(template_id)
        if not template_meta:
            raise ValueError(f"未找到模板配置: {template_id}")

        logger.info(f"模板函数键: function_key='{template_meta.function_key}'")

        provider = RealEstateDataProvider(
            config["city"], block, start_year, end_year, config["table"]
        )

        context = ContextBuilder.build_context(
            template_meta=template_meta,
            provider=provider,
            city=config["city"],
            block=block,
            start_year=start_year,
            end_year=end_year,
        )

        output_file = (
            f"output/test_{template_id}_{config['table']}_{block.replace(' ', '_')}.pptx"
        )
        engine = PPTGenerationEngine(output_file)

        Path("output").mkdir(parents=True, exist_ok=True)
        engine.generate_multiple_slides(
            [SlideTask(template_id=template_id, context=context)]
        )

        logger.success(f"模板 {template_id} 测试通过")
        logger.success(f"输出文件: {output_file}")
        result["success"] = True

    except Exception as exc:
        logger.error(f"模板 {template_id} 测试失败: {exc}")
        logger.error(traceback.format_exc())
        result["error"] = str(exc)

    return result


def _log_test_summary(title, results):
    """输出测试汇总。"""
    success_count = sum(1 for result in results if result["success"])
    fail_count = len(results) - success_count

    logger.info(f"\n{'=' * 80}")
    logger.info(title)
    logger.info(f"{'=' * 80}")
    logger.info(f"总数: {len(results)}")
    logger.success(f"成功: {success_count}")
    logger.error(f"失败: {fail_count}")

    if fail_count > 0:
        logger.error("\n失败明细:")
        for result in results:
            if not result["success"]:
                logger.error(
                    f"  - {result['template_id']} / {result['table']} / {result['block']}: {result['error']}"
                )


def test_specific_template(template_id):
    """测试指定模板在适用配置下的全部组合。"""
    logger.info(f"\n{'#' * 80}")
    logger.info(f"测试指定模板: {template_id}")
    logger.info(f"{'#' * 80}")

    start_year = "2020"
    end_year = "2022"
    results = []

    for config in get_applicable_configs(template_id):
        for block in config["blocks"]:
            results.append(
                test_single_template(template_id, config, block, start_year, end_year)
            )

    _log_test_summary(f"模板 {template_id} 测试汇总", results)
    return results


def test_all_templates_sample():
    """为每个模板抽取一个样例配置做快速测试。"""
    logger.info(f"\n{'#' * 80}")
    logger.info("开始执行样例模板快速测试")
    logger.info(f"{'#' * 80}")

    start_year = "2020"
    end_year = "2022"
    results = []

    for template_id in ALL_TEMPLATES:
        sample_config = get_applicable_configs(template_id)[0]
        sample_block = sample_config["blocks"][0]
        results.append(
            test_single_template(
                template_id,
                sample_config,
                sample_block,
                start_year,
                end_year,
            )
        )

    _log_test_summary("样例测试汇总", results)
    return results


def _run_template_group_test(group_title, template_ids):
    """输出测试汇总。"""
    logger.info(f"\n{'#' * 80}")
    logger.info(f"开始测试{group_title}")
    logger.info(f"{'#' * 80}")

    start_year = "2020"
    end_year = "2022"
    results = []

    for template_id in template_ids:
        for config in get_applicable_configs(template_id):
            for block in config["blocks"]:
                results.append(
                    test_single_template(
                        template_id,
                        config,
                        block,
                        start_year,
                        end_year,
                    )
                )

    _log_test_summary(f"{group_title}测试汇总", results)
    return results


def test_theme5_templates():
    """测试主题5模板。"""
    return _run_template_group_test("主题5模板", T05_TEMPLATES)


def test_theme7_8_templates():
    """测试主题7/8模板。"""
    return _run_template_group_test("主题7/8模板", T07_T08_TEMPLATES)


def test_theme9_10_templates():
    """测试主题9/10模板。"""
    return _run_template_group_test("主题9/10模板", T09_T10_TEMPLATES)


def test_theme11_12_templates():
    """测试主题11/12模板。"""
    return _run_template_group_test("主题11/12模板", T11_T12_TEMPLATES)


def test_specific_table(table_name):
    """测试指定数据表对应的所有模板。"""
    logger.info(f"\n{'#' * 80}")
    logger.info(f"测试指定数据表: {table_name}")
    logger.info(f"{'#' * 80}")

    config = next((item for item in TEST_CONFIGS if item["table"] == table_name), None)
    if not config:
        logger.error(f"未找到数据表配置: {table_name}")
        return []

    start_year = "2020"
    end_year = "2022"
    results = []

    applicable_template_ids = [
        template_id
        for template_id in ALL_TEMPLATES
        if config in get_applicable_configs(template_id)
    ]
    for block in config["blocks"]:
        for template_id in applicable_template_ids:
            results.append(
                test_single_template(template_id, config, block, start_year, end_year)
            )

    _log_test_summary(f"表 {table_name} 测试汇总", results)
    return results


def generate_test_report(results, report_name="test_report.txt"):
    """输出测试汇总。"""
    Path("output").mkdir(parents=True, exist_ok=True)
    with open(f"output/{report_name}", "w", encoding="utf-8") as file:
        file.write("=" * 80 + "\n")
        file.write("PPT 模板测试报告\n")
        file.write("=" * 80 + "\n\n")

        total = len(results)
        success = sum(1 for result in results if result["success"])
        fail = total - success
        success_rate = (success / total * 100) if total else 0.0

        file.write(f"总数: {total}\n")
        file.write(f"成功: {success}\n")
        file.write(f"失败: {fail}\n")
        file.write(f"成功率: {success_rate:.1f}%\n\n")

        if fail > 0:
            file.write("全部结果:\n")
            file.write("-" * 80 + "\n")
            for result in results:
                if not result["success"]:
                    file.write(f"模板: {result['template_id']}\n")
                    file.write(
                        f"表: {result['table']}, 板块: {result['block']}\n"
                    )
                    file.write(f"错误: {result['error']}\n\n")

        file.write("全部结果:\n")
        file.write("-" * 80 + "\n")
        for result in results:
            status = "成功" if result["success"] else "失败"
            file.write(
                f"{status} {result['template_id']} - {result['table']}/{result['block']}\n"
            )

    logger.info(f"\n测试报告已生成: output/{report_name}")


if __name__ == "__main__":
    logger.add("logs/test_all_templates.log", rotation="10 MB")
    resource_manager.load_all()

    print("\n" + "=" * 80)
    print("PPT 模板测试工具")
    print("=" * 80)
    print("\n请选择测试模式:")
    print("1. 快速测试 - 每个模板只跑一个样例")
    print("2. 全量测试 - 运行所有模板与全部配置")
    print("3. 测试指定模板")
    print("4. 测试指定表")
    print("5. 测试主题5")
    print("6. 测试主题7/8")
    print("7. 测试主题9/10")
    print("8. 测试主题11/12")
    print("=" * 80)

    choice = input("\n请输入选项 (1-8): ").strip()

    if choice == "1":
        results = test_all_templates_sample()
        generate_test_report(results, "quick_test_report.txt")
    elif choice == "2":
        logger.info("\n开始执行全量模板测试...")
        all_results = []
        for config in TEST_CONFIGS:
            applicable_template_ids = [
                template_id
                for template_id in ALL_TEMPLATES
                if config in get_applicable_configs(template_id)
            ]
            for block in config["blocks"]:
                for template_id in applicable_template_ids:
                    all_results.append(
                        test_single_template(
                            template_id,
                            config,
                            block,
                            "2020",
                            "2022",
                        )
                    )
        generate_test_report(all_results, "full_test_report.txt")
    elif choice == "3":
        template_id = input("\n请输入模板ID (如 T01_Supply_Trans_Bar): ").strip()
        if template_id in ALL_TEMPLATES:
            results = test_specific_template(template_id)
            generate_test_report(results, f"test_{template_id}_report.txt")
        else:
            logger.error(f"无效的模板ID: {template_id}")
            logger.info(f"示例模板ID: {', '.join(ALL_TEMPLATES[:5])}...")
    elif choice == "4":
        print("\n可选数据表:")
        for index, config in enumerate(TEST_CONFIGS, 1):
            print(f"{index}. {config['table']}")
        table_choice = input("\n请输入表名 (如 Beijing_new_house): ").strip()
        results = test_specific_table(table_choice)
        generate_test_report(results, f"test_{table_choice}_report.txt")
    elif choice == "5":
        results = test_theme5_templates()
        generate_test_report(results, "test_theme5_report.txt")
    elif choice == "6":
        results = test_theme7_8_templates()
        generate_test_report(results, "test_theme7_8_report.txt")
    elif choice == "7":
        results = test_theme9_10_templates()
        generate_test_report(results, "test_theme9_10_report.txt")
    elif choice == "8":
        results = test_theme11_12_templates()
        generate_test_report(results, "test_theme11_12_report.txt")
    else:
        logger.error("无效选项")

    logger.info("\n测试完成")
    logger.info("可到 output/ 目录查看生成的 PPT 和测试报告")
