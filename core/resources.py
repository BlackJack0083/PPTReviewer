from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Template
from loguru import logger

from config import setting

from .schemas import LayoutType


@dataclass
class TemplateMeta:
    """模板元数据 (由 YAML 驱动)"""

    uid: str
    layout_type: LayoutType
    style_config_id: str  # 对应 styles.yaml 的 Style
    theme_key: str  # 对应 text_pattern.yaml 的 Theme
    function_key: str | list[str]  # 支持单个或多个 function_key
    summary_item: int  # 对应 text_pattern.yaml 的 Summaries 索引
    data_keys: dict[str, str]  # 槽位名 -> 数据键名

    # 兼容性属性：保持向后兼容
    @property
    def function_keys(self) -> list[str]:
        """返回 function_key 列表，兼容单个和多个的情况"""
        if isinstance(self.function_key, str):
            return [self.function_key]
        return self.function_key

    @property
    def primary_function_key(self) -> str:
        """返回第一个 function_key（用于获取结论）"""
        return self.function_keys[0]


class ResourceManager:
    """
    静态资源管理器 (Singleton)
    统一负责加载：
    1. ppt模板定义 (Template Definitions)
    2. 文本模板 (Text Patterns)
    """

    _instance = None

    def __init__(self):
        self._templates: dict[str, TemplateMeta] = {}
        self._text_patterns: dict[str, Any] = {}
        self._is_loaded = False

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_template(self, meta: TemplateMeta) -> None:
        """
        显式填充一个模板元数据

        可以从任何来源（YAML, DB, API, 代码硬编码）添加模板，
        而不仅限于文件加载。
        """
        self._templates[meta.uid] = meta
        logger.debug(f"Registered template: {meta.uid}")

    def load_all(self):
        """一次性加载所有资源"""
        if self._is_loaded:
            return

        self._load_templates(setting.TEMPLATE_CONFIG_PATH)
        self._load_text_patterns(setting.TEXT_PATTERN_PATH)
        self._is_loaded = True
        logger.info("All static resources loaded.")

    def _load_templates(self, path: Path):
        if not path.exists():
            logger.error(f"Template config not found: {path}")
            return

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for item in data:
            try:
                meta = TemplateMeta(
                    uid=item["uid"],
                    layout_type=LayoutType(item["layout_type"]),
                    style_config_id=item["style_config_id"],
                    theme_key=item["theme_key"],
                    function_key=item["function_key"],
                    summary_item=item["summary_item"],
                    data_keys=item["data_keys"],
                )
                # 复用注册接口
                self.register_template(meta)
            except Exception as e:
                logger.warning(f"Failed to load template {item.get('uid')}: {e}")

    def get_template(self, uid: str) -> TemplateMeta | None:
        return self._templates.get(uid)

    @property
    def all_templates(self) -> dict[str, TemplateMeta]:
        return self._templates

    def _load_text_patterns(self, path: Path) -> None:
        if not path.exists():
            logger.warning(f"Text pattern config not found: {path}")
            return

        with open(path, encoding="utf-8") as f:
            # 加载 YAML 内容
            raw_data = yaml.safe_load(f)

        # 预编译 Jinja 模板
        for theme, content in raw_data.items():
            self._text_patterns[theme] = {}
            # 提取 slide_title，它不是一个模板
            slide_title = content.pop("slide_title", "")

            for func, func_content in content.items():
                self._text_patterns[theme][func] = {
                    "slide_title": slide_title,  # 从父级获取并保存
                    "chart_caption": Template(func_content.get("chart_caption", "")),
                    "summaries": [
                        Template(s) for s in func_content.get("summaries", [])
                    ],
                }

    def render_text(
        self,
        theme: str,
        func: str,
        part: str,
        context: dict[str, Any],
        variant_idx: int = 0,
    ) -> str:
        """渲染文本模板"""
        try:
            target = self._text_patterns[theme][func]

            if part == "slide_title":
                return target["slide_title"]
            elif part == "caption":
                return target["chart_caption"].render(**context)
            elif part == "summary":
                summaries = target["summaries"]
                if variant_idx >= len(summaries):
                    raise ValueError(f"Variant index out of range: {variant_idx}")
                return summaries[variant_idx].render(**context)

        except KeyError as e:
            logger.error(f"Text pattern not found: {theme} -> {func}")
            raise ValueError(f"Invalid text pattern: {theme} -> {func}") from e
        return ""


# 全局单例
resource_manager = ResourceManager.get_instance()
