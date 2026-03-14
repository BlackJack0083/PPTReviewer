"""
YAML 导入器
根据 YAML 配置文件重建 PPT
"""
from pathlib import Path

import yaml
from loguru import logger

from common.function_specs import filter_function_args
from core import PPTOperations, PresentationContext, resource_manager
from core.data_provider import RealEstateDataProvider
from core.schemas import (
    BinningRule,
    ChartElement,
    LayoutModel,
    MetricRule,
    SlideRenderConfig,
    TableAnalysisConfig,
    TableElement,
    TextElement,
)
from engine.builder import SlideConfigBuilder
from engine.slide_renderers import RendererFactory


class YAMLImporter:
    """
    YAML 配置导入器
    负责从 YAML 配置文件加载数据并重建 PPT
    """

    @staticmethod
    def load_yaml(yaml_path: str | Path) -> dict:
        """加载 YAML 配置文件"""
        with open(yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    @staticmethod
    def resolve_template_id(yaml_data: dict, yaml_path: str | Path) -> str:
        """仅从 YAML meta 解析 template_id（单一 schema 模式）"""
        meta = yaml_data.get("meta", {})
        if not isinstance(meta, dict):
            raise ValueError(
                f"YAML missing 'meta' section: {yaml_path}. "
                "Expected meta.template_id."
            )

        template_id = meta.get("template_id")
        if not isinstance(template_id, str) or not template_id.strip():
            raise ValueError(
                f"YAML missing 'meta.template_id': {yaml_path}. "
                "Expected non-empty template_id."
            )
        return template_id.strip()

    @staticmethod
    def build_config_from_yaml(args_config: dict) -> TableAnalysisConfig:
        """从 YAML 中的 args 配置构建 TableAnalysisConfig"""
        dimensions = []
        for dim in args_config.get("dimensions", []):
            dimensions.append(
                BinningRule(
                    source_col=dim.get("source_col"),
                    target_col=dim.get("target_col"),
                    method=dim.get("method", "range"),
                    step=dim.get("step"),
                    format_str=dim.get("format_str"),
                    min=dim.get("min"),
                    max=dim.get("max"),
                )
            )

        metrics = []
        for metric in args_config.get("metrics", []):
            metrics.append(
                MetricRule(
                    name=metric.get("name"),
                    source_col=metric.get("source_col"),
                    agg_func=metric.get("agg_func"),
                    filter_condition=metric.get("filter_condition"),
                )
            )

        return TableAnalysisConfig(
            table_type=args_config.get("table_type", "field-constraint"),
            dimensions=dimensions,
            metrics=metrics,
        )

    @staticmethod
    def rebuild_from_yaml(
        yaml_path: str | Path,
        output_ppt_path: str | Path,
    ) -> None:
        """
        根据 YAML 配置文件重建 PPT

        Args:
            yaml_path: YAML 配置文件路径
            output_ppt_path: 输出 PPT 文件路径
        """
        # 1. 加载 YAML
        yaml_data = YAMLImporter.load_yaml(yaml_path)

        # 2. 解析基本信息
        query_filters = yaml_data.get("query_filters", {})
        slide_filters = yaml_data.get("slide_filters", [])
        template_slide = yaml_data.get("template_slide", {})

        # 3. 解析 template_id（单一 schema：meta.template_id）
        template_id = YAMLImporter.resolve_template_id(yaml_data, yaml_path)
        logger.info(f"Resolved template_id: {template_id}")

        # 4. 获取数据（支持多个 slide_filter，对应双栏图）
        if not slide_filters:
            raise ValueError("No slide_filters found in YAML")

        # 从 query_filters 获取城市、板块、时间范围
        city = query_filters.get("city", "Beijing")
        block = query_filters.get("block", "Unknown")
        start_year = query_filters.get("start_date", "2020-01-01")[:4]
        end_year = query_filters.get("end_date", "2022-12-31")[:4]

        # 获取 template_meta
        template_meta = resource_manager.get_template(template_id)
        if not template_meta:
            raise ValueError(f"Template not found: {template_id}")

        # 5. 创建 DataProvider 并获取所有数据
        logger.info(f"Fetching data: city={city}, block={block}")
        provider = RealEstateDataProvider(
            city=city,
            block=block,
            start_year=start_year,
            end_year=end_year,
            table_name="",  # 临时设为空，稍后从 slide_filter 获取
        )

        # 存储所有获取的数据
        all_data = []
        all_configs = []

        for idx, slide_filter in enumerate(slide_filters):
            # 获取表名
            connection = slide_filter.get("connection", {})
            table_name = connection.get("table", ["beijing_new_house"])[0]

            # 更新 provider 的表名
            provider.filter.table_name = table_name

            fun_tool = slide_filter.get("fun_tool", {})
            function_key = fun_tool.get("fun")
            fun_args = fun_tool.get("args", {})

            # 过滤参数
            valid_args = filter_function_args(function_key, fun_args)
            logger.info(f"[{idx+1}/{len(slide_filters)}] Calling {function_key} with args: {valid_args}")

            # 调用对应的数据方法
            df, _, config = provider.execute_by_function_key(
                function_key, **valid_args
            )
            logger.info(f"  -> Fetched data shape: {df.shape}")

            all_data.append(df)
            all_configs.append(config)

        # 6. 构建 PresentationContext（只需要基本变量，文字内容从 YAML 直接读取）
        context = PresentationContext()
        context.add_variable("Geo_City_Name", city)
        context.add_variable("Geo_Block_Name", block)
        context.add_variable("Temporal_Start_Year", start_year)
        context.add_variable("Temporal_End_Year", end_year)
        context.add_variable("_table_name", table_name)

        # 添加数据集和配置（支持多个）
        data_keys = list(template_meta.data_keys.values())
        for idx, (df, config) in enumerate(zip(all_data, all_configs, strict=False)):
            if idx < len(data_keys):
                data_key = data_keys[idx]
                context.add_dataset(data_key, df)
                if config:
                    context.add_config(data_key, config)

        # 7. 使用 Builder 构建 SlideConfig
        builder = SlideConfigBuilder()
        slide_config = builder.build(template_id, context)

        # 8. 手动渲染 PPT（简化版本）
        # 注意：这里需要手动创建元素，因为我们要从 YAML 的 template_slide 获取布局信息
        elements = []

        # 追踪图表/表格的索引（用于从 all_data 中获取对应数据）
        chart_idx = 0
        data_keys = list(template_meta.data_keys.values())

        # 8.1 从 template_slide 构建元素
        for elem_dict in template_slide.get("elements", []):
            elem_type = elem_dict.get("type")
            role = elem_dict.get("role")
            layout_dict = elem_dict.get("layout", {})

            layout = LayoutModel(
                left=layout_dict.get("x", 0),
                top=layout_dict.get("y", 0),
                width=layout_dict.get("width", 10),
                height=layout_dict.get("height", 5),
            )

            if elem_type == "textBox":
                text = elem_dict.get("text", "")
                elements.append(TextElement(role=role, text=text, layout=layout))

            elif elem_type == "chart":
                # 根据索引获取对应的数据
                if chart_idx < len(all_data) and chart_idx < len(data_keys):
                    chart_df = all_data[chart_idx]
                    chart_data_key = data_keys[chart_idx]
                    chart_config = all_configs[chart_idx] if chart_idx < len(all_configs) else None
                else:
                    # 降级处理：使用第一个数据
                    chart_df = all_data[0]
                    chart_data_key = data_keys[0] if data_keys else "data"
                    chart_config = all_configs[0] if all_configs else None

                # 从 args 获取配置
                args_config = elem_dict.get("args", {})
                final_config = YAMLImporter.build_config_from_yaml(args_config) if args_config else chart_config

                elements.append(
                    ChartElement(
                        role=role,
                        layout=layout,
                        data_key=chart_data_key,
                        data_payload=chart_df,
                        config=final_config,
                    )
                )
                chart_idx += 1

            elif elem_type == "table":
                # 表格使用第一个数据
                elements.append(
                    TableElement(
                        role=role,
                        layout=layout,
                        data_key=data_keys[0] if data_keys else "data",
                        data_payload=all_data[0] if all_data else None,
                    )
                )

        # 9. 生成 PPT
        # 获取 layout_type
        layout_type = template_meta.layout_type

        # 使用 PPTOperations 生成 PPT
        with PPTOperations(output_ppt_path) as ppt_ops:
            # 初始化一页
            ppt_ops.init_slides(1, layout_type=layout_type)

            # 获取渲染器
            renderer = RendererFactory.get_renderer(layout_type, ppt_ops)

            # 更新 slide_config 的元素
            slide_config = SlideRenderConfig(
                layout_type=layout_type,
                style_id=template_meta.style_config_id,
                elements=elements,
            )

            # 渲染
            renderer.render(slide_config, page_number=1)

        logger.success(f"PPT generated: {output_ppt_path}")


def rebuild_ppt_from_yaml(yaml_path: str, output_path: str | None = None) -> None:
    """
    便捷函数：根据 YAML 重建 PPT

    Args:
        yaml_path: YAML 配置文件路径
        output_path: 输出 PPT 路径（可选，默认与 YAML 同名 .pptx）
    """
    yaml_path = Path(yaml_path)

    if output_path is None:
        output_path = yaml_path.with_suffix(".pptx")
    else:
        output_path = Path(output_path)

    # 确保资源已加载
    resource_manager.load_all()

    YAMLImporter.rebuild_from_yaml(yaml_path, output_path)
