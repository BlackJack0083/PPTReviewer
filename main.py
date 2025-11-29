import yaml
from loguru import logger

from ppt_operations import PPTOperations
from slide_renderers import RendererFactory


def detect_layout_type(config: dict) -> str:
    """
    根据 elements 中的 role 统计信息来推断 layout_type
    规则:
    1. 1个 chart-bar -> single_column_bar
    2. 1个 chart-line -> single_column_line
    3. 2个 chart-line -> double_column_line
    4. 2个 chart-bar -> double_column_bar
    5. chart-bar + chart-line -> double_column_mix (混合双栏)
    """
    elements = config.get("template_slide", {}).get("elements", [])

    # 统计图表类型的数量
    bar_count = 0
    line_count = 0
    total_charts = 0

    for el in elements:
        if el.get("type") == "chart":
            total_charts += 1
            role = el.get("role", "")
            if "bar" in role:
                bar_count += 1
            elif "line" in role:
                line_count += 1

    layout_type = "base"

    if total_charts == 1:
        if bar_count == 1:
            layout_type = "single_column_bar"
        elif line_count == 1:
            layout_type = "single_column_line"
        else:
            # 可能是饼图或其他单图
            layout_type = "single_column_chart"

    elif total_charts == 2:
        if line_count == 2:
            layout_type = "double_column_line"
        elif bar_count == 2:
            layout_type = "double_column_bar"
        else:
            layout_type = "double_column_mix"

    elif total_charts == 0:
        # 可能是纯文本页或表格页
        for el in elements:
            if el.get("type") == "table":
                layout_type = "single_column_table"
                break

    return layout_type


def generate_ppt_from_yaml(yaml_file: str, output_ppt: str):
    logger.info(f"Loading configuration from: {yaml_file}")
    with open(yaml_file, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 初始化 PPT
    ppt_ops = PPTOperations(output_ppt)

    slide_size = config.get("template_slide", {}).get("slide_size", {})
    width = slide_size.get("width", 33.867)
    height = slide_size.get("height", 19.05)

    ppt_ops.init_slides(1, width, height)

    # 自动推断版式
    layout_type = detect_layout_type(config)
    logger.info(f"Detected Layout Strategy: {layout_type}")

    # 获取渲染器并执行
    renderer = RendererFactory.get_renderer(layout_type, ppt_ops)

    slide_data = config.get("template_slide", {})
    renderer.render(slide_data, page_num=1)

    ppt_ops.save()
    logger.info(f"PPT generated successfully: {output_ppt}")


if __name__ == "__main__":

    yaml_path = "data/ReSlide_02/3/template-3/BeijingDongba-7668359c87e34caaa4ac7f6dcd80f255.yaml"

    generate_ppt_from_yaml(yaml_path, "output/report_output.pptx")
