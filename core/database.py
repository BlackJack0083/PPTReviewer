import pandas as pd
from loguru import logger
from sqlalchemy import create_engine, text

from config import setting


class DatabaseManager:
    _instance = None

    def __init__(self):
        self.url = f"postgresql://{setting.SQL_USER}:{setting.SQL_PASSWORD}@{setting.SQL_HOST}:{setting.SQL_PORT}/{setting.SQL_DATABASE}"
        self.engine = create_engine(self.url)
        logger.info(f"Database engine initialized for host: {setting.SQL_HOST}")

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def query(self, sql: str, params: dict = None) -> pd.DataFrame:
        """
        执行 SQL 并返回 DataFrame
        使用 params 参数可以防止 SQL 注入
        """
        try:
            with self.engine.connect() as conn:
                # 使用 SQLAlchemy 的 text() 来安全绑定参数
                result = pd.read_sql(text(sql), conn, params=params)
            return result
        except Exception as e:
            logger.error(f"Query failed: {e}\nSQL: {sql}")
            raise


db_manager = DatabaseManager.get_instance()
