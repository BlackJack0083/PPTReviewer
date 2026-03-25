import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.function_specs import get_default_function_args

_TEMPLATE_VAR_PATTERN = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")
_NON_ALNUM_PATTERN = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)

# 用户自定义外显 template_id（给 agent 看）
# key: 原始 canonical template_id
# value: 外显 alias（建议唯一、清晰）
TEMPLATE_ID_ALIASES: dict[str, str] = {
    "T01_Supply_Trans_Bar": "Block Supply_Transaction Unit Statistic Bar Chart",
    "T01_Supply_Trans_Line": "Block Supply_Transaction Unit Statistic Line Chart",
    "T02_Cross_Pivot_Table": "New-House Cross-Structure Analysis Table",
    "T02_Area_Dist_Bar": "New-House Cross-Structure Area Analysis Bar Chart",
    "T02_Area_Dist_Line": "New-House Cross-Structure Area Analysis Line Chart",
    "T02_Price_Dist_Bar": "New-House Cross-Structure Price Analysis Bar Chart",
    "T02_Price_Dist_Line": "New-House Cross-Structure Price Analysis Line Chart",
    "T02_Double_Price_Dist_Line": "New-House Cross-Structure Price Analysis Double Line Chart",
    "T02_Double_Price_Dist_Bar": "New-House Cross-Structure Price Analysis Double Bar Chart",
    "T04_Annual_Supply_Demand_Bar": "New-House Annual Supply_Demand Analysis Bar Chart",
    "T04_Annual_Supply_Demand_Line": "New-House Annual Supply_Demand Analysis Line Chart",
    "T04_Supply_Transaction_Area_Line": "New-House Supply_Transaction Area Analysis Line Chart",
    "T04_Supply_Transaction_Area_Bar": "New-House Supply_Transaction Area Analysis Bar Chart",
}


def _normalize_table_name(table_name: str) -> str:
    """兼容大小写差异：guangzhou_new_house -> Guangzhou_new_house"""
    head, sep, tail = table_name.partition("_")
    if not sep:
        return table_name
    return f"{head.capitalize()}_{tail}"


def _extract_template_vars(template_text: str) -> list[str]:
    return list(dict.fromkeys(_TEMPLATE_VAR_PATTERN.findall(template_text)))


def _normalize_identifier(text: str) -> str:
    return _NON_ALNUM_PATTERN.sub("", str(text).strip().lower())


def _default_text_edit_yaml_path(yaml_path: Path) -> Path:
    return yaml_path.with_name(f"{yaml_path.stem}-text_edited.yaml")


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


@dataclass
class EditAction:
    shape_id: str | None
    updated_summary: str | None
    execution_success: bool | None = None


