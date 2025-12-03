"""
PPT生成引擎 - 统一的PPT生成接口

这个模块提供了完整的PPT生成工作流，整合了：
1. 模板系统 (template_system)
2. 数据管理 (data_manager)
3. 渲染系统 (rendering)
4. PPT操作 (core/ppt_operations)

主要功能：
- 支持所有31个模板
- 统一的数据接入接口
- 灵活的版式管理
- 完善的错误处理
"""

from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from core.ppt_operations import PPTOperations
from data_manager.context import PresentationContext
from rendering.slide_renderers import RendererFactory
from template_system.builder import SlideConfigBuilder
from template_system.catalog import TEMPLATE_CATALOG, get_template_by_id


class PPTGenerationEngine:
    """PPT生成引擎

    职责：
    1. 管理PPT生成的完整工作流
    2. 提供统一的API接口
    3. 协调各个子系统的工作
    4. 处理错误和异常情况
    """

    def __init__(
        self, output_file_path: str | Path, template_file_path: str | Path = None
    ):
        """
        初始化PPT生成引擎

        Args:
            output_file_path: 输出PPT文件路径
            template_file_path: 模板PPT文件路径（可选）
        """
        self.output_file_path = output_file_path
        self.template_file_path = template_file_path
        self.slide_config_builder = SlideConfigBuilder()

        logger.info(f"Initialized PPT Generation Engine for: {output_file_path}")

    def generate_single_slide(
        self, template_id: str, presentation_context: PresentationContext
    ) -> None:
        """
        生成单页PPT

        Args:
            template_id: 模板ID，如 "T01_Area_Supply_Demand"
            presentation_context: 包含数据和变量的上下文

        Raises:
            ValueError: 模板不存在或数据缺失时抛出异常
        """
        logger.info(f"Generating single slide with template: {template_id}")

        try:
            with PPTOperations(
                self.output_file_path, self.template_file_path
            ) as ppt_operations:
                # 初始化幻灯片（1页）
                ppt_operations.init_slides(1)

                # 构建幻灯片配置
                slide_config = self.slide_config_builder.build(
                    template_id, presentation_context
                )

                # 获取对应的渲染器
                layout_type = slide_config["layout_type"]
                renderer = RendererFactory.get_renderer(layout_type, ppt_operations)

                # 渲染幻灯片
                renderer.render(slide_config["template_slide"], page_number=1)

        except Exception as e:
            logger.error(f"Failed to generate slide with template {template_id}: {e}")
            raise

    def generate_multiple_slides(self, template_configs: list[dict[str, Any]]) -> None:
        """
        生成多页PPT

        Args:
            template_configs: 模板配置列表，每个包含:
                - template_id: 模板ID
                - context: 对应的PresentationContext

        Raises:
            ValueError: 配置无效时抛出异常
        """
        logger.info(f"Generating {len(template_configs)} slides")

        try:
            with PPTOperations(
                self.output_file_path, self.template_file_path
            ) as ppt_operations:
                # 初始化幻灯片（多页）
                ppt_operations.init_slides(len(template_configs))

                for page_index, config in enumerate(template_configs, start=1):
                    template_id = config["template_id"]
                    presentation_context = config["context"]

                    logger.info(f"Generating page {page_index}: {template_id}")

                    # 构建幻灯片配置
                    # 确保传入完整的模板ID（如 "T01_Area_Supply_Demand"）
                    full_template_id = config.get("full_template_id", template_id)

                    # 如果没有完整ID，尝试从catalog查找
                    if not config.get("full_template_id"):
                        from template_system.catalog import TEMPLATE_CATALOG

                        # 尝试找到匹配的模板
                        for catalog_id, template_meta in TEMPLATE_CATALOG.items():
                            if template_meta.uid == template_id:
                                full_template_id = catalog_id
                                break

                    slide_config = self.slide_config_builder.build(
                        full_template_id, presentation_context
                    )

                    # 获取对应的渲染器
                    layout_type = slide_config["layout_type"]
                    renderer = RendererFactory.get_renderer(layout_type, ppt_operations)

                    # 渲染幻灯片
                    renderer.render(
                        slide_config["template_slide"], page_number=page_index
                    )

        except Exception as e:
            logger.error(f"Failed to generate multiple slides: {e}")
            raise

    def generate_from_template_category(
        self, category: str, presentation_context: PresentationContext
    ) -> None:
        """
        根据模板分类生成PPT

        Args:
            category: 模板分类，如 "面积分析"、"价格分析" 等
            presentation_context: 包含数据和变量的上下文

        Raises:
            ValueError: 分类不存在时抛出异常
        """
        logger.info(f"Generating slides from category: {category}")

        # 临时禁用分类功能，因为新的catalog结构不支持分类
        logger.warning("分类生成功能暂时不可用，请使用generate_single_slide")
        return

    def generate_all_templates(self, presentation_context: PresentationContext) -> None:
        """
        生成所有模板的PPT（用于测试和演示）

        Args:
            presentation_context: 包含数据和变量的上下文
        """
        logger.info("Generating all templates (may take a while)")

        # 构建所有模板的配置列表
        template_configs = [
            {"template_id": template_id, "context": presentation_context}
            for template_id in TEMPLATE_CATALOG
        ]

        # 生成多页PPT
        self.generate_multiple_slides(template_configs)

    def validate_template_data(
        self, template_id: str, presentation_context: PresentationContext
    ) -> bool:
        """
        简化的模板验证

        Args:
            template_id: 模板ID
            presentation_context: 数据上下文

        Returns:
            bool: 数据是否齐全
        """
        template = get_template_by_id(template_id)
        if not template:
            logger.error(f"Template not found: {template_id}")
            return False

        # 检查数据
        for data_key in template.data_keys.values():
            if data_key not in presentation_context._datasets:
                logger.error(f"Missing dataset '{data_key}' for template {template_id}")
                return False

        logger.info(f"Template {template_id} validation passed")
        return True

    def get_template_info(self) -> dict[str, Any]:
        """
        获取模板系统信息

        Returns:
            Dict: 包含模板数量等信息
        """
        template_info = {
            "total_templates": len(TEMPLATE_CATALOG),
            "template_list": list(TEMPLATE_CATALOG.keys()),
        }

        return template_info


