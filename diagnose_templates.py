# diagnose_templates.py
"""
模板诊断工具 - 快速识别所有模板问题
"""
from loguru import logger

from core import resource_manager
from core.context import PresentationContext
from core.data_provider import RealEstateDataProvider
from engine import PPTGenerationEngine


def check_text_pattern_coverage():
    """检查text_pattern.yaml中所有主题和功能的summary数量"""
    import yaml

    logger.info("=" * 80)
    logger.info("检查 text_pattern.yaml 覆盖率")
    logger.info("=" * 80)

    with open("config/templates/text_pattern.yaml", encoding="utf-8") as f:
        patterns = yaml.safe_load(f)

    for theme, content in patterns.items():
        logger.info(f"\n主题: {theme}")
        if isinstance(content, dict):
            for function, func_content in content.items():
                if isinstance(func_content, dict) and "summaries" in func_content:
                    summaries = func_content["summaries"]
                    logger.info(f"  功能: {function}")
                    logger.info(f"  Summary数量: {len(summaries)}")
                    logger.info(f"  有效索引: 0-{len(summaries)-1}")
                    logger.info(f"  有效summary_item: 1-{len(summaries)}")


def check_template_definitions():
    """检查template_definitions.yaml中的配置是否正确"""
    import yaml

    logger.info("\n" + "=" * 80)
    logger.info("检查 template_definitions.yaml 配置")
    logger.info("=" * 80)

    with open("config/templates/template_definitions.yaml", encoding="utf-8") as f:
        templates = yaml.safe_load(f)

    errors = []

    for template in templates:
        uid = template.get("uid")
        summary_item = template.get("summary_item")

        # 检查summary_item是否有效
        if summary_item and summary_item > 3:
            errors.append(f"{uid}: summary_item={summary_item} 可能超出范围")

        # 检查data_keys
        data_keys = template.get("data_keys", {})
        if not data_keys:
            errors.append(f"{uid}: 缺少 data_keys")

        logger.info(f"\n{uid}:")
        logger.info(f"  theme_key: {template.get('theme_key')}")
        logger.info(f"  function_key: {template.get('function_key')}")
        logger.info(f"  layout_type: {template.get('layout_type')}")
        logger.info(f"  summary_item: {summary_item}")
        logger.info(f"  data_keys: {data_keys}")

    if errors:
        logger.error("\n发现配置错误:")
        for error in errors:
            logger.error(f"  ❌ {error}")
    else:
        logger.success("\n✓ 所有配置检查通过")

    return templates


def test_data_format_output():
    """测试各种DataProvider方法输出的数据格式"""
    logger.info("\n" + "=" * 80)
    logger.info("检查数据格式")
    logger.info("=" * 80)

    resource_manager.load_all()

    # 使用一个简单的测试案例
    provider = RealEstateDataProvider(
        "Shenzhen", "Buji New Town", "2020", "2022", "Shenzhen_new_house"
    )

    # 1. 供需统计
    logger.info("\n1. 供需统计数据格式:")
    df1 = provider.get_supply_transaction_stats(area_range_size=20)
    logger.info(f"   形状: {df1.shape}")
    logger.info(f"   列: {df1.columns.tolist()}")
    logger.info(f"   索引: {df1.index.tolist()}")
    logger.info(f"   数据类型:\n{df1.dtypes}")
    logger.info(f"   数据预览:\n{df1.head()}")

    # 2. 交叉分析
    logger.info("\n2. 交叉分析数据格式:")
    df2 = provider.get_area_price_cross_stats(area_step=20, price_step=1)
    logger.info(f"   形状: {df2.shape}")
    logger.info(f"   列: {df2.columns.tolist()}")
    logger.info(f"   索引: {df2.index.tolist()}")
    logger.info(f"   数据预览:\n{df2.head()}")

    # 3. 面积分布
    logger.info("\n3. 面积分布数据格式:")
    df3 = provider.get_area_distribution_stats(step=20)
    logger.info(f"   形状: {df3.shape}")
    logger.info(f"   列: {df3.columns.tolist()}")
    logger.info(f"   索引名: {df3.index.name}")
    logger.info(f"   数据预览:\n{df3.head()}")

    # 4. 价格分布
    logger.info("\n4. 价格分布数据格式:")
    df4 = provider.get_price_distribution_stats(price_range_size=1)
    logger.info(f"   形状: {df4.shape}")
    logger.info(f"   列: {df4.columns.tolist()}")
    logger.info(f"   索引名: {df4.index.name}")
    logger.info(f"   数据预览:\n{df4.head()}")


