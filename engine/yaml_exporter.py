"""
YAML 导出器
在生成 PPT 时同步生成配置 YAML 文件
记录 query_filters, slide_filters, template_slide
"""

from hashlib import md5
from pathlib import Path

import yaml
from loguru import logger

from common.function_specs import get_default_function_args
from core import PresentationContext, resource_manager
from core.layout_manager import layout_manager
from core.schemas import ChartElement, SlideRenderConfig, TableElement, TextElement
from engine.data_files import write_dataframe_csv


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
        template_slide, data_exports = YAMLExporter._build_template_slide(slide_config)

        # 4. 构建模板元信息（供 YAML 导入重建时使用）
        meta = YAMLExporter._build_meta(template_meta, template_id)

        # 5. 组装 YAML 数据
        yaml_data = {
            "meta": meta,
            "query_filters": query_filters,
            "slide_filters": slide_filters,
            "template_slide": template_slide,
        }

        # 6. 生成文件路径并写入
        yaml_path = YAMLExporter._write_yaml(
            yaml_data,
            output_file_path,
            context.variables.get("Geo_City_Name", "Unknown"),
            context.variables.get("Geo_Block_Name", "Unknown"),
            template_id,
        )
        YAMLExporter._write_data_exports(yaml_path.parent, data_exports)

        logger.info(f"已导出配置文件: {yaml_path}")
        return yaml_path

    # ==================== 构建方法 ====================

    @staticmethod
    def _require_context_var(context: PresentationContext, key: str) -> str:
        """读取导出所需的上下文变量，缺失则直接报错。"""
        value = context.variables.get(key)
        if value is None:
            raise ValueError(f"Missing required context variable: {key}")
        return str(value)

    @staticmethod
    def _build_meta(template_meta, template_id: str) -> dict:
        """构建导入重建所需的最小元信息"""
        return {
            "template_id": template_id,
        }

    @staticmethod
    def _build_query_filters(context: PresentationContext) -> dict:
        """从 context 构建 query_filters"""
        return {
            "city": YAMLExporter._require_context_var(context, "Geo_City_Name"),
            "block": YAMLExporter._require_context_var(context, "Geo_Block_Name"),
            "start_date": f"{YAMLExporter._require_context_var(context, 'Temporal_Start_Year')}-01-01",
            "end_date": f"{YAMLExporter._require_context_var(context, 'Temporal_End_Year')}-12-31",
        }

    @staticmethod
    def _build_slide_filters(template_meta, context: PresentationContext) -> list[dict]:
        """构建 slide_filters（每个槽位对应一个过滤器）"""
        filters = []
        function_keys = template_meta.function_key
        data_keys = template_meta.data_keys
        table_name = YAMLExporter._require_context_var(context, "_table_name")
        city = YAMLExporter._require_context_var(context, "Geo_City_Name")
        block = YAMLExporter._require_context_var(context, "Geo_Block_Name")
        start_year = YAMLExporter._require_context_var(context, "Temporal_Start_Year")
        end_year = YAMLExporter._require_context_var(context, "Temporal_End_Year")
        params = context.variables.get("_function_params", {})

        # 遍历每个槽位
        for i, (_slot_name, data_key) in enumerate(data_keys.items()):
            if i >= len(function_keys):
                raise ValueError(
                    f"Missing function_key for slot index {i} in template {template_meta.uid}"
                )
            func_key = function_keys[i]

            # 从 context.configs 获取配置，提取需要查询的列
            config = context.get_config(data_key)
            if not config:
                raise ValueError(
                    f"Missing analysis config for data_key '{data_key}' in template {template_meta.uid}"
                )

            select_cols = []
            for dim in config.dimensions:
                if dim.source_col not in select_cols:
                    select_cols.append(dim.source_col)
            for metric in config.metrics:
                if metric.source_col not in select_cols:
                    select_cols.append(metric.source_col)

            # 根据 function_key 动态组装参数：
            # 以默认参数为底，再用 _function_params 中同名键覆盖
            fun_args = get_default_function_args(func_key)
            for key in list(fun_args.keys()):
                if key in params:
                    fun_args[key] = params[key]

            # 构建过滤器
            filter_entry = {
                "connection": {"table": [table_name.lower()]},
                "select_columns": select_cols,
                "filters": {
                    "city": city,
                    "block": block,
                    "start_date": f"{start_year}-01-01",
                    "end_date": f"{end_year}-12-31",
                },
                "fun_tool": {
                    "fun": func_key,
                    "args": fun_args,
                },
                "sql_query": [
                    f"SELECT {', '.join(select_cols)} FROM public.{table_name} "  # nosec B608
                    f"WHERE city = '{city}' "
                    f"AND block = '{block}' "
                    f"AND date_code >= '{start_year}-01-01' "
                    f"AND date_code <= '{end_year}-12-31'"
                ],
            }
            filters.append(filter_entry)

        return filters

    @staticmethod
    def _build_template_slide(
        slide_config: SlideRenderConfig,
    ) -> tuple[dict, list[tuple[str, object]]]:
        """构建 template_slide"""
        # 获取 slide 尺寸
        slide_size = layout_manager.get_slide_size(slide_config.layout_type.value)

        template_slide = {
            "slide_size": {
                "width": slide_size.width,
                "height": slide_size.height,
            },
            "elements": [],
        }

        # 遍历所有元素
        data_exports = []
        for i, element in enumerate(slide_config.elements, 1):
            elem_dict, data_payload = YAMLExporter._element_to_dict(element, i)
            template_slide["elements"].append(elem_dict)
            if data_payload is not None:
                data_exports.append((elem_dict["data"], data_payload))

        return template_slide, data_exports

    @staticmethod
    def _element_to_dict(element, element_id: int) -> tuple[dict, object | None]:
        """将元素对象转换为字典"""
        elem = {"id": str(element_id)}
        data_payload = None

        if isinstance(element, TextElement):
            elem.update(
                {
                    "type": "textBox",
                    "role": element.role,
                    "text": element.text,
                    "layout": {
                        "x": element.layout.left,
                        "y": element.layout.top,
                        "width": element.layout.width,
                        "height": element.layout.height,
                    },
                }
            )

        elif isinstance(element, ChartElement | TableElement):
            is_chart = isinstance(element, ChartElement)
            data_payload = element.data_payload
            elem.update(
                {
                    "type": "chart" if is_chart else "table",
                    "role": element.role,
                    "layout": {
                        "x": element.layout.left,
                        "y": element.layout.top,
                        "width": element.layout.width,
                        "height": element.layout.height,
                    },
                    "data": f"./data/element_{element_id}.csv",
                }
            )
            # 图表添加 args
            if is_chart:
                elem["args"] = YAMLExporter._build_chart_args(element)

        return elem, data_payload

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
    def _write_yaml(
        yaml_data: dict, ppt_path: str | Path, city: str, block: str, template_id: str
    ) -> Path:
        """生成 YAML 文件路径并写入"""
        ppt_path = Path(ppt_path)

        # 生成唯一 ID；仅用于文件名去重，不用于安全场景。
        unique_id = md5(  # noqa: S324  # nosec B324
            f"{city}{block}{template_id}".encode(),
            usedforsecurity=False,
        ).hexdigest()[:16]
        safe_block = block.replace(" ", "").replace("/", "")
        yaml_filename = f"{city}{safe_block}-{template_id}-{unique_id}.yaml"

        yaml_path = ppt_path.parent / yaml_filename
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

        return yaml_path

    @staticmethod
    def _write_data_exports(
        yaml_dir: Path,
        data_exports: list[tuple[str, object]],
    ) -> None:
        """Write chart/table display data files referenced by template_slide elements."""
        for rel_path, df in data_exports:
            path = Path(rel_path)
            if path.is_absolute():
                raise ValueError(f"Data path must be relative: {rel_path}")
            write_dataframe_csv(df, yaml_dir / path)
