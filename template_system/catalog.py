from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml
from loguru import logger


class LayoutType(str, Enum):
    """版式类型枚举"""

    SINGLE_COLUMN_BAR = "single_column_bar"
    SINGLE_COLUMN_LINE = "single_column_line"
    DOUBLE_COLUMN_BAR = "double_column_bar"
    DOUBLE_COLUMN_LINE = "double_column_line"
    SINGLE_COLUMN_TABLE = "single_column_table"


@dataclass
class TemplateMeta:
    """模板元数据 (由 YAML 驱动)"""

    uid: str
    layout_type: LayoutType
    theme_key: str  # 对应 text_pattern.yaml 的 Theme
    function_key: str  # 对应 text_pattern.yaml 的 Function
    summary_item: int  # 对应 text_pattern.yaml 的 Summaries 索引
    data_keys: dict[str, str]


# 全局存储
TEMPLATE_CATALOG: dict[str, TemplateMeta] = {}


# TODO: 加载模板需要改为从config导入
def load_templates(config_path: str = "resources/templates/template_definitions.yaml"):
    """从 YAML 加载所有模板定义"""
    global TEMPLATE_CATALOG
    path = Path(config_path)
    if not path.exists():
        logger.error(f"配置文件未找到: {path}")
        return

    with open(path, encoding="utf-8") as f:
        definitions = yaml.safe_load(f)

    TEMPLATE_CATALOG.clear()
    for item in definitions:
        try:
            meta = TemplateMeta(
                uid=item["uid"],
                layout_type=LayoutType(item["layout_type"]),  # 字符串转枚举
                theme_key=item["theme_key"],
                function_key=item["function_key"],
                summary_item=item["summary_item"],
                data_keys=item["data_keys"],
            )
            TEMPLATE_CATALOG[meta.uid] = meta
        except Exception as e:
            logger.error(f"加载模板 {item.get('uid')} 失败: {e}")

    logger.info(f"已加载 {len(TEMPLATE_CATALOG)} 个模板定义")


def get_template_by_id(template_id: str) -> TemplateMeta | None:
    return TEMPLATE_CATALOG.get(template_id)