def test_single_template_generation(template_id):
    """测试单个模板生成，诊断问题"""
    logger.info("\n" + "=" * 80)
    logger.info(f"诊断模板: {template_id}")
    logger.info("=" * 80)

    resource_manager.load_all()

    # 根据模板类型选择合适的表
    if template_id.startswith("T03"):
        # 二手房模板
        provider = RealEstateDataProvider(
            "Shenzhen", "Buji New Town", "2020", "2022", "Shenzhen_resale_house"
        )
    else:
        # 新房模板
        provider = RealEstateDataProvider(
            "Shenzhen", "Buji New Town", "2020", "2022", "Shenzhen_new_house"
        )

    context = PresentationContext()
    context.add_variable("Geo_City_Name", "Shenzhen")
    context.add_variable("Geo_Block_Name", "Buji New Town")
    context.add_variable("Temporal_Start_Year", "2020")
    context.add_variable("Temporal_End_Year", "2022")

    # 根据模板ID准备相应的数据
    template_type = template_id.split("_")[0]  # T01, T02, T03, T04

    if template_type == "T01":
        # ReSlide_01: 供需统计
        logger.info("  准备数据: 供需统计")
        df_supply, conclusion = provider.get_supply_transaction_stats_with_conclusion(
            area_range_size=20
        )
        context.add_dataset("supply_trans_data", df_supply)
        for key, value in conclusion.items():
            context.add_variable(key, value)
            logger.info(f"  结论变量: {key} = {value}")

    elif template_type == "T02":
        # ReSlide_02: 新房交叉分析
        function = template_id.split("_")[1]  # Cross, Area, Price

        if function == "Cross":
            # 交叉分析数据
            logger.info("  准备数据: 交叉分析")
            df_cross, cross_conclusion = (
                provider.get_area_price_cross_stats_with_conclusion(
                )
            )
            context.add_dataset("cross_analysis_data", df_cross)
            for key, value in cross_conclusion.items():
                context.add_variable(key, value)
                logger.info(f"  结论变量: {key} = {value}")

        elif function == "Area":
            # 面积分布
            logger.info("  准备数据: 面积分布")
            df_area, area_conclusion = (
                provider.get_area_distribution_with_conclusion()
            )
            context.add_dataset("newhouse_area_dist_data", df_area)
            for key, value in area_conclusion.items():
                context.add_variable(key, value)
                logger.info(f"  结论变量: {key} = {value}")

        elif function == "Price":
            # 价格分布
            logger.info("  准备数据: 价格分布")
            df_price, price_conclusion = (
                provider.get_price_distribution_with_conclusion(
                )
            )
            context.add_dataset("newhouse_price_dist_data", df_price)
            for key, value in price_conclusion.items():
                context.add_variable(key, value)
                logger.info(f"  结论变量: {key} = {value}")

    elif template_type == "T03":
        # ReSlide_03: 二手房分析 (已注释，暂不使用)
        pass

    elif template_type == "T04":
        # ReSlide_04: 市场容量 (已注释，暂不使用)
        pass

    # 尝试生成PPT
    try:
        output_file = f"output/diagnose_{template_id}.pptx"
        engine = PPTGenerationEngine(output_file)
        engine.generate_multiple_slides(
            [{"template_id": template_id, "context": context}]
        )
        logger.success(f"✓ {template_id} 生成成功: {output_file}")
        return True
    except Exception as e:
        logger.error(f"✗ {template_id} 生成失败: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return False


def generate_diagnostic_report():
    """生成完整诊断报告"""
    logger.info("=" * 80)
    logger.info("PPT 模板诊断报告")
    logger.info("=" * 80)

    # 1. 检查text_pattern覆盖率
    check_text_pattern_coverage()

    # 2. 检查template_definitions配置
    check_template_definitions()

    # 3. 检查数据格式
    test_data_format_output()

    # 4. 测试几个关键模板
    logger.info("\n" + "=" * 80)
    logger.info("测试关键模板")
    logger.info("=" * 80)

    test_templates = [
        "T01_Supply_Trans_Bar",
        # "T01_Supply_Trans_Line",
        # "T03_Resale_Area_Dist_Table",
        # "T02_Cross_Pivot_Bar",
    ]

    results = {}
    for template_id in test_templates:
        results[template_id] = test_single_template_generation(template_id)

    # 总结
    logger.info("\n" + "=" * 80)
    logger.info("诊断总结")
    logger.info("=" * 80)

    success_count = sum(1 for v in results.values() if v)
    fail_count = len(results) - success_count

    logger.info(f"测试模板数: {len(results)}")
    logger.success(f"成功: {success_count}")
    logger.error(f"失败: {fail_count}")

    if fail_count > 0:
        logger.error("\n失败的模板:")
        for template_id, success in results.items():
            if not success:
                logger.error(f"  - {template_id}")


if __name__ == "__main__":
    logger.add("logs/diagnose_templates.log", rotation="10 MB")

    print("\n" + "=" * 80)
    print("PPT 模板诊断工具")
    print("=" * 80)
    print("\n请选择诊断模式:")
    print("1. 完整诊断报告（推荐）")
    print("2. 只检查text_pattern覆盖")
    print("3. 只检查template_definitions配置")
    print("4. 只检查数据格式")
    print("5. 测试特定模板")
    print("=" * 80)

    choice = input("\n请输入选项 (1-5): ").strip()

    if choice == "1":
        generate_diagnostic_report()
    elif choice == "2":
        check_text_pattern_coverage()
    elif choice == "3":
        check_template_definitions()
    elif choice == "4":
        test_data_format_output()
    elif choice == "5":
        template_id = input("\n请输入模板ID (如 T01_Supply_Trans_Bar): ").strip()
        test_single_template_generation(template_id)
    else:
        logger.error("无效的选项")

    logger.info("\n诊断完成！请查看日志获取详细信息")
