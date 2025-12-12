import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Setting:
    BASE_DIR: Path = Path(__file__).parent.parent

    TEMPLATE_DIR: Path = BASE_DIR / "config" / "templates"

    TEMPLATE_CONFIG_PATH: Path = TEMPLATE_DIR / "template_definitions.yaml"
    TEXT_PATTERN_PATH: Path = TEMPLATE_DIR / "text_pattern.yaml"

    DEFAULT_FONT_NAME: str = "Arial"
    DEFAULT_CJK_FONT_NAME: str = "方正兰亭黑_GBK"  # 中文字体

    SQL_USER = os.getenv("SQL_USER")
    SQL_PASSWORD = os.getenv("SQL_PASSWORD")
    SQL_HOST = os.getenv("SQL_HOST")
    SQL_PORT = os.getenv("SQL_PORT")
    SQL_DATABASE = os.getenv("SQL_DB")


setting = Setting()
