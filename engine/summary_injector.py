"""
Summary 槽位注入器

基于 YAML 中的 summary_binding 信息进行精确注入：
1. 保留 summary_slots_truth（真值槽位）不变
2. 仅更新 summary_slot_overrides（可注入槽位）
3. 重新渲染 summary，并覆盖 template_slide 对应文本元素
"""
from pathlib import Path

import yaml
from jinja2 import Template


class SummaryInjector:
    """Summary 槽位注入器"""

    @staticmethod
    def load_yaml(yaml_path: str | Path) -> dict:
        """加载 YAML 文件"""
        with open(yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    @staticmethod
    def save_yaml(data: dict, yaml_path: str | Path) -> None:
        """保存 YAML 文件"""
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=1000,
            )

    @staticmethod
    def inject_summary_slots(
        yaml_path: str | Path,
        slot_overrides: dict[str, str],
        output_yaml_path: str | Path | None = None,
    ) -> Path:
        """向 summary 可渲染槽位注入错误值并写回 YAML"""
        yaml_path = Path(yaml_path)
        data = SummaryInjector.load_yaml(yaml_path)

        summary_binding = data.get("summary_binding")
        if not isinstance(summary_binding, dict):
            raise ValueError("YAML missing 'summary_binding'")

        truth_slots = summary_binding.get("summary_slots_truth", {})
        if not isinstance(truth_slots, dict):
            raise ValueError("'summary_slots_truth' must be a dict")

        unknown_keys = [k for k in slot_overrides if k not in truth_slots]
        if unknown_keys:
            raise ValueError(
                f"Unknown summary slot(s): {unknown_keys}. "
                f"Available: {list(truth_slots.keys())}"
            )

        existing_overrides = summary_binding.get("summary_slot_overrides", {})
        if not isinstance(existing_overrides, dict):
            existing_overrides = {}

        merged_overrides = dict(existing_overrides)
        merged_overrides.update(slot_overrides)
        summary_binding["summary_slot_overrides"] = merged_overrides

        rendered_text = SummaryInjector.render_summary(summary_binding)
        target_role = summary_binding.get("target_text_role", "body-text")

        updated_count = SummaryInjector._update_text_element(
            data=data,
            target_role=target_role,
            new_text=rendered_text,
        )
        if updated_count == 0:
            raise ValueError(
                f"No textBox element found for role '{target_role}' in template_slide"
            )

        if output_yaml_path is None:
            output_yaml_path = yaml_path.with_name(f"{yaml_path.stem}-summary_injected.yaml")
        output_yaml_path = Path(output_yaml_path)
        output_yaml_path.parent.mkdir(parents=True, exist_ok=True)

        SummaryInjector.save_yaml(data, output_yaml_path)
        return output_yaml_path

    @staticmethod
    def inject_summary_and_rebuild_ppt(
        yaml_path: str | Path,
        slot_overrides: dict[str, str],
        output_yaml_path: str | Path | None = None,
        output_ppt_path: str | Path | None = None,
    ) -> tuple[Path, Path]:
        """注入 summary 槽位并用现有导入器重建 PPT"""
        from engine.yaml_importer import rebuild_ppt_from_yaml

        injected_yaml = SummaryInjector.inject_summary_slots(
            yaml_path=yaml_path,
            slot_overrides=slot_overrides,
            output_yaml_path=output_yaml_path,
        )

        if output_ppt_path is None:
            output_ppt_path = injected_yaml.with_suffix(".pptx")
        output_ppt_path = Path(output_ppt_path)
        output_ppt_path.parent.mkdir(parents=True, exist_ok=True)

        rebuild_ppt_from_yaml(str(injected_yaml), str(output_ppt_path))
        return injected_yaml, output_ppt_path

    @staticmethod
    def render_summary(summary_binding: dict) -> str:
        """根据 truth + overrides 渲染当前 summary 文本"""
        summary_template = summary_binding.get("summary_template")
        if not summary_template:
            raise ValueError("'summary_template' is required")

        truth_slots = summary_binding.get("summary_slots_truth", {})
        if not isinstance(truth_slots, dict):
            raise ValueError("'summary_slots_truth' must be a dict")

        fixed_context = summary_binding.get("summary_context_fixed", {})
        if not isinstance(fixed_context, dict):
            fixed_context = {}

        overrides = summary_binding.get("summary_slot_overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}

        render_slots = dict(truth_slots)
        render_slots.update(overrides)

        render_context = dict(fixed_context)
        render_context.update(render_slots)

        return Template(summary_template).render(**render_context)

    @staticmethod
    def _update_text_element(data: dict, target_role: str, new_text: str) -> int:
        """更新 template_slide 中指定 role 的 textBox 文本"""
        updated = 0
        elements = data.get("template_slide", {}).get("elements", [])
        for elem in elements:
            if elem.get("type") == "textBox" and elem.get("role") == target_role:
                elem["text"] = new_text
                updated += 1
        return updated
