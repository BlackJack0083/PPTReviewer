import pandas as pd
import yaml
from loguru import logger

from ppt_operations import PPTOperations
from ppt_schemas import (
    Align,
    ChartConfigModel,
    Color,
    LayoutModel,
    RectangleStyleModel,
    TextContentModel,
)


class YamlSlideGenerator:
    def __init__(self, ppt_path: str = "output.pptx"):
        self.ppt_path = ppt_path

    def _map_layout(self, yaml_layout: dict[str, float]) -> LayoutModel:
        """将 YAML 的 layout (x, y) 映射到 LayoutModel (left, top)"""
        return LayoutModel(
            left=yaml_layout["x"],
            top=yaml_layout["y"],
            width=yaml_layout["width"],
            height=yaml_layout.get("height", 0),
            alignment=Align.LEFT,  # 默认左对齐，具体对齐可能会在 TextContentModel 覆盖或由逻辑控制
        )

    def _get_text_style_by_role(self, role: str, text: str) -> TextContentModel:
        """
        根据 role 返回对应的样式模型
        """
        base_config = {
            "text": text,
            "word_wrap": True,
            "font_name": "微软雅黑",
        }

        if role == "slide-title":
            return TextContentModel(
                **base_config, font_size=24, font_bold=True, font_color=Color.BLACK
            )
        elif role == "caption":
            return TextContentModel(
                **base_config, font_size=12, font_bold=False, font_color=Color.GRAY
            )
        elif role == "body-text":
            return TextContentModel(
                **base_config, font_size=14, font_bold=False, font_color=Color.BLACK
            )
        else:
            return TextContentModel(
                **base_config, font_size=14, font_bold=False, font_color=Color.BLACK
            )

    def _mock_data_fetcher(self, args: list) -> pd.DataFrame:
        """模拟数据获取"""
        data = {
            "0-20m²": 50,
            "20-40m²": 150,
            "40-60m²": 800,
            "60-80m²": 2500,
            "80-100m²": 2541,
            "100-120m²": 600,
            "120-140m²": 300,
            "140-160m²": 100,
            "160-180m²": 50,
            "180-200m²": 20,
        }
        # 转换为 DataFrame: Index 为图例(系列), Columns 为 X轴(类别)
        df = pd.DataFrame([data], index=["Count"])
        return df

    def generate(self, yaml_content: str):
        """主生成逻辑"""
        # 1. 解析 YAML
        config = yaml.safe_load(yaml_content)
        slide_config = config.get("template_slide", {})

        # 2. 获取尺寸配置
        size = slide_config.get("slide_size", {"width": 33.87, "height": 19.05})

        # 3. 使用 Context Manager 初始化 PPT
        with PPTOperations(self.ppt_path) as ppt:
            # 初始化页面：传入尺寸，确保至少有1页
            ppt.init_slides(count=1, width_cm=size["width"], height_cm=size["height"])

            elements = slide_config.get("elements", [])
            current_page = 1

            for el in elements:
                el_type = el.get("type")
                el_role = el.get("role")
                layout_model = self._map_layout(el["layout"])

                if el_type == "textBox":
                    # 构建文本内容模型
                    content_model = self._get_text_style_by_role(
                        el_role, el.get("text", "")
                    )

                    # 新接口统一使用 add_textbox
                    ppt.add_title(
                        page_num=current_page,
                        content=content_model,
                        layout=layout_model,
                    )

                elif el_type == "chart":
                    # 1. 获取数据
                    df = self._mock_data_fetcher(el.get("args", []))

                    # 2. 配置图表样式
                    chart_config = ChartConfigModel(
                        style_name="2_blue_lightblue",  # 使用新代码中存在的 key
                        font_size=10,
                        has_legend=True,
                        has_data_labels=False,
                        y_axis_visible=True,
                    )

                    # 3. 绘制
                    ppt.add_chart(
                        page_num=current_page,
                        df=df,
                        layout=layout_model,
                        config=chart_config,
                    )

                elif el_type == "rectangle":
                    rect_style = RectangleStyleModel(
                        fore_color=Color.GRAY, is_background=True
                    )
                    ppt.add_rectangle(
                        page_num=current_page, layout=layout_model, style=rect_style
                    )

        logger.info(f"PPT 生成完毕: {self.ppt_path}")


# ==========================================
# 使用示例数据
# ==========================================
yaml_data = """
template_slide:
  slide_size:
    width: 19.05
    height: 14.29
  elements:
  - id: '1'
    type: textBox
    text: Cross-Structure Analysis of New-House Transactions
    role: slide-title
    layout:
      x: 0.5
      y: 1.0
      width: 18.0
      height: 1.1
  - id: '2'
    type: textBox
    text: Mainstream types concentrate in 60-80m² and 80-100m² segments, totaling 5041 units.
    role: body-text
    layout:
      x: 0.5
      y: 1.9
      width: 18.0
      height: 1.5
  - id: '3'
    type: textBox
    text: 2020-2022 Beijing Liangxiang Total Area Segment Distribution Statistics
    role: caption
    layout:
      x: 3.9
      y: 3.6
      width: 12.0
      height: 1.3
  - id: '4'
    type: chart
    role: chart-bar
    layout:
      x: 3.7
      y: 4.94
      width: 12.2
      height: 7.48
    args:
    - field-constraint
"""

if __name__ == "__main__":
    # 确保 output 目录存在
    import os

    os.makedirs("output", exist_ok=True)

    generator = YamlSlideGenerator("output/analysis_report.pptx")
    generator.generate(yaml_data)
