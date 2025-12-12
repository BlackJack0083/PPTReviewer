from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from core import PPTOperations, PresentationContext, resource_manager

from .builder import SlideConfigBuilder
from .slide_renderers import RendererFactory


@dataclass
class SlideTask:
    """定义单个幻灯片的生成任务"""

    template_id: str
    context: PresentationContext
    # 可选：如果传入的 template_id 是简写(uid)，可以在这里缓存完整ID
    full_template_id: str | None = None


class PPTGenerationEngine:
    """PPT生成引擎

    职责：
    1. 管理PPT生成的完整工作流
    2. 提供统一的API接口 (单页/多页)
    3. 协调 ConfigBuilder 和 Renderer
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

        # 建立 UID 到 Full ID 的快速查找表，避免在循环中遍历 Catalog
        self._template_id_map: dict[str, str] = {}
        self._refresh_template_map()

        logger.info(f"Initialized PPT Generation Engine for: {output_file_path}")

    def _refresh_template_map(self):
        """刷新 UID 到 Full ID 的映射表"""
        # 从 registry 获取所有模板
        all_templates = resource_manager.all_templates

        self._template_id_map = {
            meta.uid: full_id for full_id, meta in all_templates.items()
        }

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

        task = SlideTask(template_id=template_id, context=presentation_context)
        self.generate_multiple_slides([task])

    def generate_multiple_slides(self, tasks: list[SlideTask | dict]) -> None:
        """
        生成多页PPT

        Args:
            ttasks: SlideTask 对象列表，或者包含 'template_id' 和 'context' 的字典列表

        Raises:
            ValueError: 配置无效时抛出异常
        """
        if not tasks:
            logger.warning("No slides tasks provided.")
            return

        logger.info(f"Starting generation for {len(tasks)} slides")

        try:
            # 统一使用 Context Manager 管理 PPT 生命周期
            with PPTOperations(
                self.output_file_path, self.template_file_path
            ) as ppt_ops:

                ppt_ops.init_slides(len(tasks))

                for index, task_data in enumerate(tasks, start=1):
                    # 兼容字典输入，转换为 SlideTask 对象
                    if isinstance(task_data, dict):
                        task = SlideTask(
                            template_id=task_data["template_id"],
                            context=task_data["context"],
                            full_template_id=task_data.get("full_template_id"),
                        )
                    else:
                        task = task_data

                    self._process_slide(ppt_ops, index, task)

        except Exception as e:
            logger.error(f"PPT Generation failed: {e}")
            raise

    def _process_slide(
        self, ppt_ops: PPTOperations, page_number: int, task: SlideTask
    ) -> None:
        """
        处理单页幻灯片的内部核心逻辑
        """
        # 1. 解析 Template ID
        target_id = self._resolve_template_id(task)
        logger.info(f"Rendering Page {page_number}: {target_id}")

        try:
            # 2. 构建配置 (Builder)
            slide_config = self.slide_config_builder.build(target_id, task.context)

            # 3. 获取渲染器 (Factory)
            layout_type = slide_config.layout_type
            renderer = RendererFactory.get_renderer(layout_type, ppt_ops)

            # 4. 执行渲染 (Renderer)
            renderer.render(slide_config, page_number=page_number)

        except Exception as e:
            # 捕获单页错误，记录日志，选择是否抛出 (这里选择抛出以中断流程，也可改为 continue 跳过错误页)
            logger.error(
                f"Error on page {page_number} (Template: {task.template_id}): {e}"
            )
            raise

    def _resolve_template_id(self, task: SlideTask) -> str:
        """
        解析并验证模板ID。
        优先使用 full_template_id，其次在 catalog 中查找 uid 对应的 full_id。
        """
        if task.full_template_id:
            return task.full_template_id

        # 尝试直接匹配 Catalog Key
        if task.template_id in resource_manager.all_templates:
            return task.template_id

        # 尝试通过 UID 查找 (使用构造函数中建立的缓存 Map，O(1) 复杂度)
        mapped_id = self._template_id_map.get(task.template_id)
        if mapped_id:
            return mapped_id

        # 如果都找不到，假定用户传入的就是 Key，让 Builder 去报错
        return task.template_id

    def get_template_info(self) -> dict[str, Any]:
        templates = resource_manager.all_templates
        return {
            "total_templates": len(templates),
            "template_list": list(templates.keys()),
        }
