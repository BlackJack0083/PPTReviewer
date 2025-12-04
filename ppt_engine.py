from pathlib import Path
from typing import Any

from loguru import logger

from core.ppt_operations import PPTOperations
from data_manager.context import PresentationContext
from rendering.slide_renderers import RendererFactory
from template_system.builder import SlideConfigBuilder
from template_system.catalog import TEMPLATE_CATALOG


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
