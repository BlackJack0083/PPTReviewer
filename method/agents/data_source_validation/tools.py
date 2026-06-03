"""仅供 `DataSourceValidationAgent` 使用的工具。

这个文件放在 `agent.py` 旁边，是为了明确：只有数据源验证 ReAct agent
可以直接调用数据库 slot 验证工具。工具只返回证据；Missing/Error/Unmatch/
Correct 的标签判断由 LLM agent 根据 prompt 完成。
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from core.database import db_manager

REAL_ESTATE_TABLES = [
    "beijing_new_house",
    "beijing_resale_house",
    "guangzhou_new_house",
    "guangzhou_resale_house",
    "shenzhen_new_house",
    "shenzhen_resale_house",
]


class DataSourceSlots(BaseModel):
    """定位底层房地产数据源所需的 slots。"""

    table: str = Field(..., description="Database table name, e.g. beijing_new_house")
    city: str = Field(..., description="City slot extracted from the slide")
    block: str = Field(..., description="Block or district slot extracted from the slide")
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format")
    end_date: str = Field(..., description="End date in YYYY-MM-DD format")


class DataSourceQueryTool:
    """用真实房地产数据库验证 data-source slots。

    该工具刻意只返回证据，不直接给出错误类型。ReAct agent 负责判断 slots 是
    Missing、Error、Unmatch 还是 Correct。

    默认检查只在当前 table 内进行。这里不做跨表诊断，因为 data-source 验证
    只需要判断当前 PPT 声称的数据源是否能检索到数据。
    """

    def __init__(self, database: Any = db_manager, tables: list[str] | None = None):
        """初始化数据库驱动的 data-source checker。

        Args:
            database: 暴露 `query(sql, params=None)` 的数据库适配器。
            tables: 可选的房地产数据表白名单。
        """
        self.database = database
        self.tables = list(tables or REAL_ESTATE_TABLES)
        self._existing_tables_cache: set[str] | None = None

    def run(
        self,
        table: str,
        city: str,
        block: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """检查 data-source slots 是否能从数据库中检索到行。

        Args:
            table: PPT 声称的数据库表名。
            city: PPT 声称的 city slot。
            block: PPT 声称的 block/district slot。
            start_date: PPT 声称的开始日期，格式为 `YYYY-MM-DD`。
            end_date: PPT 声称的结束日期，格式为 `YYYY-MM-DD`。

        Returns:
            供 ReAct prompt 使用的证据字典。计数被编码为 `0/1`，让 LLM 可以
            在不看到原始 SQL rows 的情况下判断 Missing/Error/Unmatch/Correct。
        """
        slots = {
            "table": table,
            "city": city,
            "block": block,
            "start_date": start_date,
            "end_date": end_date,
        }
        table_exists = self._table_exists(table)
        date_valid = _valid_date_order(start_date, end_date)

        table_city_rows = False
        table_block_rows = False
        table_city_block_rows = False
        full_scope_rows = False
        if table_exists:
            table_checks = self._table_scope_checks(
                table=table,
                city=city,
                block=block,
                start_date=start_date,
                end_date=end_date,
                include_time_range=date_valid,
            )
            table_city_rows = table_checks["table_city"]
            table_block_rows = table_checks["table_block"]
            table_city_block_rows = table_checks["table_city_block"]
            full_scope_rows = table_checks["full_scope"]

        return {
            "input_slots": slots,
            "single_slot_counts": {
                "table": int(table_exists),
                "city": int(table_city_rows),
                "block": int(table_block_rows),
                "time_range": int(date_valid),
            },
            "combination_counts": {
                "table_city": int(table_city_rows),
                "city_block": int(table_city_block_rows),
                "table_city_block": int(table_city_block_rows),
                "full_scope_rows": int(full_scope_rows),
            },
            "checks": {
                "table_exists": table_exists,
                "city_exists": table_city_rows,
                "block_exists": table_block_rows,
                "time_range_valid": date_valid,
                "table_city_matches": table_city_rows,
                "city_block_matches": table_city_block_rows,
                "table_city_block_matches": table_city_block_rows,
                "full_scope_has_data": full_scope_rows,
            },
        }

    def _table_exists(self, table: str) -> bool:
        return table in self._existing_tables()

    def _existing_tables(self) -> set[str]:
        if self._existing_tables_cache is not None:
            return self._existing_tables_cache

        allowed_tables = ", ".join(f"'{table}'" for table in self.tables)
        result = self.database.query(
            f"""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name IN ({allowed_tables})
            """,  # nosec - table names come from the static allowlist.
        )
        self._existing_tables_cache = {str(row["table_name"]) for _, row in result.iterrows()}
        return self._existing_tables_cache

    def _table_scope_checks(
        self,
        *,
        table: str,
        city: str,
        block: str,
        start_date: str,
        end_date: str,
        include_time_range: bool,
    ) -> dict[str, bool]:
        if table not in self.tables:
            return {
                "table_city": False,
                "table_block": False,
                "table_city_block": False,
                "full_scope": False,
            }
        full_scope_sql = (
            f"""
            EXISTS (
                SELECT 1
                FROM public.{table}
                WHERE city = :city
                  AND block = :block
                  AND date_code >= :start_date
                  AND date_code <= :end_date
                LIMIT 1
            )
            """
            if include_time_range
            else "FALSE"
        )
        result = self.database.query(
            f"""
            SELECT
                EXISTS (
                    SELECT 1
                    FROM public.{table}
                    WHERE city = :city
                    LIMIT 1
                ) AS table_city,
                EXISTS (
                    SELECT 1
                    FROM public.{table}
                    WHERE block = :block
                    LIMIT 1
                ) AS table_block,
                EXISTS (
                    SELECT 1
                    FROM public.{table}
                    WHERE city = :city AND block = :block
                    LIMIT 1
                ) AS table_city_block,
                {full_scope_sql} AS full_scope
            """,  # nosec - table name comes from the static allowlist.
            {
                "city": city,
                "block": block,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        if result.empty:
            return {
                "table_city": False,
                "table_block": False,
                "table_city_block": False,
                "full_scope": False,
            }
        row = result.iloc[0]
        return {
            "table_city": bool(row["table_city"]),
            "table_block": bool(row["table_block"]),
            "table_city_block": bool(row["table_city_block"]),
            "full_scope": bool(row["full_scope"]),
        }


def build_data_source_query_tool(
    query_tool: DataSourceQueryTool | None = None,
) -> StructuredTool:
    """构建暴露给 ReAct agent 的 LangChain StructuredTool。

    Args:
        query_tool: 可选的测试 runner。未提供时使用真实数据库驱动的
            `DataSourceQueryTool`。

    Returns:
        名为 `data_source_query_tool` 的 LangChain-compatible structured tool。
    """

    runner = query_tool or DataSourceQueryTool()

    def _tool(
        table: str,
        city: str,
        block: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """用数据库验证 table/city/block/time_range slots。"""

        return runner.run(
            table=table,
            city=city,
            block=block,
            start_date=start_date,
            end_date=end_date,
        )

    return StructuredTool.from_function(
        func=_tool,
        name="data_source_query_tool",
        description=(
            "用真实房地产数据库验证 PPT data-source slots。"
            "仅在所有 required slots 都非空后调用。"
        ),
        args_schema=DataSourceSlots,
    )


def _valid_date_order(start_date: str, end_date: str) -> bool:
    """判断两个日期能否解析，且 `start_date <= end_date`。"""
    start = pd.to_datetime(start_date, errors="coerce")
    end = pd.to_datetime(end_date, errors="coerce")
    if pd.isna(start) or pd.isna(end):
        return False
    return bool(start <= end)
