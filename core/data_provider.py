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

    def _transform_to_ppt_format(self, df: pd.DataFrame, index_col: str) -> pd.DataFrame:
        """
        [私有辅助方法] 将分析用的长表/宽表转换为 PPT 生成器需要的横置格式
        1. 设置锚点列为索引
        2. 转置表格 (行列互换)
        3. 清洗 Numpy 数据类型为 Python 原生类型
        """
        # 1. 只有当列在 dataframe 中不仅是索引时才 set_index
        # 防止 transformers 有时已经把 index 设置好了
        if index_col in df.columns:
            df = df.set_index(index_col)
        
        # 2. 转置
        df_transposed = df.T

        # 3. 清洗类型 (解决 int64 is not JSON serializable 问题)
        # 使用 applymap 递归处理所有单元格
        df_final = df_transposed.applymap(lambda x: x.item() if hasattr(x, 'item') else x)
        
        return df_final

    def get_supply_transaction_stats_with_conclusion(
        self, area_range_size: int = 20
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取供需统计数据，并返回计算结论"""
        # 1. 获取原始分析数据
        df = self.get_supply_transaction_stats(area_range_size)
        
        # 2. 生成结论 (必须用原始形状)
        conclusion_vars = self.conclusion_gen.get_supply_transaction_conclusion(df)
        
        # 3. 转置并清洗供 PPT 使用 (锚点: area_range)
        df_final = self._transform_to_ppt_format(df, index_col='area_range')
            
        return df_final, conclusion_vars

    def get_area_price_cross_stats_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取面积x价格交叉统计，并返回计算结论"""
        df = self.get_area_price_cross_stats()
        conclusion_vars = self.conclusion_gen.get_cross_structure_conclusion(df)
        
        # 转置并清洗 (锚点: area_range)
        # 注意：这里假设交叉表的行索引是 area_range，转置后 area_range 变成表头
        df_final = self._transform_to_ppt_format(df, index_col='area_range')
        
        return df_final, conclusion_vars

    def get_area_distribution_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取面积分布，并返回计算结论"""
        df = self.get_area_distribution_stats()
        conclusion_vars = self.conclusion_gen.get_area_distribution_conclusion(df)
        
        # 转置并清洗 (锚点: area_range)
        df_final = self._transform_to_ppt_format(df, index_col='area_range')
        
        return df_final, conclusion_vars

    def get_price_distribution_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取新房价格分布统计"""
        df = self.get_price_distribution_stats()
        conclusion_vars = self.conclusion_gen.get_price_distribution_conclusion(df)
        
        # 转置并清洗 (注意锚点变化: price_range)
        df_final = self._transform_to_ppt_format(df, index_col='price_range')
        
        return df_final, conclusion_vars


