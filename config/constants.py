from pptx.dml.color import RGBColor


class LayoutCoordinates:
    """
    PPT 元素布局坐标配置
    单位: cm
    """

    # --- 静态文本元素 ---
    TITLE = {"x": 0.5, "y": 1.0, "width": 18.0, "height": 1.1}
    DESCRIPTION = {"x": 0.5, "y": 2.0, "width": 18.0, "height": 1.2}
    CAPTION = {"x": 3.75, "y": 3.5, "width": 12.5, "height": 1.2}

    # --- 数据元素布局 (图表/表格) ---
    # 单栏大图/表格
    CHART_SINGLE = {"x": 3.7, "y": 4.54, "width": 12.2, "height": 7.48}
    TABLE_MAIN = {"x": 1.5, "y": 4.5, "width": 20.0, "height": 8.96}

    # 双栏布局 (左/右)
    CHART_DOUBLE_LEFT = {"x": 0.75, "y": 4.94, "width": 10.5, "height": 6.5}
    CHART_DOUBLE_RIGHT = {"x": 12.75, "y": 4.94, "width": 10.5, "height": 6.5}


CHART_THEMES = {
    "2_orange_green": [RGBColor(255, 192, 0), RGBColor(0, 176, 80)],
    "2_green_orange": [RGBColor(0, 176, 80), RGBColor(255, 192, 0)],
    "2_orange_olive": [RGBColor(255, 192, 0), RGBColor(0, 176, 180)],
    "2_olive_green": [RGBColor(0, 176, 180), RGBColor(0, 176, 80)],
    "2_white_olive": [RGBColor(255, 255, 255), RGBColor(0, 176, 180)],
    "2_blue_lightblue": [RGBColor(0, 176, 240), RGBColor(169, 227, 255)],
    "2_olive_orange": [RGBColor(0, 176, 180), RGBColor(255, 192, 0)],
    "2_gray_lightblue2": [RGBColor(182, 191, 197), RGBColor(169, 227, 255)],
    "1_olive": [RGBColor(0, 176, 180)],
    "1_orange": [RGBColor(255, 192, 0)],
    "1_gray": [RGBColor(182, 191, 197)],
    "1_lightblue": [RGBColor(0, 176, 240)],
    "1_tangerine": [RGBColor(255, 102, 153)],
    "2_tangerine_gray": [RGBColor(255, 102, 153), RGBColor(182, 191, 197)],
    "2_gray_tangerine": [RGBColor(182, 191, 197), RGBColor(255, 102, 153)],
    "2_gray_lightblue": [RGBColor(182, 191, 197), RGBColor(0, 176, 240)],
    "2_green_gray": [RGBColor(0, 176, 80), RGBColor(182, 191, 197)],
    "2_olive_gray": [RGBColor(0, 176, 180), RGBColor(182, 191, 197)],
}
