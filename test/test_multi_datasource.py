#!/usr/bin/env python3
"""
测试多数据源功能
验证一页 PPT 中可以包含多个不同的图表
"""
import sys
from loguru import logger

from core import ContextBuilder, resource_manager
from core.data_provider import RealEstateDataProvider
from engine import PPTGenerationEngine


def test_multi_datasource_template():
    """测试多数据源模板"""
    logger.info("=" * 80)
    logger.info("测试多数据源模板")
    logger.info("=" * 80)

    # 加载资源
    resource_manager.load_all()

    # 测试配置
    template_id = "T02_Double_Price_Dist_Line"
    city = "Beijing"
    block = "Beiqijia"
    start_year = "2020"
    end_year = "2022"
    table = "Beijing_new_house"

    try:
        # 1. 获取模板元数据
        template_meta = resource_manager.get_template(template_id)
        if not template_meta:
            logger.error(f"✗ 模板不存在: {template_id}")
            return False

        logger.info(f"\n模板信息:")
        logger.info(f"  UID: {template_meta.uid}")
        logger.info(f"  function_key: {template_meta.function_key}")
        logger.info(f"  function_keys: {template_meta.function_keys}")
        logger.info(f"  layout_type: {template_meta.layout_type}")
        logger.info(f"  data_keys: {template_meta.data_keys}")

        # 2. 验证配置
        if len(template_meta.function_keys) != 2:
            logger.error(f"✗ 期望 2 个 function_key，实际: {len(template_meta.function_keys)}")
            return False

        if len(template_meta.data_keys) != 2:
            logger.error(f"✗ 期望 2 个 data_key，实际: {len(template_meta.data_keys)}")
            return False

        logger.success("\n✓ 配置验证通过")

        # 3. 初始化 Provider
        provider = RealEstateDataProvider(city, block, start_year, end_year, table)

        # 4. 构建 Context
        logger.info("\n构建 Context...")
        context = ContextBuilder.build_context(
            template_meta=template_meta,
            provider=provider,
            city=city,
            block=block,
            start_year=start_year,
            end_year=end_year,
        )

        # 5. 验证结果
        logger.info("\n验证 Context:")
        logger.info(f"  数据集数量: {len(context._datasets)}")
        logger.info(f"  数据集键: {list(context._datasets.keys())}")
        logger.info(f"  变量数量: {len(context._variables)}")

        # 验证数据集
        expected_datasets = list(template_meta.data_keys.values())
        for dataset_name in expected_datasets:
            if dataset_name not in context._datasets:
                logger.error(f"✗ 缺少数据集: {dataset_name}")
                return False
            logger.success(f"  ✓ 数据集存在: {dataset_name}, shape={context._datasets[dataset_name].shape}")

        # 验证结论变量（只应该有第一个 function_key 的）
        if len(context._variables) < 4:  # 至少应该有基础变量 + 结论变量
            logger.warning(f"  ⚠ 结论变量较少: {len(context._variables)} 个")

        logger.success("\n✓ Context 构建成功")

        # 6. 生成 PPT
        logger.info("\n生成 PPT...")
        output_file = f"output/test_multi_datasource_{template_id}_{block.replace(' ', '_')}.pptx"
        logger.info(f"输出文件: {output_file}")

        engine = PPTGenerationEngine(output_file)
        engine.generate_multiple_slides(
            [{"template_id": template_id, "context": context}]
        )

        logger.success(f"\n✓ PPT 生成成功: {output_file}")

        logger.success("\n" + "=" * 80)
        logger.success("多数据源测试通过！")
        logger.success("=" * 80)
        return True

    except Exception as e:
        logger.error(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    logger.add("logs/test_multi_datasource.log", rotation="10 MB")

    success = test_multi_datasource_template()

    if success:
        logger.success("\n✓ 所有测试通过！")
        logger.info("请查看 output/ 目录生成的 PPT 文件")
        sys.exit(0)
    else:
        logger.error("\n✗ 测试失败")
        sys.exit(1)
