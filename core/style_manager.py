from pathlib import Path

import yaml
from loguru import logger
from pydantic import ValidationError

from config import setting

from .schemas import (
    BarChartConfig,
    LineChartConfig,
    TableConfig,
    TextStyleDefinition,
)


class StyleManager:
    """
    样式管理器：负责加载 styles.yaml 并提供样式配置对象
    """

    _instance = None

    def __init__(self):
        self._bar_styles: dict[str, BarChartConfig] = {}
        self._line_styles: dict[str, LineChartConfig] = {}
        self._table_styles: dict[str, TableConfig] = {}
        self._text_styles: dict[str, TextStyleDefinition] = {}
        self._is_loaded = False

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = cls()
        return cls._instance

    def load_styles_yaml(self, path: Path = None):
        """
        加载 styles.yaml 文件
        """
        if self._is_loaded:
            return

        config_path = path or (setting.TEMPLATE_DIR / "styles.yaml")

        if not config_path.exists():
            logger.error(f"styles.yaml not found in {config_path}")
            raise FileNotFoundError(f"styles.yaml not found in {config_path}")

        logger.info(f"Loading styles from {config_path}")

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # 1. 加载柱状图样式
        for key, config_dict in data.get("bar_configs", {}).items():
            try:
                # 利用 Pydantic 自动校验
                self._bar_styles[key] = BarChartConfig(**config_dict)
            except Exception as e:
                logger.error(f"Failed to load bar style '{key}': {e}")
                raise e

        # 2. 加载折线图样式
        for key, config_dict in data.get("line_configs", {}).items():
            try:
                self._line_styles[key] = LineChartConfig(**config_dict)
            except Exception as e:
                logger.error(f"Failed to load line style '{key}': {e}")
                raise e

        # 3. 加载表格样式
        for key, config_dict in data.get("table_configs", {}).items():
            try:
                self._table_styles[key] = TableConfig(**config_dict)
            except ValidationError as e:
                logger.error(f"Failed to load table style '{key}': {e}")
                raise e

        raw_text_configs = data.get("text_configs", {})
        for style_id, roles_dict in raw_text_configs.items():
            self._text_styles[style_id] = {}
            for role, config_dict in roles_dict.items():
                try:
                    self._text_styles[style_id][role] = TextStyleDefinition(
                        **config_dict
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to load text style '{style_id}' for role '{role}': {e}"
                    )
                    raise e

        self._is_loaded = True

    def get_bar_style(self, style_id: str) -> BarChartConfig:
        """获取柱状图样式，找不到则返回默认"""
        if not self._is_loaded:
            self.load_styles_yaml()

        style = self._bar_styles.get(style_id)
        if not style:
            logger.warning(f"Bar style '{style_id}' not found, using default.")
            raise ValueError(f"Bar style '{style_id}' not found, using default.")
        return style

    def get_line_style(self, style_id: str) -> LineChartConfig:
        """获取折线图样式，找不到则返回默认"""
        if not self._is_loaded:
            self.load_styles_yaml()

        style = self._line_styles.get(style_id)
        if not style:
            logger.warning(f"Line style '{style_id}' not found, using default.")
            raise ValueError(f"Line style '{style_id}' not found, using default.")
        return style

    def get_table_style(self, style_id: str) -> TableConfig:
        """获取表格样式，找不到则返回默认"""
        if not self._is_loaded:
            self.load_styles_yaml()

        style = self._table_styles.get(style_id)
        if not style:
            logger.warning(f"Table style '{style_id}' not found, using default.")
            raise ValueError(f"Table style '{style_id}' not found, using default.")
        return style

    def get_text_style(self, style_id: str, role: str) -> TextStyleDefinition:
        """
        获取文本样式配置
        """
        if not self._is_loaded:
            self.load_styles_yaml()

        # 1. 尝试获取指定 style_id
        style_group = self._text_styles.get(style_id)

        # 2. 回退到 default
        if not style_group:
            style_group = self._text_styles.get("default", {})

        style = style_group.get(role)

        # 3. 最后的兜底
        if not style:
            # logger.warning(f"No style found for {style_id}.{role}, using default.")
            return TextStyleDefinition()  # 返回默认值

        return style


# 单例导出
style_manager = StyleManager.get_instance()
