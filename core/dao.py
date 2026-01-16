import pandas as pd
from loguru import logger

from .database import db_manager
from .schemas import QueryFilter


class RealEstateDAO:
    """
    Data Access Object
    职责：仅负责 SQL 执行和原始数据获取，没有任何业务计算逻辑。
    """

    def fetch_raw_data(  # noqa: S608
        self, filters: QueryFilter, columns: list[str] = None
    ) -> pd.DataFrame:
        col_str = ", ".join(columns) if columns else "*"

        # SQL 变得非常简单，没有 group by，没有 logic
        # 注意：虽然使用 f-string，但表名和列名来自配置，非用户输入，相对安全
        sql = f"""
            SELECT {col_str}
            FROM public.{filters.table_name}
            WHERE city = :city
              AND block = :block
              AND date_code >= :start_date
              AND date_code <= :end_date
        """  # nosec

        logger.debug(f"Executing Query on {filters.table_name}...")
        return db_manager.query(sql, filters.sql_params)
