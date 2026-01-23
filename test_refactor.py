#!/usr/bin/env python3
"""
测试重构后的架构
验证 function_key 映射和 ContextBuilder 是否正常工作
"""
import sys
from loguru import logger

from core import ContextBuilder, resource_manager
from core.data_provider import RealEstateDataProvider


def test_function_dispatcher():
    """测试 execute_by_function_key 方法"""
    logger.info("=" * 80)
    logger.info("测试 1: execute_by_function_key 方法")
    logger.info("=" * 80)

    # 初始化 provider
    provider = RealEstateDataProvider(
        city="Beijing",
        block="Beiqijia",
        start_year="2020",
        end_year="2022",
        table_name="Beijing_new_house"
    )

    # 测试所有 function_key
    test_cases = [
        {
            "function_key": "Supply-Transaction Unit Statistic",
            "params": {"area_range_size": 20},
            "expected_data_keys": ["supply_trans_data"]
        },
        {
            "function_key": "Area x Price Cross Pivot",
            "params": {"area_step": 20, "price_step": 5},
            "expected_data_keys": ["cross_analysis_data"]
        },
        {
            "function_key": "Area Segment Distribution",
            "params": {"step": 20},
            "expected_data_keys": ["newhouse_area_dist_data"]
        },
        {
            "function_key": "Price Segment Distribution",
            "params": {"price_range_size": 1},
            "expected_data_keys": ["newhouse_price_dist_data"]
        },
    ]

    for i, test_case in enumerate(test_cases, 1):
        logger.info(f"\n测试 {i}: {test_case['function_key']}")
        logger.info(f"参数: {test_case['params']}")

        try:
            df, conclusion_vars = provider.execute_by_function_key(
                test_case["function_key"],
                **test_case["params"]
            )
            logger.success(f"✓ 成功! 数据形状: {df.shape}, 结论变量数: {len(conclusion_vars)}")
        except Exception as e:
            logger.error(f"✗ 失败: {e}")
            return False

    logger.success("\n" + "=" * 80)
    logger.success("测试 1 通过!")
    logger.success("=" * 80)
    return True


def test_context_builder():
    """测试 ContextBuilder"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 2: ContextBuilder")
    logger.info("=" * 80)

    # 加载资源
    resource_manager.load_all()

    # 测试模板
    test_templates = [
        "T01_Supply_Trans_Bar",
        "T02_Cross_Pivot_Table",
        "T02_Area_Dist_Bar",
        "T02_Price_Dist_Bar",
    ]

    for template_id in test_templates:
        logger.info(f"\n测试模板: {template_id}")

        try:
            # 获取模板元数据
            template_meta = resource_manager.get_template(template_id)
            if not template_meta:
                logger.error(f"✗ 模板不存在: {template_id}")
                return False

            logger.info(f"function_key: {template_meta.function_key}")

            # 初始化 provider
            provider = RealEstateDataProvider(
                city="Beijing",
                block="Beiqijia",
                start_year="2020",
                end_year="2022",
                table_name="Beijing_new_house"
            )

            # 使用 ContextBuilder 构建上下文
            context = ContextBuilder.build_context(
                template_meta=template_meta,
                provider=provider,
                city="Beijing",
                block="Beiqijia",
                start_year="2020",
                end_year="2022"
            )

            logger.success(
                f"✓ 成功! 数据集: {list(context._datasets.keys())}, "
                f"变量数: {len(context._variables)}"
            )

        except Exception as e:
            logger.error(f"✗ 失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    logger.success("\n" + "=" * 80)
    logger.success("测试 2 通过!")
    logger.success("=" * 80)
    return True


def test_invalid_function_key():
    """测试无效的 function_key"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 3: 无效的 function_key 处理")
    logger.info("=" * 80)

    provider = RealEstateDataProvider(
        city="Beijing",
        block="Beiqijia",
        start_year="2020",
        end_year="2022",
        table_name="Beijing_new_house"
    )

    try:
        provider.execute_by_function_key("Invalid Function Key")
        logger.error("✗ 应该抛出 ValueError，但没有")
        return False
    except ValueError as e:
        if "未知的 function_key" in str(e):
            logger.success(f"✓ 正确抛出 ValueError: {e}")
        else:
            logger.error(f"✗ 错误消息不正确: {e}")
            return False
    except Exception as e:
        logger.error(f"✗ 抛出了错误的异常类型: {type(e).__name__}: {e}")
        return False

    logger.success("\n" + "=" * 80)
    logger.success("测试 3 通过!")
    logger.success("=" * 80)
    return True


if __name__ == "__main__":
    logger.add("logs/test_refactor.log", rotation="10 MB")

    all_passed = True

    # 运行测试
    all_passed &= test_function_dispatcher()
    all_passed &= test_context_builder()
    all_passed &= test_invalid_function_key()

    # 总结
    logger.info("\n" + "#" * 80)
    if all_passed:
        logger.success("所有测试通过!")
        logger.success("#" * 80)
        sys.exit(0)
    else:
        logger.error("部分测试失败!")
        logger.error("#" * 80)
        sys.exit(1)
