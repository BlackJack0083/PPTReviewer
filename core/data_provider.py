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
        "Annual Supply-Demand Comparison": "get_annual_supply_demand_comparison_with_conclusion",
        "Supply-Transaction Area": "get_supply_transaction_area_with_conclusion",
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

    def get_supply_transaction_stats(
        self, area_range_size: int = 20
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """获取供需统计数据

        Returns:
            tuple[pd.DataFrame, TableAnalysisConfig]: 处理后的数据和分析配置
        """
        # 1. 获取原料 (IO Bound)
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_area", "supply_sets", "trade_sets"]
        )

        # 计算 dim_area 的 min/max
        area_min = int(raw_df["dim_area"].min()) if not raw_df.empty else 0
        area_max = int(raw_df["dim_area"].max()) if not raw_df.empty else 300

        # 2. Config Construction
        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[
                BinningRule(
                    source_col="dim_area",
                    target_col="area_range",
                    method="range",
                    step=area_range_size,
                    format_str="{}-{}m²",
                    min=area_min,
                    max=area_max,
                )
            ],
            metrics=[
                MetricRule(
                    name="Supply Count",
                    source_col="supply_sets",
                    agg_func="count",
                    filter_condition={"supply_sets": 1},
                ),
                MetricRule(
                    name="Sales Count",
                    source_col="trade_sets",
                    agg_func="count",
                    filter_condition={"trade_sets": 1},
                ),
            ],
        )

        # 3. CPU Bound
        df = self.transformer.process_data_pipeline(raw_df, config)
        return df, config

    def get_area_price_cross_stats(
        self, area_range_size: int = 20, price_range_size: int = 1
    ) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(self.filter, columns=["dim_area", "dim_price"])

        # 计算 min/max
        area_min = int(raw_df["dim_area"].min()) if not raw_df.empty else 0
        area_max = int(raw_df["dim_area"].max()) if not raw_df.empty else 300
        price_min = int(raw_df["dim_price"].min()) if not raw_df.empty else 0
        price_max = int(raw_df["dim_price"].max()) if not raw_df.empty else 20

        config = TableAnalysisConfig(
            table_type="cross-constraint",
            dimensions=[
                BinningRule(
                    source_col="dim_area",
                    target_col="area_range",
                    method="range",
                    step=area_range_size,
                    format_str="{}-{}m²",
                    min=area_min,
                    max=area_max,
                ),
                BinningRule(
                    source_col="dim_price",
                    target_col="price_range",
                    method="range",
                    step=price_range_size,
                    format_str="{}-{}M",
                    min=price_min,
                    max=price_max,
                ),
            ],
            metrics=[
                MetricRule(name="Count", source_col="dim_price", agg_func="count")
            ],
            crosstab_row="area_range",
            crosstab_col="price_range",
        )

        # 2. 加工产品
        df = self.transformer.process_data_pipeline(raw_df, config)
        return df, config

    def get_area_distribution_stats(
        self, area_range_size: int = 20
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """获取面积分布统计数据

        Returns:
            tuple[pd.DataFrame, TableAnalysisConfig]: 处理后的数据和分析配置
        """
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_area", "trade_sets"]
        )

        # 计算 dim_area 的 min/max
        area_min = int(raw_df["dim_area"].min()) if not raw_df.empty else 0
        area_max = int(raw_df["dim_area"].max()) if not raw_df.empty else 300

        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[
                BinningRule(
                    source_col="dim_area",
                    target_col="area_range",
                    method="range",
                    step=area_range_size,
                    format_str="{}-{}m²",
                    min=area_min,
                    max=area_max,
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
        df = self.transformer.process_data_pipeline(raw_df, config)
        return df, config

    def get_price_distribution_stats(
        self, price_range_size: int = 1
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """获取价格分布统计数据

        Returns:
            tuple[pd.DataFrame, TableAnalysisConfig]: 处理后的数据和分析配置
        """
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_price", "trade_sets"]
        )

        # 计算 dim_price 的 min/max
        price_min = int(raw_df["dim_price"].min()) if not raw_df.empty else 0
        price_max = int(raw_df["dim_price"].max()) if not raw_df.empty else 20

        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[
                BinningRule(
                    source_col="dim_price",
                    target_col="price_range",
                    method="range",
                    step=price_range_size,
                    format_str="{}-{}M",
                    min=price_min,
                    max=price_max,
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
        df = self.transformer.process_data_pipeline(raw_df, config)
        return df, config

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
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """获取供需统计数据，并返回计算结论和配置

        Returns:
            tuple: (处理后的数据, 结论变量, 分析配置)
        """
        # 1. 获取原始分析数据(长表/竖表) 和 config
        df, config = self.get_supply_transaction_stats(area_range_size)

        # 2. 基于标准数据生成结论
        conclusion_vars = self.conclusion_gen.get_supply_transaction_conclusion(df)

        # 3. 转置为 PPT 需要的格式 (锚点: area_range)
        df_ppt = self._transform_to_ppt_format(df, index_col="area_range")

        return df_ppt, conclusion_vars, config

    def get_area_price_cross_stats_with_conclusion(
        self, area_range_size: int = 20, price_range_size: int = 5
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """获取面积x价格交叉统计，并返回计算结论和配置

        Args:
            area_range_size: 面积区间大小
            price_range_size: 价格区间大小

        Returns:
            tuple: (处理后的数据, 结论变量, 分析配置)
        """
        df, config = self.get_area_price_cross_stats(area_range_size, price_range_size)
        conclusion_vars = self.conclusion_gen.get_cross_structure_conclusion(df)

        return df, conclusion_vars, config

    def get_area_distribution_with_conclusion(
        self, area_range_size: int = 20
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """获取面积分布，并返回计算结论和配置

        Args:
            area_range_size: 面积区间大小

        Returns:
            tuple: (处理后的数据, 结论变量, 分析配置)
        """
        df, config = self.get_area_distribution_stats(area_range_size)
        conclusion_vars = self.conclusion_gen.get_area_distribution_conclusion(df)

        # 转置并清洗 (锚点: area_range)
        df_ppt = self._transform_to_ppt_format(df, index_col="area_range")

        return df_ppt, conclusion_vars, config

    def get_price_distribution_with_conclusion(
        self, price_range_size: int = 1
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """获取新房价格分布统计，返回计算结论和配置

        Returns:
            tuple: (处理后的数据, 结论变量, 分析配置)
        """
        df, config = self.get_price_distribution_stats(price_range_size)
        conclusion_vars = self.conclusion_gen.get_price_distribution_conclusion(df)

        # 转置并清洗 (注意锚点变化: price_range)
        df_ppt = self._transform_to_ppt_format(df, index_col="price_range")

        return df_ppt, conclusion_vars, config

    # ==================== 年度供需对比统计 (套数) ====================

    def get_annual_supply_demand_comparison_stats(
        self,
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """获取年度供需对比统计数据（套数）

        Returns:
            tuple[pd.DataFrame, TableAnalysisConfig]: 处理后的数据和分析配置
        """
        # 1. 获取原料 (IO Bound)
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["date_code", "supply_sets", "trade_sets"]
        )

        # 2. 添加年份列
        raw_df["year"] = pd.to_datetime(raw_df["date_code"]).dt.year

        # 3. 按年份聚合供应套数和成交套数
        supply_df = raw_df[raw_df["supply_sets"] == 1].groupby("year").size().reset_index(name="supply_count")
        deal_df = raw_df[raw_df["trade_sets"] == 1].groupby("year").size().reset_index(name="deal_count")

        # 合并
        df = pd.merge(supply_df, deal_df, on="year", how="outer").fillna(0)
        df = df.sort_values("year").reset_index(drop=True)

        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[],
            metrics=[],
        )

        return df, config

    def get_annual_supply_demand_comparison_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """获取年度供需对比统计数据，并返回计算结论和配置

        Returns:
            tuple: (处理后的数据, 结论变量, 分析配置)
        """
        df, config = self.get_annual_supply_demand_comparison_stats()
        conclusion_vars = self.conclusion_gen.get_supply_deal_flow_detail(df)

        # 转置为 PPT 需要的格式 (锚点: year)
        df_ppt = self._transform_to_ppt_format(df, index_col="year")

        return df_ppt, conclusion_vars, config

    # ==================== 供应成交面积统计 ====================

    def get_supply_transaction_area_stats(
        self,
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """获取供应成交面积统计数据

        Returns:
            tuple[pd.DataFrame, TableAnalysisConfig]: 处理后的数据和分析配置
        """
        # 1. 获取原料 (IO Bound)
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["date_code", "dim_area", "supply_sets", "trade_sets"]
        )

        # 2. 添加年份列
        raw_df["year"] = pd.to_datetime(raw_df["date_code"]).dt.year

        # 3. 按年份聚合供应面积和成交面积
        # 供应面积: 当 supply_sets=1 时，对 dim_area 求和
        supply_df = raw_df[raw_df["supply_sets"] == 1].groupby("year")["dim_area"].sum().reset_index(name="supply_area")
        # 成交面积: 当 trade_sets=1 时，对 dim_area 求和
        deal_df = raw_df[raw_df["trade_sets"] == 1].groupby("year")["dim_area"].sum().reset_index(name="deal_area")

        # 合并
        df = pd.merge(supply_df, deal_df, on="year", how="outer").fillna(0)
        df = df.sort_values("year").reset_index(drop=True)

        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[],
            metrics=[],
        )

        return df, config

    def get_supply_transaction_area_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """获取供应成交面积统计数据，并返回计算结论和配置

        Returns:
            tuple: (处理后的数据, 结论变量, 分析配置)
        """
        df, config = self.get_supply_transaction_area_stats()
        conclusion_vars = self.conclusion_gen.get_supply_deal_area_trend(df)

        # 转置为 PPT 需要的格式 (锚点: year)
        df_ppt = self._transform_to_ppt_format(df, index_col="year")

        return df_ppt, conclusion_vars, config

    # ==================== Function Dispatcher ====================

    def execute_by_function_key(
        self, function_key: str, **kwargs
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig | None]:
        """
        根据 function_key 自动调用对应的函数

        Args:
            function_key: 功能键 (如 "Supply-Transaction Unit Statistic")
            **kwargs: 传递给目标函数的参数 (如 area_range_size=20)

        Returns:
            tuple[DataFrame, dict[str, str], TableAnalysisConfig | None]:
            (数据框, 结论变量字典, 数据分析配置)

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

        # 调用方法获取结果（已经是三元组：df, conclusions, config）
        result = method(**kwargs)

        # 直接返回三元组
        return result
