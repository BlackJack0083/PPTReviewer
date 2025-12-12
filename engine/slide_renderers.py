from typing import Any

from loguru import logger

from core import (
    Color,
    LayoutType,
    PPTOperations,
    RectangleStyleModel,
    TextContentModel,
    style_manager,
)
from core.schemas import (
    ChartElement,
    RenderableElement,
    SlideRenderConfig,
    TableElement,
    TextElement,
)


class BaseSlideRenderer:
    """所有版式渲染器的基类

    职责：
    1. 提供统一的渲染接口和元素分发逻辑
    2. 定义通用的文本、图表、表格渲染方法
    3. 管理PPT操作对象的引用
    4. 解耦数据获取逻辑，专注于渲染逻辑
    """

    def __init__(self, ppt_operations: PPTOperations, layout_type: LayoutType):
        """
        初始化渲染器

        Args:
            ppt_operations: PPT操作对象
            layout_type: 版式类型
        """
        self.ppt_operations = ppt_operations
        self.layout_type = layout_type

    def render(self, slide_configuration: SlideRenderConfig, page_number: int) -> None:
        """
        主渲染入口

        Args:
            slide_configuration: 幻灯片配置字典
            page_number: 幻灯片页码（从1开始）
        """
        self.current_style_id = slide_configuration.style_id

        elements = slide_configuration.elements

        if not elements:
            logger.warning(f"No elements to render for page {page_number}")
            return

        logger.info(f"Rendering page {page_number} with {len(elements)} elements")

        for element in elements:
            try:
                self._render_element(page_number, element)
            except Exception as e:
                logger.error(f"Failed to render element on page {page_number}: {e}")
                # 继续渲染其他元素，不因单个元素失败而中断整个渲染过程

    def _render_element(self, page_number: int, element: RenderableElement) -> None:
        """
        根据元素类型分发到具体的渲染方法，使用字典分发

        Args:
            page_number: 幻灯片页码
            element: 元素配置字典
        """
        match element:
            case TextElement():
                self._render_text_box(page_number, element)

            case ChartElement():
                self._render_chart(page_number, element)

            case TableElement():
                self._render_table(page_number, element)

            case _:
                logger.warning(f"Unknown element type: {type(element)}")
                raise ValueError(f"Unknown element type: {type(element)}")

    def _render_text_box(self, page_number: int, element: TextElement) -> None:
        """
        渲染文本框

        Args:
            page_number: 幻灯片页码
            element: 文本框元素配置
        """
        # 1. 从 StyleManager 获取样式对象 (TextStyleDefinition)
        style_def = style_manager.get_text_style(self.current_style_id, element.role)

        # 2. 合并样式与文本内容
        # 利用 Pydantic 的 model_dump() 将样式对象转为字典，然后解包传入
        content_model = TextContentModel(text=element.text, **style_def.model_dump())

        self.ppt_operations.add_text_box(page_number, content_model, element.layout)

    def _get_text_style_by_role(self, role: str) -> tuple[int, bool, Color]:
        """
        根据角色获取文本样式

        Args:
            role: 元素角色

        Returns:
            tuple: (字体大小, 是否加粗, 字体颜色)
        """

        role_styles = {
            "slide-title": (24, True, Color.BLACK),
            "body-text": (14, False, Color.DARK_BLUE),
            "caption": (10, False, Color.GRAY),
        }

        return role_styles.get(role, (12, False, Color.BLACK))

    def _render_chart(self, page_number: int, element: ChartElement) -> None:
        """
        渲染图表（基类默认实现）

        Args:
            page_number: 幻灯片页码
            element: 图表元素配置
        """
        chart_role = element.role
        chart_data = element.data_payload

        # 2. 根据 layout_type 或 role 路由到具体的图表类型
        if "bar" in chart_role.lower():
            config = style_manager.get_bar_style(self.current_style_id)
            self.ppt_operations.add_bar_chart(
                page_number, chart_data, element.layout, config
            )
        elif "line" in chart_role.lower():
            config = style_manager.get_line_style(self.current_style_id)
            self.ppt_operations.add_line_chart(
                page_number, chart_data, element.layout, config
            )
        else:
            logger.warning(f"Unknown chart role: {chart_role}")

    def _render_table(self, page_number: int, element: TableElement) -> None:
        """
        渲染表格

        Args:
            page_number: 幻灯片页码
            element: 表格元素配置
        """
        table_data = element.data_payload

        # 默认表格样式
        font_name = "微软雅黑"
        # 根据版式决定字体大小（如果需要在不同版式下有不同表格样式，也可以移入 ConfigManager）
        font_size = 12 if self.layout_type == LayoutType.DOUBLE_COLUMN_LINE else 11

        self.ppt_operations.add_table(
            page_num=page_number,
            layout=element.layout,
            data=table_data,
            font_name=font_name,
            font_size=font_size,
        )

    def _render_rectangle(self, page_number: int, element: dict[str, Any]) -> None:
        """
        渲染矩形

        Args:
            page_number: 幻灯片页码
            element: 矩形元素配置
        """
        layout = element.get("layout", {})

        # 默认矩形样式
        style = RectangleStyleModel(
            fore_color=Color.GRAY,
            line_color=Color.GRAY,
            line_width=0,
            rotation=0,
            is_background=False,
        )

        self.ppt_operations.add_rectangle(page_number, layout, style)

    def _render_picture(self, page_number: int, element: dict[str, Any]) -> None:
        """
        渲染图片

        Args:
            page_number: 幻灯片页码
            element: 图片元素配置
        """
        image_path = element.get("image_path", "")
        layout = element.get("layout", {})

        if not image_path:
            logger.warning("No image path provided")
            return

        self.ppt_operations.add_picture(page_number, image_path, layout)


class RendererFactory:
    """渲染器工厂类"""

    @staticmethod
    def get_renderer(
        layout_type: LayoutType, ppt_operations: PPTOperations
    ) -> BaseSlideRenderer:
        """
        现在的工厂不再需要返回不同的子类，
        而是返回同一个类，但注入了不同的 layout_type 上下文。
        """
        logger.info(f"Initializing renderer for layout: {layout_type}")
        return BaseSlideRenderer(ppt_operations, layout_type)

    @staticmethod
    def get_supported_layout_types() -> list[str]:
        return [t.value for t in LayoutType]
