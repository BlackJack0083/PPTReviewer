from pathlib import Path

import yaml
from loguru import logger

from config import setting

from .schemas import GlobalLayoutConfig, LayoutModel, SlotDefinition


class LayoutManager:
    """
    版式管理器，加载 layouts.yaml 文件，并提供坐标查询
    """

    _instance = None

    def __init__(self) -> None:
        self._config: GlobalLayoutConfig | None = None

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = cls()
        return cls._instance

    def load_config(self, config_path: Path = None) -> None:
        """
        加载 layouts.yaml 文件
        """
        config_path = config_path or (setting.TEMPLATE_DIR / "layouts.yaml")

        if not config_path.exists():
            raise FileNotFoundError(f"layouts.yaml not found in {config_path}")

        logger.info(f"Loading layouts config from {config_path}")

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            self._config = GlobalLayoutConfig(**data)

    def get_layout_slots(self, layout_type: str) -> list[SlotDefinition]:
        """获取指定版式的所有槽位配置"""
        if not self._config:
            self.load_config()

        layout = self._config.layouts.get(layout_type)
        if not layout:
            logger.warning(
                f"Undefined layout type: {layout_type}, returning empty slots."
            )
            return []
        return layout.slots

    def get_common_layout(self, element_name: str) -> LayoutModel:
        """获取公共版式的元素配置: 包括 title, caption, textbox"""
        if not self._config:
            self.load_config()

        layout = self._config.common.get(element_name)
        if not layout:
            logger.warning(
                f"Undefined common element: {element_name}, returning empty layout."
            )
            raise ValueError(f"Undefined common element: {element_name}")
        return layout


layout_manager = LayoutManager.get_instance()
