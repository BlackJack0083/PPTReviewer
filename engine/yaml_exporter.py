"""
YAML 导出器
在生成 PPT 时同步生成配置 YAML 文件
记录 slide_state 和 slide_info
"""
from hashlib import md5
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from core import LayoutModel, PresentationContext, resource_manager
from core.layout_manager import layout_manager
from core.schemas import ChartElement, SlideRenderConfig, TableElement, TextElement


class YAMLExporter:
    """
    YAML 配置导出器
    负责将 SlideConfig 和 Context 导出为 YAML 文件
    """

    @staticmethod
    def export_slide_config(
        slide_config: SlideRenderConfig,
        context: PresentationContext,
        template_id: str,
        output_file_path: str | Path,
    ) -> Path:
        """
        导出 SlideConfig 为 YAML 文件

        Args:
            slide_config: Slide 配置对象
            context: PresentationContext（包含数据和变量）
            template_id: 模板 ID
            output_file_path: PPT 输出路径（用于确定 YAML 输出位置）

        Returns:
            导出的 YAML 文件路径
        """
        # 1. 获取模板元数据
        template_meta = resource_manager.get_template(template_id)
        if not template_meta:
            logger.warning(f"无法找到模板元数据: {template_id}")
            return None

        # 2. 从 context 中提取关键信息
        city = context.variables.get("Geo_City_Name", "Unknown")
        block = context.variables.get("Geo_Block_Name", "Unknown")
        start_year = context.variables.get("Temporal_Start_Year", "2020")
        end_year = context.variables.get("Temporal_End_Year", "2022")

        # 3. 构建 slide_state
        slide_state = YAMLExporter._build_slide_state(
            template_meta, context, city, block, start_year, end_year
        )

        # 4. 构建 slide_info
        slide_info = YAMLExporter._build_slide_info(slide_config, template_id)

        # 5. 组装完整数据
        yaml_data = {
            "slide_state": slide_state,
            "slide_info": slide_info,
        }

        # 6. 生成文件路径
        yaml_path = YAMLExporter._generate_yaml_path(
            output_file_path, city, block, template_id
        )

        # 7. 写入 YAML 文件
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(
                yaml_data,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=1000,
            )

        logger.info(f"已导出配置文件: {yaml_path}")
        return yaml_path

    @staticmethod
    def _build_slide_state(
        template_meta, context: PresentationContext, city: str, block: str,
        start_year: str, end_year: str
    ) -> list[dict]:
        """
        构建 slide_state 部分

        记录每个槽位的数据来源信息
        """
        slide_state = []
        function_keys = template_meta.function_keys

        # 获取表名（从 context 或默认值）
        # 注意：这里需要从 somewhere 获取表名
        # 暂时从变量中获取，或者使用默认值
        table_name = context.variables.get("_table_name", "unknown_table")

        for function_key in function_keys:
            state_entry = {
                "connection": {
                    "table": [table_name.lower()]
                },
                "select_columns": YAMLExporter._get_select_columns(function_key),
                "filters": {
                    "city": city,
                    "block": block,
                    "start_date": f"{start_year}-01-01",
                    "end_date": f"{end_year}-12-31",
                },
                "fun_tool": {
                    "fun": function_key
                },
            }
            slide_state.append(state_entry)

        return slide_state

    @staticmethod
    def _get_select_columns(function_key: str) -> list[str]:
        """根据 function_key 获取选择的列"""
        column_map = {
            "Supply-Transaction Unit Statistic": ["dim_area"],
            "Area x Price Cross Pivot": ["dim_area", "dim_price"],
            "Area Segment Distribution": ["dim_area"],
            "Price Segment Distribution": ["dim_price"],
        }
        return column_map.get(function_key, ["unknown_column"])

    @staticmethod
    def _build_slide_info(slide_config: SlideRenderConfig, template_id: str) -> dict:
        """
        构建 slide_info 部分

        记录幻灯片的尺寸和所有元素
        """
        # slide_size 是固定的：25.4 x 14.29 cm
        slide_info = {
            "slide_size": {
                "width": 25.4,
                "height": 14.29,
            },
            "elements": [],
        }

        # 遍历所有元素
        element_id = 1
        for element in slide_config.elements:
            element_dict = YAMLExporter._element_to_dict(element, element_id)
            slide_info["elements"].append(element_dict)
            element_id += 1

        return slide_info

    @staticmethod
    def _element_to_dict(element, element_id: int) -> dict:
        """将元素对象转换为字典"""
        element_dict = {
            "id": str(element_id),
        }

        # 根据元素类型提取信息
        if isinstance(element, TextElement):
            element_dict["type"] = "textBox"
            element_dict["role"] = element.role
            element_dict["text"] = element.text
            element_dict["layout"] = {
                "x": element.layout.left,
                "y": element.layout.top,
                "width": element.layout.width,
                "height": element.layout.height,
            }

        elif isinstance(element, (ChartElement, TableElement)):
            element_dict["type"] = "chart" if isinstance(element, ChartElement) else "table"
            element_dict["role"] = element.role
            element_dict["layout"] = {
                "x": element.layout.left,
                "y": element.layout.top,
                "width": element.layout.width,
                "height": element.layout.height,
            }

            # 添加图表参数（从 DataFrame 中推断）
            if isinstance(element, ChartElement):
                element_dict["args"] = YAMLExporter._extract_chart_args(element)

        return element_dict

    @staticmethod
    def _extract_chart_args(chart_element: ChartElement) -> list:
        """
        从图表元素中提取参数

        根据 DataFrame 的结构推断字段约束
        """
        df = chart_element.data_payload

        # 分析 DataFrame 结构
        if df.empty:
            return []

        # 获取索引名和列名
        index_name = df.index.name if df.index.name else "Unknown"
        columns = df.columns.tolist()

        # 根据 role 和数据结构推断参数
        # 这里需要根据实际情况构建参数
        # 暂时返回一个示例结构
        return [
            "field-constraint",
            [
                [index_name, ["index"], "{}-{}m²", "0", "200", "20"],
                columns,
                ["count"]
            ]
        ]

    @staticmethod
    def _generate_yaml_path(
        ppt_path: str | Path, city: str, block: str, template_id: str
    ) -> Path:
        """
        生成 YAML 文件路径

        与 PPT 文件在同一目录，文件名格式：
        CityBlock-templateid-random.yaml
        """
        ppt_path = Path(ppt_path)

        # 生成唯一 ID
        base_str = f"{city}{block}{template_id}"
        unique_id = md5(base_str.encode()).hexdigest()[:16]

        # 文件名
        safe_block = block.replace(" ", "").replace("/", "")
        yaml_filename = f"{city}{safe_block}-{template_id}-{unique_id}.yaml"

        # 与 PPT 同目录
        yaml_path = ppt_path.parent / yaml_filename

        return yaml_path
