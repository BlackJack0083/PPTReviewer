import pandas as pd
from loguru import logger
from sqlalchemy import create_engine, text

from config import setting

DATABASE_URL = (
    f"postgresql://{setting.SQL_USER}:{setting.SQL_PASSWORD}"
    f"@{setting.SQL_HOST}:{setting.SQL_PORT}/{setting.SQL_DATABASE}"
)
engine = create_engine(DATABASE_URL)
logger.info(f"Method database engine initialized for host: {setting.SQL_HOST}")


def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    """执行 SQL 查询。

    Args:
        sql: SQL 文本，动态值必须通过 `params` 绑定。
        params: SQLAlchemy 参数字典。

    Returns:
        查询结果 dataframe。
    """
    try:
        with engine.connect() as conn:
            return pd.read_sql(text(sql), conn, params=params)
    except Exception as exc:
        logger.error(f"Method query failed: {exc}\nSQL: {sql}")
        raise
