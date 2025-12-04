from typing import Any

import yaml
from jinja2 import Template


class TextTemplateManager:
    def __init__(self, template_path: str):
        self.patterns = self._load(template_path)

    def _load(self, path: str):
        with open(path, encoding="utf-8") as f:
            # 加载原始 YAML
            data = yaml.safe_load(f)

        # 预编译 Jinja 模板以提升性能
        processed = {}
        for theme, content in data.items():
            processed[theme] = {}
            # 提取 slide_title，它不是一个模板
            slide_title = content.pop("slide_title")

            for func, func_content in content.items():
                # func_content 现在只包含 chart_caption 和 summaries
                processed[theme][func] = {
                    "slide_title": slide_title,  # 从父级获取并保存
                    "chart_caption": Template(func_content["chart_caption"]),
                    # 处理结论列表
                    "summaries": [Template(s) for s in func_content["summaries"]],
                }
        return processed

    def render(
        self,
        theme: str,
        func: str,
        part: str,
        context: dict[str, Any],
        variant_idx: int = 0,
    ) -> str:
        """
        theme: 大主题 Key
        func: 子功能 Key
        part: 'caption' 或 'summary'
        context: 变量字典
        variant_idx: 选择第几个结论变体
        """
        try:
            target = self.patterns[theme][func]
            if part == "caption":
                return target["chart_caption"].render(**context)
            elif part == "summary":
                summaries = target["summaries"]
                # 选择第几个结论变体，如果越界则报错
                if variant_idx >= len(summaries):
                    raise ValueError(f"Variant index out of range: {variant_idx}")
                return summaries[variant_idx].render(**context)
            elif part == "slide_title":
                return target["slide_title"]
        except KeyError as err:
            raise KeyError(f"Error: Template not found for {theme} -> {func}") from err
