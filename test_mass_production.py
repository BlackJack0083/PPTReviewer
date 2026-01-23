#!/usr/bin/env python3
"""
大规模 PPT 生成脚本
为每个 block 生成所有模板的 PPT
"""
import csv
import os
import traceback
from pathlib import Path
from loguru import logger

from core import ContextBuilder, resource_manager
from core.data_provider import RealEstateDataProvider
from engine import PPTGenerationEngine


# ==================== 配置 ====================

# 城市配置映射
CITY_CONFIGS = {
    "beijing": {
        "city": "Beijing",
        "table": "Beijing_new_house",
        "csv_file": "test/beijing.csv",
    },
    "guangzhou": {
        "city": "Guangzhou",
        "table": "Guangzhou_new_house",
        "csv_file": "test/guangzhou.csv",
    },
    "shenzhen": {
        "city": "Shenzhen",
        "table": "Shenzhen_new_house",
        "csv_file": "test/shenzhen.csv",
    },
}

# 时间范围
START_YEAR = "2020"
END_YEAR = "2022"

# 输出根目录
OUTPUT_ROOT = Path("output/mass_production")

# ==================== 核心函数 ====================


def load_blocks_from_csv(csv_file: str) -> list[str]:
    """
    从 CSV 文件加载 block 列表

    Args:
        csv_file: CSV 文件路径

    Returns:
        block 列表
    """
    blocks = []
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            blocks.append(row["block"])
    return blocks


def get_all_templates() -> list[str]:
    """获取所有启用的模板 ID"""
    resource_manager.load_all()

    # 从 template_definitions.yaml 中获取所有模板
    all_templates = [
        # ReSlide_01
        "T01_Supply_Trans_Bar",
        "T01_Supply_Trans_Line",
        # ReSlide_02
        "T02_Cross_Pivot_Table",
        "T02_Area_Dist_Bar",
        "T02_Area_Dist_Line",
        "T02_Price_Dist_Bar",
        "T02_Price_Dist_Line",
        "T02_Double_Price_Dist_Line",  # 多数据源示例
    ]

    # 验证模板是否存在
    valid_templates = []
    for template_id in all_templates:
        if resource_manager.get_template(template_id):
            valid_templates.append(template_id)
        else:
            logger.warning(f"模板不存在: {template_id}")

    return valid_templates


def generate_ppt_for_block(
    city_name: str,
    table_name: str,
    block: str,
    template_id: str,
    output_dir: Path,
):
    """
    为单个 block 生成单个模板的 PPT

    Args:
        city_name: 城市名
        table_name: 表名
        block: 板块名
        template_id: 模板 ID
        output_dir: 城市输出目录（会在其下创建 block 子目录）

    Returns:
        bool: 是否成功
    """
    try:
        # 获取模板元数据
        template_meta = resource_manager.get_template(template_id)
        if not template_meta:
            logger.error(f"✗ 模板不存在: {template_id}")
            return False

        # 初始化 Provider
        provider = RealEstateDataProvider(
            city_name, block, START_YEAR, END_YEAR, table_name
        )

        # 构建 Context
        context = ContextBuilder.build_context(
            template_meta=template_meta,
            provider=provider,
            city=city_name,
            block=block,
            start_year=START_YEAR,
            end_year=END_YEAR,
        )

        # 为每个 block 创建单独的文件夹
        safe_block = block.replace(" ", "_").replace("/", "_")
        block_dir = output_dir / safe_block
        block_dir.mkdir(parents=True, exist_ok=True)

        # 生成文件名
        filename = f"{template_id}.pptx"
        output_file = block_dir / filename

        # 生成 PPT
        engine = PPTGenerationEngine(str(output_file))
        engine.generate_multiple_slides(
            [{"template_id": template_id, "context": context}]
        )

        logger.debug(f"  ✓ 生成成功: {safe_block}/{filename}")
        return True

    except Exception as e:
        logger.error(f"  ✗ 生成失败: {template_id} - {e}")
        logger.debug(traceback.format_exc())
        return False


def generate_city_blocks(
    city_key: str,
    templates: list[str],
):
    """
    为指定城市的所有 block 生成 PPT

    Args:
        city_key: 城市键（beijing/guangzhou/shenzhen）
        templates: 模板 ID 列表

    Returns:
        统计信息
    """
    config = CITY_CONFIGS[city_key]
    city_name = config["city"]
    table_name = config["table"]
    csv_file = config["csv_file"]

    logger.info(f"\n{'='*80}")
    logger.info(f"开始处理城市: {city_name}")
    logger.info(f"{'='*80}")
    logger.info(f"表: {table_name}")
    logger.info(f"CSV: {csv_file}")
    logger.info(f"模板数量: {len(templates)}")

    # 加载 blocks
    logger.info(f"\n加载 block 列表...")
    blocks = load_blocks_from_csv(csv_file)
    logger.info(f"找到 {len(blocks)} 个 blocks")

    # 创建输出目录
    output_dir = OUTPUT_ROOT / city_key
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"输出目录: {output_dir}")

    # 统计
    stats = {
        "total": len(blocks) * len(templates),
        "success": 0,
        "failed": 0,
        "by_template": {tid: 0 for tid in templates},
    }

    # 遍历所有 blocks
    for i, block in enumerate(blocks, 1):
        logger.info(f"\n{'─'*60}")
        logger.info(f"处理 block [{i}/{len(blocks)}]: {block}")
        logger.info(f"{'─'*60}")

        # 遍历所有模板
        for template_id in templates:
            success = generate_ppt_for_block(
                city_name=city_name,
                table_name=table_name,
                block=block,
                template_id=template_id,
                output_dir=output_dir,
            )

            if success:
                stats["success"] += 1
                stats["by_template"][template_id] += 1
            else:
                stats["failed"] += 1

    return stats


