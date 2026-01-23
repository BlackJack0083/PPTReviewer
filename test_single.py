# test_single.py
"""
单例测试脚本 - 测试单个模板在特定表和板块上的表现
用于快速验证特定配置是否正常工作
"""
import traceback

from loguru import logger

from core import ContextBuilder, resource_manager
from core.data_provider import RealEstateDataProvider
from engine import PPTGenerationEngine


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
        # 获取模板元数据
        template_meta = resource_manager.get_template(template_id)
        if not template_meta:
            logger.error(f"✗ 模板不存在: {template_id}")
            return False

        logger.info(f"模板信息: function_key='{template_meta.function_key}'")

        # 遍历所有板块
        for block in table_config["blocks"]:
            logger.info(f"\n{'─'*60}")
            logger.info(f"测试板块: {block}")
            logger.info(f"{'─'*60}")

            # 初始化DataProvider
            provider = RealEstateDataProvider(
                table_config["city"], block, start_year, end_year, table_config["table"]
            )

            # 使用 ContextBuilder 自动构建 Context
            context = ContextBuilder.build_context(
                template_meta=template_meta,
                provider=provider,
                city=table_config["city"],
                block=block,
                start_year=start_year,
                end_year=end_year,
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