class PPTDataHelper:
    """PPT数据助手类，帮助准备PresentationContext"""

    @staticmethod
    def create_context() -> PresentationContext:
        """创建新的PresentationContext"""
        return PresentationContext()

    @staticmethod
    def add_sample_data(context: PresentationContext) -> None:
        """添加示例数据到上下文（已废弃，建议使用真实CSV数据）"""
        logger.warning("add_sample_data 已废弃，请使用真实的CSV数据文件")

        # 可以在这里添加一些简单的示例数据
        import pandas as pd

        # 示例数据
        sample_data = pd.DataFrame(
            {
                "类别": ["80-100㎡", "100-120㎡", "120-140㎡"],
                "供应套数": [1000, 500, 300],
                "成交套数": [800, 400, 250],
            }
        ).set_index("类别")

        context.add_dataset("sample_data", sample_data)

        # 添加示例变量
        context.add_variable("Temporal_Start_Year", "2023")
        context.add_variable("Temporal_End_Year", "2024")
        context.add_variable("Geo_City_Name", "北京")
        context.add_variable("Geo_Block_Name", "示例板块")

    @staticmethod
    def add_custom_data(
        context: PresentationContext, data_name: str, data: pd.DataFrame
    ) -> None:
        """添加自定义数据到上下文"""
        context.add_dataset(data_name, data)

    @staticmethod
    def add_custom_variable(
        context: PresentationContext, var_name: str, value: Any
    ) -> None:
        """添加自定义变量到上下文"""
        context.add_variable(var_name, value)


# 便捷函数
def quick_generate_ppt(
    template_id: str, output_file: str, use_sample_data: bool = True
) -> None:
    """
    快速生成PPT的便捷函数

    Args:
        template_id: 模板ID
        output_file: 输出文件路径
        use_sample_data: 是否使用示例数据
    """
    engine = PPTGenerationEngine(output_file)

    if use_sample_data:
        context = PPTDataHelper.create_context()
        PPTDataHelper.add_sample_data(context)
    else:
        # 用户需要自己填充数据
        context = PPTDataHelper.create_context()
        logger.warning("使用空数据上下文，请确保添加所需的数据和变量")

    engine.generate_single_slide(template_id, context)
    logger.info(f"PPT generated successfully: {output_file}")


# 使用示例
if __name__ == "__main__":
    # 示例1: 快速生成单个模板
    quick_generate_ppt("T01_Area_Supply_Demand", "output/example_single.pptx")

    # 示例2: 使用自定义数据
    engine = PPTGenerationEngine("output/example_custom.pptx")
    context = PPTDataHelper.create_context()
    PPTDataHelper.add_sample_data(context)
    PPTDataHelper.add_custom_variable(context, "city", "上海")
    PPTDataHelper.add_custom_variable(context, "block", "浦东")

    engine.generate_single_slide("T11_Price_Trend", context)

    # 示例3: 生成整个分类的模板
    engine = PPTGenerationEngine("output/example_category.pptx")
    context = PPTDataHelper.create_context()
    PPTDataHelper.add_sample_data(context)

    engine.generate_from_template_category("面积分析", context)
