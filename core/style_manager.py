from pathlib import Path

import yaml
from loguru import logger

from config import setting

from .schemas import BarChartConfig, LineChartConfig


class StyleManager:
    """
    样式管理器：负责加载 styles.yaml 并提供样式配置对象
    """

    _instance = None

    def __init__(self):
        self._bar_styles: dict[str, BarChartConfig] = {}
        self._line_styles: dict[str, LineChartConfig] = {}
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


# 单例导出
style_manager = StyleManager.get_instance()
