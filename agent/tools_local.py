import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.function_specs import get_default_function_args


def _normalize_table_name(table_name: str) -> str:
    """兼容大小写差异：guangzhou_new_house -> Guangzhou_new_house"""
    if "_" not in table_name:
        return table_name
    parts = table_name.split("_")
    if not parts:
        return table_name
    parts[0] = parts[0].capitalize()
    return "_".join(parts)


def _extract_template_vars(template_text: str) -> list[str]:
    pattern = r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}"
    return list(dict.fromkeys(re.findall(pattern, template_text)))


@dataclass
class ToolEvidence:
    template_id: str
    function_key: str
    city: str
    block: str
    start_year: str
    end_year: str
    table_name: str
    function_args: dict
    conclusion_vars: dict[str, str]
    expected_summary: str
    expected_summary_slots: dict[str, str]


class LocalDataTools:
    """本地低级工具（DB查询+统计），后续可替换为 MCP 实现。"""

    def __init__(self):
        # 延迟导入，避免脚本 --help 时触发数据库侧效应
        from core.resources import resource_manager

        resource_manager.load_all()
        self.resource_manager = resource_manager

    def list_template_ids(self) -> list[str]:
        return sorted(self.resource_manager.all_templates.keys())

    def list_table_names(self) -> list[str]:
        # 先给当前项目常用表，后续可动态读取 DB schema
        return [
            "Beijing_new_house",
            "Guangzhou_new_house",
            "Shenzhen_new_house",
            "Guangzhou_resale_house",
            "Shenzhen_resale_house",
        ]

    def available_tools(self) -> list[dict[str, Any]]:
        """ReAct 模式的中粒度工具定义清单。"""
        return [
            {"name": "resolve_plan", "args": ["template_id"]},
            {
                "name": "query_conclusion_vars",
                "args": ["city", "block", "start_year", "end_year", "table_name", "function_key", "function_args"],
            },
            {
                "name": "build_expected_summary",
                "args": ["template_id", "city", "block", "start_year", "end_year", "conclusion_vars"],
            },
        ]

    def resolve_plan(self, template_id: str) -> dict[str, Any]:
        """根据 template_id 生成数据查询与文本渲染计划。"""
        template_meta = self.resolve_template_meta(template_id)
        function_key = template_meta.primary_function_key
        return {
            "template_id": template_meta.uid,
            "theme_key": template_meta.theme_key,
            "summary_item": template_meta.summary_item,
            "function_key": function_key,
            "function_args": get_default_function_args(function_key),
        }

    def resolve_template_meta(self, template_id: str):
        template_meta = self.resource_manager.get_template(template_id)
        if template_meta is None:
            raise ValueError(f"Unknown template_id: {template_id}")
        return template_meta

    def resolve_function_key(self, template_id: str) -> str:
        template_meta = self.resolve_template_meta(template_id)
        return template_meta.primary_function_key

    def resolve_function_args(self, function_key: str) -> dict[str, Any]:
        return get_default_function_args(function_key)

    def query_conclusion_vars(
        self,
        city: str,
        block: str,
        start_year: str,
        end_year: str,
        table_name: str,
        function_key: str,
        function_args: dict[str, Any],
    ) -> dict[str, str]:
        # 延迟导入：保证 no_tool 模式和 --help 不依赖数据库初始化
        from core.data_provider import RealEstateDataProvider

        provider = RealEstateDataProvider(
            city=city,
            block=block,
            start_year=start_year,
            end_year=end_year,
            table_name=_normalize_table_name(table_name),
        )
        _df, conclusion_vars, _config = provider.execute_by_function_key(
            function_key, **function_args
        )
        return {str(k): str(v) for k, v in conclusion_vars.items()}

    def render_expected_summary(
        self,
        template_id: str,
        city: str,
        block: str,
        start_year: str,
        end_year: str,
        conclusion_vars: dict[str, str],
    ) -> str:
        template_meta = self.resolve_template_meta(template_id)
        function_key = template_meta.primary_function_key
        render_context = {
            "Geo_City_Name": city,
            "Geo_Block_Name": block,
            "Temporal_Start_Year": start_year,
            "Temporal_End_Year": end_year,
            **conclusion_vars,
        }
        return self.resource_manager.render_text(
            template_meta.theme_key,
            function_key,
            "summary",
            render_context,
            template_meta.summary_item,
        )

    def extract_expected_summary_slots(
        self,
        template_id: str,
        conclusion_vars: dict[str, str],
    ) -> dict[str, str]:
        template_meta = self.resolve_template_meta(template_id)
        summary_template = self.resource_manager.get_summary_template(
            template_meta.theme_key,
            template_meta.primary_function_key,
            template_meta.summary_item,
        )
        summary_template_vars = set(_extract_template_vars(summary_template))
        return {k: v for k, v in conclusion_vars.items() if k in summary_template_vars}

    def build_expected_summary(
        self,
        template_id: str,
        city: str,
        block: str,
        start_year: str,
        end_year: str,
        conclusion_vars: dict[str, str],
    ) -> dict[str, Any]:
        """组合输出 expected_summary + expected_summary_slots。"""
        expected_summary = self.render_expected_summary(
            template_id=template_id,
            city=city,
            block=block,
            start_year=start_year,
            end_year=end_year,
            conclusion_vars=conclusion_vars,
        )
        expected_summary_slots = self.extract_expected_summary_slots(
            template_id=template_id,
            conclusion_vars=conclusion_vars,
        )
        return {
            "expected_summary": expected_summary,
            "expected_summary_slots": expected_summary_slots,
        }

    def compute_evidence(
        self,
        template_id: str,
        city: str,
        block: str,
        start_year: str,
        end_year: str,
        table_name: str,
    ) -> ToolEvidence:
        template_meta = self.resolve_template_meta(template_id)
        function_key = self.resolve_function_key(template_id)
        function_args = self.resolve_function_args(function_key)
        conclusion_vars = self.query_conclusion_vars(
            city=city,
            block=block,
            start_year=start_year,
            end_year=end_year,
            table_name=table_name,
            function_key=function_key,
            function_args=function_args,
        )
        expected_summary = self.render_expected_summary(
            template_id=template_id,
            city=city,
            block=block,
            start_year=start_year,
            end_year=end_year,
            conclusion_vars=conclusion_vars,
        )
        summary_slots = self.extract_expected_summary_slots(template_id, conclusion_vars)

        return ToolEvidence(
            template_id=template_id,
            function_key=function_key,
            city=city,
            block=block,
            start_year=start_year,
            end_year=end_year,
            table_name=_normalize_table_name(table_name),
            function_args=function_args,
            conclusion_vars=conclusion_vars,
            expected_summary=expected_summary,
            expected_summary_slots=summary_slots,
        )


def image_path_from_yaml_path(dataset_root: Path, yaml_rel_path: str) -> Path:
    yaml_path = dataset_root / yaml_rel_path
    return yaml_path.with_name("slide.png")