class LocalDataTools:
    """本地低级工具（DB查询+统计），后续可替换为 MCP 实现。"""

    def __init__(self):
        # 延迟导入，避免脚本 --help 时触发数据库侧效应
        from core.resources import resource_manager

        resource_manager.load_all()
        self.resource_manager = resource_manager
        self._canonical_template_ids = sorted(self.resource_manager.all_templates.keys())
        self._canonical_to_exposed = self._build_canonical_to_exposed_map()  # 载入别名
        self._alias_to_canonical = self._build_alias_to_canonical_map()
        self._runtime_context = threading.local()

    def list_template_ids(self) -> list[str]:
        """返回给 agent 的模板 ID 列表（优先使用用户定义 alias）。"""
        return [self._canonical_to_exposed[t] for t in self._canonical_template_ids]

    def list_canonical_template_ids(self) -> list[str]:
        return list(self._canonical_template_ids)

    def normalize_template_id(self, template_id: str) -> str:
        """将 alias / 外显 ID / 原始 ID 统一映射为 canonical template_id。"""
        raw = str(template_id).strip()
        if raw in self.resource_manager.all_templates:
            return raw
        return self._alias_to_canonical.get(_normalize_identifier(raw), raw)

    def _build_canonical_to_exposed_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for canonical in self._canonical_template_ids:
            alias = TEMPLATE_ID_ALIASES.get(canonical, canonical)
            alias = str(alias).strip()
            mapping[canonical] = alias
        return mapping

    def _build_alias_to_canonical_map(self) -> dict[str, str]:
        """
        将别名映射回原本 template id
        """
        
        alias_bucket: dict[str, set[str]] = {}

        def add_alias(alias_text: str, canonical: str) -> None:
            key = _normalize_identifier(alias_text)
            if key:
                alias_bucket.setdefault(key, set()).add(canonical)

        for canonical, exposed in self._canonical_to_exposed.items():
            add_alias(canonical, canonical)
            add_alias(exposed, canonical)

        # 仅接受唯一映射，避免 alias 冲突误路由
        return {
            alias: next(iter(targets))
            for alias, targets in alias_bucket.items()
            if len(targets) == 1
        }

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
            {"name": "list_editable_textboxes", "args": []},
            {"name": "apply_textbox_edit", "args": ["shape_id", "new_text"]},
        ]

    def set_runtime_yaml_path(self, yaml_path: str | Path) -> None:
        self._runtime_context.yaml_path = str(Path(yaml_path))

    def clear_runtime_yaml_path(self) -> None:
        if hasattr(self._runtime_context, "yaml_path"):
            del self._runtime_context.yaml_path

    def _resolve_runtime_yaml_path(self, yaml_path: str | Path | None) -> Path:
        if yaml_path is not None:
            return Path(yaml_path)
        runtime_yaml_path = getattr(self._runtime_context, "yaml_path", None)
        if runtime_yaml_path:
            return Path(runtime_yaml_path)
        raise ValueError("Missing yaml_path for text edit operation.")

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
        # 将别名template_id 映射为原始 template_id
        template_id = self.normalize_template_id(template_id)
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
            table_name=table_name,
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

    def list_editable_textboxes(
        self,
        yaml_path: str | Path | None = None,
    ) -> list[dict[str, str]]:
        """
        列出 YAML 中当前页可编辑的 textBox。

        供 runtime 在调用 agent 前组织上下文时使用。
        """
        from engine.summary_injector import SummaryInjector

        resolved_yaml_path = self._resolve_runtime_yaml_path(yaml_path)
        data = SummaryInjector.load_yaml(resolved_yaml_path)
        elements = data.get("template_slide", {}).get("elements", [])
        editable_shapes: list[dict[str, str]] = []

        for elem in elements:
            if elem.get("type") != "textBox":
                continue
            editable_shapes.append(
                {
                    "shape_id": str(elem.get("id", "")).strip(),
                    "role": str(elem.get("role", "")).strip(),
                    "text": str(elem.get("text", "")),
                }
            )

        return [shape for shape in editable_shapes if shape["shape_id"]]

    def apply_textbox_edit(
        self,
        shape_id: str,
        new_text: str,
        yaml_path: str | Path | None = None,
        output_yaml_path: str | Path | None = None,
        output_ppt_path: str | Path | None = None,
    ) -> bool:
        """
        修改单个 textBox 的文本，并基于更新后的 YAML 重新渲染 PPT。

        说明：
        - `yaml_path` 由 workflow/runtime 持有并隐式注入。
        - agent 只需要关心 `shape_id` 和 `new_text`。
        """
        from engine.summary_injector import SummaryInjector
        from engine.yaml_importer import rebuild_ppt_from_yaml

        yaml_path = self._resolve_runtime_yaml_path(yaml_path)
        output_yaml = Path(output_yaml_path) if output_yaml_path else _default_text_edit_yaml_path(yaml_path)
        output_ppt = Path(output_ppt_path) if output_ppt_path else output_yaml.with_suffix(".pptx")

        data = SummaryInjector.load_yaml(yaml_path)
        elements = data.get("template_slide", {}).get("elements", [])
        target_shape_id = str(shape_id).strip()
        updated = False

        for elem in elements:
            if elem.get("type") != "textBox":
                continue
            if str(elem.get("id", "")).strip() != target_shape_id:
                continue
            elem["text"] = str(new_text)
            updated = True
            break

        if not updated:
            raise ValueError(f"TextBox shape_id not found: {target_shape_id}")

        output_yaml.parent.mkdir(parents=True, exist_ok=True)
        output_ppt.parent.mkdir(parents=True, exist_ok=True)
        SummaryInjector.save_yaml(data, output_yaml)
        rebuild_ppt_from_yaml(str(output_yaml), str(output_ppt))
        return True


def image_path_from_yaml_path(dataset_root: Path, yaml_rel_path: str) -> Path:
    yaml_path = dataset_root / yaml_rel_path
    return yaml_path.with_name("slide.png")
