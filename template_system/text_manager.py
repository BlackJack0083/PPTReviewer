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
        for theme, funcs in data.items():
            processed[theme] = {}
            for func, content in funcs.items():
                processed[theme][func] = {
                    "title": Template(content["title"]),
                    # 处理结论列表
                    "summaries": [Template(s) for s in content["summaries"]],
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
        part: 'title' 或 'summary'
        context: 变量字典
        variant_idx: 选择第几个结论变体
        """
        try:
            target = self.patterns[theme][func]
            if part == "title":
                return target["title"].render(**context)
            elif part == "summary":
                summaries = target["summaries"]
                # 循环取模，防止越界
                return summaries[variant_idx % len(summaries)].render(**context)
        except KeyError as err:
            raise KeyError(f"Error: Template not found for {theme} -> {func}") from err


# 初始化单例
text_manager = TextTemplateManager("template_system/text_pattern.yaml")
