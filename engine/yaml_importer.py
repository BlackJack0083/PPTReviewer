"""
YAML 导入器
根据 YAML 配置文件重建 PPT
"""
from pathlib import Path

import yaml
from loguru import logger

from core.schemas import SlideRenderConfig
from core import PPTOperations
from core import layout_manager
from engine.slide_renderers import RendererFactory
from core import PresentationContext, resource_manager
from core.data_provider import RealEstateDataProvider
from core.schemas import (
    BinningRule,
    ChartElement,
    LayoutModel,
    MetricRule,
    TableAnalysisConfig,
    TextElement,
)

from engine.builder import SlideConfigBuilder


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
    def parse_template_id(yaml_filename: str) -> str:
        """从 YAML 文件名解析 template_id

        例如: BeijingBeiguan-Luyuan-T01_Supply_Trans_Bar-3719fe5e4d378185.yaml
              -> T01_Supply_Trans_Bar
        """
        # 移除 .yaml 后缀
        name_without_ext = yaml_filename.replace(".yaml", "")
        # 按 - 分割，取最后一个之前的部分作为 template_id
        parts = name_without_ext.split("-")
        # 找到 Txx_ 开头的部分
        for part in parts:
            if part.startswith("T") and "_" in part:
                return part
        # 如果找不到，返回原名称的最后一部分
        return parts[-1] if parts else name_without_ext

    # 定义每个 function_key 需要的参数
    FUNCTION_KEY_PARAMS = {
        "Supply-Transaction Unit Statistic": {"area_range_size"},
        "Area x Price Cross Pivot": {"area_range_size", "price_range_size"},
        "Area Segment Distribution": {"area_range_size"},
        "Price Segment Distribution": {"price_range_size"},
    }

    @staticmethod
    def _filter_function_args(function_key: str, args: dict) -> dict:
        """过滤参数，只保留 function_key 需要的参数"""
        valid_params = YAMLImporter.FUNCTION_KEY_PARAMS.get(function_key, set())
        return {k: v for k, v in args.items() if k in valid_params}

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

        # 3. 从文件名解析 template_id
        yaml_filename = Path(yaml_path).name
        template_id = YAMLImporter.parse_template_id(yaml_filename)
        logger.info(f"Parsed template_id: {template_id}")

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
            valid_args = YAMLImporter._filter_function_args(function_key, fun_args)
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
        for idx, (df, config) in enumerate(zip(all_data, all_configs)):
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
                    ChartElement(  # 复用 ChartElement 作为表格容器
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
