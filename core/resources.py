import threading
from dataclasses import dataclass, field
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
    function_key: list[str]
    summary_item: int  # 对应 text_pattern.yaml 的 Summaries 索引
    data_keys: dict[str, str]  # 槽位名 -> 数据键名
    function_params: dict[str, Any] = field(default_factory=dict)
    summary_function_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.function_key, list) or not self.function_key:
            raise ValueError("function_key must be a non-empty list[str]")
        if not isinstance(self.function_params, dict):
            raise ValueError("function_params must be a dict[str, Any]")
        if self.summary_function_key is not None and not isinstance(
            self.summary_function_key, str
        ):
            raise ValueError("summary_function_key must be a str | None")


class ResourceManager:
    """
    静态资源管理器 (Singleton)
    统一负责加载：
    1. ppt模板定义 (Template Definitions)
    2. 文本模板 (Text Patterns)
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._templates: dict[str, TemplateMeta] = {}
        self._text_patterns: dict[str, Any] = {}
        self._is_loaded = False
        self._load_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ResourceManager":
        if cls._instance is None:
            with cls._instance_lock:
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

    def load_all(self) -> None:
        """一次性加载所有资源"""
        if self._is_loaded:
            return
        with self._load_lock:
            if self._is_loaded:
                return

            self._load_templates(setting.TEMPLATE_CONFIG_PATH)
            self._load_text_patterns(setting.TEXT_PATTERN_PATH)
            self._is_loaded = True
            logger.info("All static resources loaded.")

    def _load_templates(self, path: Path) -> None:
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
                    function_params=item.get("function_params", {}),
                    summary_function_key=item.get("summary_function_key"),
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
                    "raw_chart_caption": func_content.get("chart_caption", ""),
                    "summaries": [
                        Template(s) for s in func_content.get("summaries", [])
                    ],
                    "raw_summaries": list(func_content.get("summaries", [])),
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

    def get_summary_template(self, theme: str, func: str, variant_idx: int = 0) -> str:
        """获取原始 summary 模板字符串（未渲染）"""
        try:
            target = self._text_patterns[theme][func]
            summaries = target.get("raw_summaries", [])
            if variant_idx >= len(summaries):
                raise ValueError(f"Variant index out of range: {variant_idx}")
            return summaries[variant_idx]
        except KeyError as e:
            logger.error(f"Text pattern not found: {theme} -> {func}")
            raise ValueError(f"Invalid text pattern: {theme} -> {func}") from e

    def get_caption_template(self, theme: str, func: str) -> str:
        """获取原始 caption 模板字符串（未渲染）"""
        try:
            return self._text_patterns[theme][func]["raw_chart_caption"]
        except KeyError as e:
            logger.error(f"Text pattern not found: {theme} -> {func}")
            raise ValueError(f"Invalid text pattern: {theme} -> {func}") from e


# 全局单例
resource_manager = ResourceManager.get_instance()
