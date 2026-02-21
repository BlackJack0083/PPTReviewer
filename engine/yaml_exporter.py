"""
YAML 导出器
在生成 PPT 时同步生成配置 YAML 文件
记录 query_filters, slide_filters, template_slide
"""
from hashlib import md5
from pathlib import Path

import yaml
from loguru import logger

from core import PresentationContext, resource_manager
from core.layout_manager import layout_manager
from core.schemas import ChartElement, SlideRenderConfig, TableElement, TextElement


class YAMLExporter:
    """
    YAML 配置导出器
    负责将 SlideConfig 和 Context 导出为 YAML 文件
    """

    # 定义每个 function_key 需要的参数
    FUNCTION_KEY_PARAMS = {
        "Supply-Transaction Unit Statistic": {"area_range_size"},
        "Area x Price Cross Pivot": {"area_range_size", "price_range_size"},
        "Area Segment Distribution": {"area_range_size"},
        "Price Segment Distribution": {"price_range_size"},
    }

    @staticmethod
    def export_slide_config(
        slide_config: SlideRenderConfig,
        context: PresentationContext,
        template_id: str,
        output_file_path: str | Path,
    ) -> Path:
        """导出 SlideConfig 为 YAML 文件"""
        template_meta = resource_manager.get_template(template_id)
        if not template_meta:
            logger.warning(f"无法找到模板元数据: {template_id}")
            return None

        # 1. 构建 query_filters（来自 context）
        query_filters = YAMLExporter._build_query_filters(context)

        # 2. 构建 slide_filters（来自 template_meta + context）
        slide_filters = YAMLExporter._build_slide_filters(template_meta, context)

        # 3. 构建 template_slide（来自 slide_config）
        template_slide = YAMLExporter._build_template_slide(slide_config)

        # 4. 组装 YAML 数据
        yaml_data = {
            "query_filters": query_filters,
            "slide_filters": slide_filters,
            "template_slide": template_slide,
        }

        # 5. 生成文件路径并写入
        yaml_path = YAMLExporter._write_yaml(
            yaml_data, output_file_path,
            context.variables.get("Geo_City_Name", "Unknown"),
            context.variables.get("Geo_Block_Name", "Unknown"),
            template_id
        )

        logger.info(f"已导出配置文件: {yaml_path}")
        return yaml_path

    # ==================== 构建方法 ====================

    @staticmethod
    def _build_query_filters(context: PresentationContext) -> dict:
        """从 context 构建 query_filters"""
        vars = context.variables
        return {
            "city": vars.get("Geo_City_Name", "Unknown"),
            "block": vars.get("Geo_Block_Name", "Unknown"),
            "project": vars.get("project", "default"),
            "start_date": f"{vars.get('Temporal_Start_Year', '2020')}-01-01",
            "end_date": f"{vars.get('Temporal_End_Year', '2022')}-12-31",
            "area_range_size": vars.get("area_range_size", 20),
            "price_range_size": vars.get("price_range_size", 1),
        }

    @staticmethod
    def _build_slide_filters(template_meta, context: PresentationContext) -> list[dict]:
        """构建 slide_filters（每个槽位对应一个过滤器）"""
        filters = []
        function_keys = template_meta.function_keys
        data_keys = template_meta.data_keys
        vars = context.variables

        # 从 context 获取表名
        table_name = vars.get("_table_name", "unknown_table")

        # 遍历每个槽位
        for i, (slot_name, data_key) in enumerate(data_keys.items()):
            # 获取对应的 function_key
            func_key = function_keys[i] if i < len(function_keys) else function_keys[0]

            # 从 context.configs 获取配置，提取需要查询的列
            config = context.get_config(data_key)
            select_cols = []
            if config:
                # 从 dimensions 和 metrics 获取列名
                for dim in config.dimensions:
                    if dim.source_col not in select_cols:
                        select_cols.append(dim.source_col)
                for metric in config.metrics:
                    if metric.source_col not in select_cols:
                        select_cols.append(metric.source_col)
            else:
                # 如果没有配置，使用默认列
                select_cols = ["dim_area"]

            # 获取实际参数值
            params = vars.get("_function_params", {})

            # 根据 function_key 筛选需要的参数
            valid_params = YAMLExporter.FUNCTION_KEY_PARAMS.get(func_key, set())
            fun_args = {}
            if "area_range_size" in valid_params:
                fun_args["area_range_size"] = params.get("area_range_size", 20)
            if "price_range_size" in valid_params:
                fun_args["price_range_size"] = params.get("price_range_size", 1)

            # 构建过滤器
            filter_entry = {
                "connection": {"table": [table_name.lower()]},
                "select_columns": select_cols,
                "filters": {
                    "city": vars.get("Geo_City_Name", "Unknown"),
                    "block": vars.get("Geo_Block_Name", "Unknown"),
                    "start_date": f"{vars.get('Temporal_Start_Year', '2020')}-01-01",
                    "end_date": f"{vars.get('Temporal_End_Year', '2022')}-12-31",
                },
                "fun_tool": {
                    "fun": func_key,
                    "args": fun_args,
                },
                "sql_query": [
                    f"SELECT {', '.join(select_cols)} FROM public.{table_name} "
                    f"WHERE city = '{vars.get('Geo_City_Name', 'Unknown')}' "
                    f"AND block = '{vars.get('Geo_Block_Name', 'Unknown')}' "
                    f"AND date_code >= '{vars.get('Temporal_Start_Year', '2020')}-01-01' "
                    f"AND date_code <= '{vars.get('Temporal_End_Year', '2022')}-12-31'"
                ],
            }
            filters.append(filter_entry)

        return filters

    @staticmethod
    def _build_template_slide(slide_config: SlideRenderConfig) -> dict:
        """构建 template_slide"""
        # 获取 slide 尺寸
        layout_type = slide_config.layout_type.value if hasattr(slide_config.layout_type, 'value') else slide_config.layout_type
        slide_size = layout_manager.get_slide_size(layout_type)

        template_slide = {
            "slide_size": {
                "width": slide_size.width,
                "height": slide_size.height,
            },
            "elements": [],
        }

        # 遍历所有元素
        for i, element in enumerate(slide_config.elements, 1):
            elem_dict = YAMLExporter._element_to_dict(element, i)
            template_slide["elements"].append(elem_dict)

        return template_slide

    @staticmethod
    def _element_to_dict(element, element_id: int) -> dict:
        """将元素对象转换为字典"""
        elem = {"id": str(element_id)}

        if isinstance(element, TextElement):
            elem.update({
                "type": "textBox",
                "role": element.role,
                "text": element.text,
                "layout": {
                    "x": element.layout.left,
                    "y": element.layout.top,
                    "width": element.layout.width,
                    "height": element.layout.height,
                }
            })

        elif isinstance(element, (ChartElement, TableElement)):
            is_chart = isinstance(element, ChartElement)
            elem.update({
                "type": "chart" if is_chart else "table",
                "role": element.role,
                "layout": {
                    "x": element.layout.left,
                    "y": element.layout.top,
                    "width": element.layout.width,
                    "height": element.layout.height,
                }
            })
            # 图表添加 args
            if is_chart:
                elem["args"] = YAMLExporter._build_chart_args(element)

        return elem

    @staticmethod
    def _build_chart_args(chart_element: ChartElement) -> dict:
        """从图表元素构建 args 参数

        使用 ChartElement.config（TableAnalysisConfig）转换为字典格式
        """
        if not chart_element.config:
            raise ValueError(
                f"ChartElement.config is required for YAML export. "
                f"Element role: {chart_element.role}"
            )
        return YAMLExporter._config_to_dict(chart_element.config)

    @staticmethod
    def _config_to_dict(config) -> dict:
        """将 TableAnalysisConfig 转换为字典格式"""
        if not config:
            return {}

        result = {
            "table_type": config.table_type,
            "dimensions": [],
            "metrics": [],
        }

        # 转换 dimensions
        for dim in config.dimensions:
            dim_dict = {
                "source_col": dim.source_col,
                "target_col": dim.target_col,
                "method": dim.method,
            }
            if dim.step:
                dim_dict["step"] = dim.step
            if dim.format_str:
                dim_dict["format_str"] = dim.format_str
            if dim.min is not None:
                dim_dict["min"] = dim.min
            if dim.max is not None:
                dim_dict["max"] = dim.max
            if dim.time_granularity:
                dim_dict["time_granularity"] = dim.time_granularity
            result["dimensions"].append(dim_dict)

        # 转换 metrics
        for metric in config.metrics:
            metric_dict = {
                "name": metric.name,
                "source_col": metric.source_col,
                "agg_func": metric.agg_func,
            }
            if metric.filter_condition:
                metric_dict["filter_condition"] = metric.filter_condition
            result["metrics"].append(metric_dict)

        return result

    @staticmethod
    def _write_yaml(yaml_data: dict, ppt_path: str | Path, city: str, block: str, template_id: str) -> Path:
        """生成 YAML 文件路径并写入"""
        ppt_path = Path(ppt_path)

        # 生成唯一 ID
        unique_id = md5(f"{city}{block}{template_id}".encode()).hexdigest()[:16]
        safe_block = block.replace(" ", "").replace("/", "")
        yaml_filename = f"{city}{safe_block}-{template_id}-{unique_id}.yaml"

        yaml_path = ppt_path.parent / yaml_filename
        yaml_path.parent.mkdir(parents=True, exist_ok=True)

        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=1000)

        return yaml_path
