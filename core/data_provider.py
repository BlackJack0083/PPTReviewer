# core/data_provider.py

from collections.abc import Callable

import pandas as pd

from .conclusion_generator import ConclusionGenerator
from .dao import RealEstateDAO
from .schemas import BinningRule, MetricRule, QueryFilter, TableAnalysisConfig
from .transformers import StatTransformer


class RealEstateDataProvider:
    """
    Facade Layer
    职责：协调 DAO 获取数据，并调用 Transformer 加工数据。
    它是 Context 唯一需要交互的对象。
    """

    # Function Key 映射：定义 function_key 到对应方法的映射
    FUNCTION_MAP: dict[str, Callable] = {
        "Supply-Transaction Unit Statistic": "get_supply_transaction_stats_with_conclusion",
        "Area x Price Cross Pivot": "get_area_price_cross_stats_with_conclusion",
        "Area Segment Distribution": "get_area_distribution_with_conclusion",
        "Price Segment Distribution": "get_price_distribution_with_conclusion",
    }

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

        # analysis_config = [
        #     "field-constraint",
        #     [["Supply Count", "Sales Count"], ["area_range", "{}-{}m²", "20"]],
        #     [["dim_area", "supply_sets"], ["dim_area", "trade_sets"]],
        #     ["count", "count"],
        # ]

        # 2. Config Construction (不再使用 list)
        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[
                BinningRule(
                    source_col="dim_area",
                    target_col="area_range",
                    method="range",
                    step=area_range_size,
                    format_str="{}-{}m²",
                )
            ],
            metrics=[
                MetricRule(
                    name="Supply Count",
                    source_col="supply_sets",
                    agg_func="count",
                    filter_condition={"supply_sets": 1},  # 显式过滤
                ),
                MetricRule(
                    name="Sales Count",
                    source_col="trade_sets",
                    agg_func="count",
                    filter_condition={"trade_sets": 1},
                ),
            ],
        )

        # # 2. 加工产品 (CPU Bound)
        # result_df = self.transformer.process_data_pipeline(raw_data=raw_df, options=analysis_config)
        # return result_df

        # 3. CPU Bound
        return self.transformer.process_data_pipeline(raw_df, config)

    def get_area_price_cross_stats(
        self, area_step: int = 20, price_step: int = 1
    ) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(self.filter, columns=["dim_area", "dim_price"])

        # analysis_config = [
        #     "cross-constraint",
        #     [["area_range", "{}-{}m²", 10], ["price_range", "{}-{}M", 1]],
        #     ["dim_price", "dim_area"],
        #     ["count"],
        # ]

        config = TableAnalysisConfig(
            table_type="cross-constraint",
            dimensions=[
                BinningRule(
                    source_col="dim_area",
                    target_col="area_range",
                    method="range",
                    step=area_step,
                    format_str="{}-{}m²",
                ),
                BinningRule(
                    source_col="dim_price",
                    target_col="price_range",
                    method="range",
                    step=price_step,
                    format_str="{}-{}M",
                ),
            ],
            metrics=[
                MetricRule(name="Count", source_col="dim_price", agg_func="count")
            ],
            crosstab_row="area_range",
            crosstab_col="price_range",
        )

        # 2. 加工产品
        # result_df = self.transformer.process_data_pipeline(raw_data=raw_df, options=analysis_config)
        # return result_df

        return self.transformer.process_data_pipeline(raw_df, config)

    def get_area_distribution_stats(self, step: int = 20) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_area", "trade_sets"]
        )

        # analysis_config = [
        #     "field-constraint",
        #     [["Area Rng Stats"], ["area_range", "{}-{}m²", 10]],
        #     ["dim_area", "trade_sets"],
        #     ["count"],
        # ]

        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[
                BinningRule(
                    source_col="dim_area",
                    target_col="area_range",
                    method="range",
                    step=step,
                    format_str="{}-{}m²",
                )
            ],
            metrics=[
                MetricRule(
                    name="Area Rng Stats",
                    source_col="trade_sets",
                    agg_func="count",
                    filter_condition={"trade_sets": 1},
                )
            ],
        )

        # 2. 加工产品
        # result_df = self.transformer.process_data_pipeline(raw_data=raw_df, options=analysis_config)
        # return result_df

        return self.transformer.process_data_pipeline(raw_df, config)

    def get_price_distribution_stats(self, price_range_size: int = 1) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_price", "trade_sets"]
        )

        # analysis_config = [
        #     "field-constraint",
        #     [["Price Rng Stats"], ["price_range", "{}-{}M", "1"]],
        #     ["dim_price", "trade_sets"],
        #     ["count"],
        # ]

        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[
                BinningRule(
                    source_col="dim_price",
                    target_col="price_range",
                    method="range",
                    step=price_range_size,
                    format_str="{}-{}M",
                )
            ],
            metrics=[
                MetricRule(
                    name="Price Rng Stats",
                    source_col="trade_sets",
                    agg_func="count",
                    filter_condition={"trade_sets": 1},
                )
            ],
        )

        # 2. 加工产品
        # result_df = self.transformer.process_data_pipeline(raw_data=raw_df, options=analysis_config)
        # return result_df

        return self.transformer.process_data_pipeline(raw_df, config)

    # ==================== 带结论的获取方法 ====================

    def _transform_to_ppt_format(
        self, df: pd.DataFrame, index_col: str
    ) -> pd.DataFrame:
        """
        [私有辅助方法] 将分析用的长表/宽表转换为 PPT 生成器需要的横置格式
        1. 设置锚点列为索引
        2. 转置表格 (行列互换)
        3. 清洗 Numpy 数据类型为 Python 原生类型

        Args:
            df (pd.DataFrame): 原始分析结果表
            index_col (str): 用作索引的列名
        """
        if df.empty:
            return df

        df_copy = df.copy()

        # 1. 设置索引 (如果存在该列)
        if index_col in df_copy.columns:
            df_copy = df_copy.set_index(index_col)

        # 2. 转置
        df_transposed = df_copy.T

        # 3. 清洗类型 (解决 int64 is not JSON serializable 问题)
        # 遍历所有单元格，如果有 item() 方法则调用
        df_final = df_transposed.applymap(
            lambda x: x.item() if hasattr(x, "item") else x
        )

        return df_final

    def get_supply_transaction_stats_with_conclusion(
        self, area_range_size: int = 20
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取供需统计数据，并返回计算结论"""
        # 1. 获取原始分析数据(长表/竖表)
        df = self.get_supply_transaction_stats(area_range_size)

        # 2. 基于标准数据生成结论
        conclusion_vars = self.conclusion_gen.get_supply_transaction_conclusion(df)

        # 3. 转置为 PPT 需要的格式 (锚点: area_range)
        df_ppt = self._transform_to_ppt_format(df, index_col="area_range")

        return df_ppt, conclusion_vars

    def get_area_price_cross_stats_with_conclusion(
        self, area_step: int = 20, price_step: int = 1
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取面积x价格交叉统计，并返回计算结论"""
        df = self.get_area_price_cross_stats(area_step, price_step)
        conclusion_vars = self.conclusion_gen.get_cross_structure_conclusion(df)

        # 转置并清洗 (锚点: area_range)
        # 注意：这里假设交叉表的行索引是 area_range，转置后 area_range 变成表头
        # df_ppt = self._transform_to_ppt_format(df, index_col="area_range")

        return df, conclusion_vars

    def get_area_distribution_with_conclusion(
        self, step: int = 20
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取面积分布，并返回计算结论"""
        df = self.get_area_distribution_stats(step)
        conclusion_vars = self.conclusion_gen.get_area_distribution_conclusion(df)

        # 转置并清洗 (锚点: area_range)
        df_ppt = self._transform_to_ppt_format(df, index_col="area_range")

        return df_ppt, conclusion_vars

    def get_price_distribution_with_conclusion(
        self, price_range_size: int = 1
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取新房价格分布统计"""
        df = self.get_price_distribution_stats(price_range_size)
        conclusion_vars = self.conclusion_gen.get_price_distribution_conclusion(df)

        # 转置并清洗 (注意锚点变化: price_range)
        df_ppt = self._transform_to_ppt_format(df, index_col="price_range")

        return df_ppt, conclusion_vars

    # ==================== Function Dispatcher ====================

    def execute_by_function_key(
        self, function_key: str, **kwargs
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """
        根据 function_key 自动调用对应的函数

        Args:
            function_key: 功能键 (如 "Supply-Transaction Unit Statistic")
            **kwargs: 传递给目标函数的参数 (如 area_range_size=20)

        Returns:
            tuple[pd.DataFrame, dict[str, str]]: (数据框, 结论变量字典)

        Raises:
            ValueError: 如果 function_key 不在映射表中
        """
        if function_key not in self.FUNCTION_MAP:
            raise ValueError(
                f"未知的 function_key: '{function_key}'. "
                f"支持的 function_key: {list(self.FUNCTION_MAP.keys())}"
            )

        method_name = self.FUNCTION_MAP[function_key]
        method = getattr(self, method_name)

        return method(**kwargs)
