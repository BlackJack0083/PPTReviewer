# core/data_provider.py
import re
from typing import Any

import pandas as pd
from loguru import logger

from .conclusion_generator import ConclusionGenerator
from .dao import RealEstateDAO
from .schemas import QueryFilter
from .transformers import StatTransformer


class RealEstateDataProvider:
    """
    Facade Layer
    职责：协调 DAO 获取数据，并调用 Transformer 加工数据。
    它是 Context 唯一需要交互的对象。
    """

    def __init__(
        self, city: str, block: str, start_year: str, end_year: str, table_name: str
    ):
        # 初始化 Filter 对象
        self.filter = QueryFilter(
            city=city,
            block=block,
            start_date=f"{start_year}-01-01",
            end_date=f"{end_year}-12-31",
            table_name=table_name,
        )
        self.dao = RealEstateDAO()

        # 初始化结论生成器
        self.conclusion_gen = ConclusionGenerator(start_year, end_year, block)

        self.transformer = StatTransformer()

    def get_supply_transaction_stats(self, area_range_size: int = 20) -> pd.DataFrame:
        # 1. 获取原料 (IO Bound)
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_area", "supply_sets", "trade_sets"]
        )

        analysis_config = [
            "field-constraint",
            [["Supply Count", "Sales Count"], ["area_range", "{}-{}m²", "20"]],
            [["dim_area", "supply_sets"], ["dim_area", "trade_sets"]],
            ["count", "count"],
        ]

        # 2. 加工产品 (CPU Bound)
        result_df = self.transformer.process_data_pipeline(raw_data=raw_df, options=analysis_config)
        return result_df

    def get_area_price_cross_stats(
        self, area_step: int = 20, price_step: int = 1
    ) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(self.filter, columns=["dim_area", "dim_price"])

        analysis_config = [
            "cross-constraint",
            [["area_range", "{}-{}m²", 10], ["price_range", "{}-{}M", 1]],
            ["dim_price", "dim_area"],
            ["count"],
        ]

        # 2. 加工产品
        result_df = self.transformer.process_data_pipeline(raw_data=raw_df, options=analysis_config)
        return result_df

    def get_area_distribution_stats(
        self, step: int = 20, unit: str = "m²"
    ) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_area", "trade_sets"]
        )
        analysis_config = [
            "field-constraint",
            [["Area Rng Stats"], ["area_range", "{}-{}m²", 10]],
            ["dim_area", "trade_sets"],
            ["count"],
        ]

        # 2. 加工产品
        result_df = self.transformer.process_data_pipeline(raw_data=raw_df, options=analysis_config)
        return result_df

    def get_price_distribution_stats(self, price_range_size: int = 1) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_price", "trade_sets"]
        )

        analysis_config = [
            "field-constraint",
            [["Price Rng Stats"], ["price_range", "{}-{}M", "1"]],
            ["dim_price", "trade_sets"],
            ["count"],
        ]

        # 2. 加工产品
        result_df = self.transformer.process_data_pipeline(raw_data=raw_df, options=analysis_config)
        return result_df

    # ==================== 带结论的获取方法 ====================

    def get_supply_transaction_stats_with_conclusion(
        self, area_range_size: int = 20
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取供需统计数据，并返回计算结论"""
        df = self.get_supply_transaction_stats(area_range_size)
        conclusion_vars = self.conclusion_gen.get_supply_transaction_conclusion(df)
        return df, conclusion_vars

    def get_area_price_cross_stats_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取面积x价格交叉统计，并返回计算结论"""
        df = self.get_area_price_cross_stats()
        conclusion_vars = self.conclusion_gen.get_cross_structure_conclusion(df)
        return df, conclusion_vars

    def get_area_distribution_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取面积分布，并返回计算结论"""
        df_for_ppt = self.get_area_distribution_stats()
        conclusion_vars = self.conclusion_gen.get_area_distribution_conclusion(
            df_for_ppt,
        )
        return df_for_ppt, conclusion_vars

    def get_price_distribution_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取新房价格分布统计"""
        df_for_ppt = self.get_price_distribution_stats()
        conclusion_vars = self.conclusion_gen.get_price_distribution_conclusion(
            df_for_ppt,
        )
        return df_for_ppt, conclusion_vars