def generate_all_cities(
    templates: list[str],
    city_keys: list[str] = None,
):
    """
    为所有城市生成 PPT

    Args:
        templates: 模板 ID 列表
        city_keys: 城市键列表，None 表示处理所有城市
    """
    if city_keys is None:
        city_keys = list(CITY_CONFIGS.keys())

    logger.info(f"\n{'#'*80}")
    logger.info(f"大规模 PPT 生成任务")
    logger.info(f"{'#'*80}")
    logger.info(f"城市: {', '.join(city_keys)}")
    logger.info(f"模板数量: {len(templates)}")
    logger.info(f"时间范围: {START_YEAR}-{END_YEAR}")
    logger.info(f"{'#'*80}\n")

    # 加载资源
    resource_manager.load_all()

    # 总统计
    total_stats = {
        "cities": {},
        "total_success": 0,
        "total_failed": 0,
    }

    # 处理每个城市
    for city_key in city_keys:
        stats = generate_city_blocks(city_key, templates)
        total_stats["cities"][city_key] = stats
        total_stats["total_success"] += stats["success"]
        total_stats["total_failed"] += stats["failed"]

    # 打印总结
    print_summary(total_stats, templates)

    return total_stats


def print_summary(stats: dict, templates: list[str]):
    """打印统计总结"""
    logger.info(f"\n{'#'*80}")
    logger.info(f"生成任务完成")
    logger.info(f"{'#'*80}")

    total = stats["total_success"] + stats["total_failed"]
    success_rate = stats["total_success"] / total * 100 if total > 0 else 0

    logger.info(f"\n总体统计:")
    logger.info(f"  总任务数: {total}")
    logger.info(f"  成功: {stats['total_success']} ({success_rate:.1f}%)")
    logger.info(f"  失败: {stats['total_failed']}")

    logger.info(f"\n各城市统计:")
    for city_key, city_stats in stats["cities"].items():
        city_total = city_stats["success"] + city_stats["failed"]
        city_rate = city_stats["success"] / city_total * 100 if city_total > 0 else 0
        logger.info(
            f"  {city_key}: {city_stats['success']}/{city_total} ({city_rate:.1f}%)"
        )

    logger.info(f"\n按模板统计:")
    for template_id in templates:
        total_count = sum(
            city_stats["by_template"].get(template_id, 0)
            for city_stats in stats["cities"].values()
        )
        logger.info(f"  {template_id}: {total_count}")

    logger.info(f"\n输出目录: {OUTPUT_ROOT.absolute()}")
    logger.info(f"{'#'*80}\n")


# ==================== 主程序 ====================


if __name__ == "__main__":
    # 配置日志
    logger.add("logs/mass_production.log", rotation="10 MB")

    # 选择要处理的城市
    # ALL_CITIES = list(CITY_CONFIGS.keys())  # 所有城市
    ALL_CITIES = ["beijing"]  # 只处理北京（测试用）

    # 选择要生成的模板
    ALL_TEMPLATES = get_all_templates()

    print("\n" + "=" * 80)
    print("大规模 PPT 生成系统")
    print("=" * 80)
    print(f"\n可用城市: {', '.join(CITY_CONFIGS.keys())}")
    print(f"可用模板数量: {len(ALL_TEMPLATES)}")
    print(f"输出目录: {OUTPUT_ROOT.absolute()}")
    print("\n请选择:")
    print("1. 生成所有城市的所有 PPT")
    print("2. 只生成北京")
    print("3. 只生成广州")
    print("4. 只生成深圳")
    print("5. 自定义")
    print("=" * 80)

    choice = input("\n请输入选项 (1-5): ").strip()

    if choice == "1":
        cities = list(CITY_CONFIGS.keys())
    elif choice == "2":
        cities = ["beijing"]
    elif choice == "3":
        cities = ["guangzhou"]
    elif choice == "4":
        cities = ["shenzhen"]
    elif choice == "5":
        print("\n可用城市:", ", ".join(CITY_CONFIGS.keys()))
        city_input = input("请输入城市（用逗号分隔）: ").strip()
        cities = [c.strip().lower() for c in city_input.split(",")]
        # 验证
        for city in cities:
            if city not in CITY_CONFIGS:
                logger.error(f"无效的城市: {city}")
                exit(1)
    else:
        logger.error("无效的选项")
        exit(1)

    # 确认
    print(f"\n将处理以下城市: {', '.join(cities)}")
    print(f"模板数量: {len(ALL_TEMPLATES)}")
    confirm = input("\n确认开始? (y/n): ").strip().lower()

    if confirm != "y":
        logger.info("已取消")
        exit(0)

    # 执行生成
    generate_all_cities(templates=ALL_TEMPLATES, city_keys=cities)

    logger.info("\n✓ 所有任务完成！")
    logger.info(f"请查看 {OUTPUT_ROOT.absolute()} 目录")
