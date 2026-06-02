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
    """Slots needed to identify the underlying real-estate data source."""

    table: str = Field(..., description="Database table name, e.g. beijing_new_house")
    city: str = Field(..., description="City slot extracted from the slide")
    block: str = Field(..., description="Block or district slot extracted from the slide")
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format")
    end_date: str = Field(..., description="End date in YYYY-MM-DD format")


class DataSourceQueryTool:
    """Validate data-source slots against the real estate database.

    The tool intentionally returns evidence only. The ReAct agent decides whether
    the slots are Missing, Error, Unmatch, or Correct.

    The default check is scoped to the selected table. Cross-table diagnosis is
    intentionally excluded because data-source verification only needs to know
    whether the current PPT state can retrieve data from its claimed source.
    """

    def __init__(self, database: Any = db_manager, tables: list[str] | None = None):
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
    """Build the LangChain tool exposed to the ReAct agent."""

    runner = query_tool or DataSourceQueryTool()

    def _tool(
        table: str,
        city: str,
        block: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """Validate table/city/block/time_range slots against the database."""

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
            "Validate PPT data-source slots against the real-estate database. "
            "Use this only after all required slots are non-empty."
        ),
        args_schema=DataSourceSlots,
    )


def _valid_date_order(start_date: str, end_date: str) -> bool:
    start = pd.to_datetime(start_date, errors="coerce")
    end = pd.to_datetime(end_date, errors="coerce")
    if pd.isna(start) or pd.isna(end):
        return False
    return bool(start <= end)
