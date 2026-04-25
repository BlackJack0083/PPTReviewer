# core/data_provider.py
from collections.abc import Callable

import pandas as pd

from .conclusion_generator import ConclusionGenerator
from .dao import RealEstateDAO
from .schemas import BinningRule, MetricRule, QueryFilter, TableAnalysisConfig
from .transformers import StatTransformer


class NoDataFoundError(ValueError):
    """Raised when a DB query returns no rows for the extracted arguments."""


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
        "Price Share Distribution": "get_price_share_with_conclusion",
        "Area Share Distribution": "get_area_share_with_conclusion",
        "Monthly Supply Volume": "get_monthly_supply_bar_with_conclusion",
        "Monthly Supply Trend": "get_monthly_supply_line_with_conclusion",
        "Annual Avg Price": "get_annual_avg_price_bar_with_conclusion",
        "Annual Avg Price & YoY Growth": "get_annual_avg_price_line_with_conclusion",
        "Annual Supply Ratio": "get_annual_supply_ratio_bar_with_conclusion",
        "Annual Supply Ratio Trend": "get_annual_supply_ratio_line_with_conclusion",
        "Area Year Pivot": "get_area_year_pivot_with_conclusion",
        "Annual Supply Trade": "get_yearly_supply_trade_with_conclusion",
        "Annual Supply-Demand Comparison": "get_annual_supply_demand_comparison_with_conclusion",
        "Supply-Transaction Area": "get_supply_transaction_area_with_conclusion",
        "Historical Delivery Metrics": "get_resale_summary_with_conclusion",
        "Annual Delivery Unit Count": "get_resale_transaction_count_with_conclusion",
        "Annual Average Price Trend": "get_resale_avg_price_with_conclusion",
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

    def _fetch_raw_data_or_raise(
        self,
        *,
        columns: list[str],
        function_key: str,
    ) -> pd.DataFrame:
        """Fetch raw rows once and fail fast with a diagnosis if the query is empty."""
        raw_df = self.dao.fetch_raw_data(self.filter, columns=columns)
        if not raw_df.empty:
            return raw_df
        raise NoDataFoundError(
            "No data found for "
            f"function_key='{function_key}', city='{self.filter.city}', "
            f"block='{self.filter.block}', table_name='{self.filter.table_name}', "
            f"start_date='{self.filter.start_date}', end_date='{self.filter.end_date}'. "
            "Check block normalization or extracted arguments."
        )

    def get_supply_transaction_stats(
        self, area_range_size: int = 20
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """获取供需统计数据
        Returns:
            tuple[pd.DataFrame, TableAnalysisConfig]: 处理后的数据和分析配置
        """
        raw_df = self._fetch_raw_data_or_raise(
            columns=["dim_area", "supply_sets", "trade_sets"],
            function_key="Supply-Transaction Unit Statistic",
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
        raw_df = self._fetch_raw_data_or_raise(
            columns=["dim_area", "dim_price"],
            function_key="Area x Price Cross Pivot",
        )
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
        raw_df = self._fetch_raw_data_or_raise(
            columns=["dim_area", "trade_sets"],
            function_key="Area Segment Distribution",
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
        raw_df = self._fetch_raw_data_or_raise(
            columns=["dim_price", "trade_sets"],
            function_key="Price Segment Distribution",
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
        # pandas>=3 已移除 applymap，统一使用 DataFrame.map
        df_final = df_transposed.map(lambda x: x.item() if hasattr(x, "item") else x)
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

    def get_price_share_with_conclusion(
        self, price_range_size: int = 1
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """获取价格段成交占比分布，并返回 share 专用结论和配置。"""
        df, config = self.get_price_distribution_stats(price_range_size)
        conclusion_vars = self.conclusion_gen.get_price_share_conclusion(df)
        df_ppt = self._transform_to_ppt_format(df, index_col="price_range")
        return df_ppt, conclusion_vars, config

    def get_area_share_with_conclusion(
        self, area_range_size: int = 20
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """获取面积段成交占比分布，并返回 share 专用结论和配置。"""
        df, config = self.get_area_distribution_stats(area_range_size)
        conclusion_vars = self.conclusion_gen.get_area_share_conclusion(df)
        df_ppt = self._transform_to_ppt_format(df, index_col="area_range")
        return df_ppt, conclusion_vars, config

    # ==================== 年度供需对比统计 (套数) ====================

    # ==================== 主题9：月度供需套数分析 ====================

    def get_monthly_supply_stats(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """获取月度供需统计数据。"""
        if col_names is None:
            col_names = ["supply_counts", "trade_counts"]
        raw_df = self._fetch_raw_data_or_raise(
            columns=["date_code", "supply_sets", "trade_sets"],
            function_key="Monthly Supply Volume",
        )
        raw_df = raw_df.copy()
        raw_df["month"] = (
            pd.to_datetime(raw_df["date_code"], errors="coerce")
            .dt.to_period("M")
            .astype(str)
        )
        supply_df = (
            raw_df[raw_df["supply_sets"] == 1]
            .groupby("month", observed=False)
            .size()
            .reset_index(name=col_names[0])
        )
        trade_df = (
            raw_df[raw_df["trade_sets"] == 1]
            .groupby("month", observed=False)
            .size()
            .reset_index(name=col_names[1])
        )
        df = pd.merge(supply_df, trade_df, on="month", how="outer").fillna(0)
        if not df.empty:
            df[col_names[0]] = df[col_names[0]].astype(int)
            df[col_names[1]] = df[col_names[1]].astype(int)
            df = df.sort_values("month").reset_index(drop=True)
        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[
                BinningRule(
                    source_col="date_code",
                    target_col="month",
                    method="period",
                    time_granularity="month",
                )
            ],
            metrics=[
                MetricRule(
                    name=col_names[0],
                    source_col="supply_sets",
                    agg_func="count",
                    filter_condition={"supply_sets": 1},
                ),
                MetricRule(
                    name=col_names[1],
                    source_col="trade_sets",
                    agg_func="count",
                    filter_condition={"trade_sets": 1},
                ),
            ],
        )
        return df, config

    def _get_monthly_supply_with_conclusion(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """获取主题9图表数据，并转换为 PPT 所需格式。"""
        df, config = self.get_monthly_supply_stats(col_names=col_names)
        conclusion_vars = self.conclusion_gen.get_monthly_supply_conclusion(df)
        df_ppt = self._transform_to_ppt_format(df, index_col="month")
        return df_ppt, conclusion_vars, config

    def get_monthly_supply_bar_with_conclusion(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """主题9图表数据入口。"""
        return self._get_monthly_supply_with_conclusion(col_names=col_names)

    def get_monthly_supply_line_with_conclusion(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """主题9图表数据入口。"""
        return self._get_monthly_supply_with_conclusion(col_names=col_names)

    # ==================== 主题10：年度均价同比增长分析 ====================

    def get_annual_avg_price_growth_stats(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """获取年度均价与同比增幅统计数据。"""
        if col_names is None:
            col_names = ["avg_price", "yoy_pct"]
        raw_df = self._fetch_raw_data_or_raise(
            columns=["date_code", "dim_unit_price", "trade_sets"],
            function_key="Annual Avg Price",
        )
        raw_df = raw_df.copy()
        raw_df["year"] = pd.to_datetime(raw_df["date_code"], errors="coerce").dt.year
        raw_df = raw_df.dropna(subset=["year"]).copy()
        raw_df["year"] = raw_df["year"].astype(int)
        if "trade_sets" in raw_df.columns:
            raw_df = raw_df[raw_df["trade_sets"] == 1].copy()
        if raw_df.empty:
            df = pd.DataFrame(columns=["year", *col_names])
        else:
            avg_price = (
                raw_df.groupby("year", observed=False)["dim_unit_price"]
                .mean()
                .fillna(0)
                .round(0)
            )
            yoy_base = avg_price.shift(1).replace(0, pd.NA)
            yoy_pct = ((avg_price - yoy_base) / yoy_base * 100).fillna(0).round(1)
            df = (
                pd.DataFrame(
                    {
                        "year": avg_price.index.astype(int),
                        col_names[0]: avg_price.astype(int).values,
                        col_names[1]: yoy_pct.astype(float).values,
                    }
                )
                .sort_values("year")
                .reset_index(drop=True)
            )
        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[
                BinningRule(
                    source_col="date_code",
                    target_col="year",
                    method="period",
                    time_granularity="year",
                )
            ],
            metrics=[
                MetricRule(
                    name=col_names[0],
                    source_col="dim_unit_price",
                    agg_func="mean",
                    filter_condition={"trade_sets": 1},
                )
            ],
        )
        return df, config

    def _get_annual_avg_price_with_conclusion(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """获取主题10图表数据，并转换为 PPT 所需格式。"""
        df, config = self.get_annual_avg_price_growth_stats(col_names=col_names)
        conclusion_vars = self.conclusion_gen.get_yoy_price_change_conclusion(df)
        df_ppt = self._transform_to_ppt_format(df, index_col="year")
        return df_ppt, conclusion_vars, config

    def get_annual_avg_price_bar_with_conclusion(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """主题10图表数据入口。"""
        return self._get_annual_avg_price_with_conclusion(col_names=col_names)

    def get_annual_avg_price_line_with_conclusion(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """主题10图表数据入口。"""
        return self._get_annual_avg_price_with_conclusion(col_names=col_names)

    # ==================== 主题11：年度供需比率分析 ====================

    def get_annual_supply_ratio_stats(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """获取年度供需比率统计数据。"""
        if col_names is None:
            col_names = ["supply_ratio"]
        raw_df = self._fetch_raw_data_or_raise(
            columns=["date_code", "supply_sets", "trade_sets"],
            function_key="Annual Supply Ratio",
        )
        raw_df = raw_df.copy()
        raw_df["year"] = pd.to_datetime(raw_df["date_code"], errors="coerce").dt.year
        raw_df = raw_df.dropna(subset=["year"]).copy()
        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[self._build_year_dimension()],
            metrics=[],
        )
        if raw_df.empty:
            return pd.DataFrame(columns=["year", col_names[0]]), config
        raw_df["year"] = raw_df["year"].astype(int)
        supply_counts = (
            raw_df[raw_df["supply_sets"] == 1].groupby("year", observed=False).size()
        )
        trade_counts = (
            raw_df[raw_df["trade_sets"] == 1].groupby("year", observed=False).size()
        )
        trade_base = trade_counts.astype(float).replace(0, pd.NA)
        ratio_series = (
            supply_counts.div(trade_base)
            .mul(100)
            .fillna(0)
            .round(1)
            .rename(col_names[0])
        )
        df = ratio_series.reset_index().sort_values("year").reset_index(drop=True)
        df[col_names[0]] = pd.to_numeric(df[col_names[0]], errors="coerce").fillna(0.0)
        return df, config

    def _get_annual_supply_ratio_with_conclusion(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """获取主题11图表数据，并补齐结论变量。"""
        df, config = self.get_annual_supply_ratio_stats(col_names=col_names)
        conclusion_vars = self.conclusion_gen.get_supply_ratio_conclusion(df)
        df_ppt = self._transform_to_ppt_format(df, index_col="year")
        return df_ppt, conclusion_vars, config

    def get_annual_supply_ratio_bar_with_conclusion(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """主题11图表数据入口。"""
        return self._get_annual_supply_ratio_with_conclusion(col_names=col_names)

    def get_annual_supply_ratio_line_with_conclusion(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """主题11图表数据入口。"""
        return self._get_annual_supply_ratio_with_conclusion(col_names=col_names)

    # ==================== 主题12：面积段年度趋势分析 ====================

    def get_area_year_pivot_stats(
        self,
        area_range_size: int = 20,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """获取面积段 x 年度透视统计数据。"""
        if col_names is None:
            col_names = ["supply_counts", "trade_counts"]
        raw_df = self._fetch_raw_data_or_raise(
            columns=["date_code", "dim_area", "supply_sets", "trade_sets"],
            function_key="Area Year Pivot",
        )
        numeric_area = pd.to_numeric(raw_df["dim_area"], errors="coerce").dropna()
        area_min = int(numeric_area.min()) if not numeric_area.empty else 0
        area_max = int(numeric_area.max()) if not numeric_area.empty else 300
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
                self._build_year_dimension(),
            ],
            metrics=[
                MetricRule(
                    name=col_names[0],
                    source_col="supply_sets",
                    agg_func="count",
                    filter_condition={"supply_sets": 1},
                ),
                MetricRule(
                    name=col_names[1],
                    source_col="trade_sets",
                    agg_func="count",
                    filter_condition={"trade_sets": 1},
                ),
            ],
            crosstab_row="area_range",
            crosstab_col="year",
        )
        df = self.transformer.process_data_pipeline(raw_df, config)
        return df, config

    def get_area_year_pivot_with_conclusion(
        self,
        area_range_size: int = 20,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """获取主题12宽表数据，并补齐结论变量。"""
        df, config = self.get_area_year_pivot_stats(
            area_range_size=area_range_size,
            col_names=col_names,
        )
        conclusion_vars = self.conclusion_gen.get_area_year_pivot_conclusion(df)
        return df, conclusion_vars, config

    def get_yearly_supply_trade_stats(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """获取主题12年度供需堆积图统计数据。"""
        if col_names is None:
            col_names = ["supply_counts", "trade_counts"]
        raw_df = self._fetch_raw_data_or_raise(
            columns=["date_code", "supply_sets", "trade_sets"],
            function_key="Annual Supply Trade",
        )
        raw_df = raw_df.copy()
        raw_df["year"] = pd.to_datetime(raw_df["date_code"], errors="coerce").dt.year
        raw_df = raw_df.dropna(subset=["year"]).copy()
        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[self._build_year_dimension()],
            metrics=[
                MetricRule(
                    name=col_names[0],
                    source_col="supply_sets",
                    agg_func="count",
                    filter_condition={"supply_sets": 1},
                ),
                MetricRule(
                    name=col_names[1],
                    source_col="trade_sets",
                    agg_func="count",
                    filter_condition={"trade_sets": 1},
                ),
            ],
        )
        if raw_df.empty:
            return pd.DataFrame(columns=["year", *col_names]), config
        raw_df["year"] = raw_df["year"].astype(int)
        supply_df = (
            raw_df[raw_df["supply_sets"] == 1]
            .groupby("year", observed=False)
            .size()
            .reset_index(name=col_names[0])
        )
        trade_df = (
            raw_df[raw_df["trade_sets"] == 1]
            .groupby("year", observed=False)
            .size()
            .reset_index(name=col_names[1])
        )
        df = pd.merge(supply_df, trade_df, on="year", how="outer").fillna(0)
        df = df.sort_values("year").reset_index(drop=True)
        for col_name in col_names:
            df[col_name] = (
                pd.to_numeric(df[col_name], errors="coerce").fillna(0).astype(int)
            )
        return df, config

    def get_yearly_supply_trade_with_conclusion(
        self,
        col_names: list[str] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """获取主题12堆积图数据，并转换为 PPT 所需格式。"""
        df, config = self.get_yearly_supply_trade_stats(col_names=col_names)
        conclusion_vars = self.conclusion_gen.get_annual_supply_trade_conclusion(df)
        df_ppt = self._transform_to_ppt_format(df, index_col="year")
        return df_ppt, conclusion_vars, config

    def get_annual_supply_demand_comparison_stats(
        self,
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """获取年度供需对比统计数据（套数）
        Returns:
            tuple[pd.DataFrame, TableAnalysisConfig]: 处理后的数据和分析配置
        """
        raw_df = self._fetch_raw_data_or_raise(
            columns=["date_code", "supply_sets", "trade_sets"],
            function_key="Annual Supply-Demand Comparison",
        )
        # 2. 添加年份列
        raw_df["year"] = pd.to_datetime(raw_df["date_code"]).dt.year
        # 3. 按年份聚合供应套数和成交套数
        supply_df = (
            raw_df[raw_df["supply_sets"] == 1]
            .groupby("year")
            .size()
            .reset_index(name="supply_count")
        )
        deal_df = (
            raw_df[raw_df["trade_sets"] == 1]
            .groupby("year")
            .size()
            .reset_index(name="deal_count")
        )
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
        raw_df = self._fetch_raw_data_or_raise(
            columns=["date_code", "dim_area", "supply_sets", "trade_sets"],
            function_key="Supply-Transaction Area",
        )
        # 2. 添加年份列
        raw_df["year"] = pd.to_datetime(raw_df["date_code"]).dt.year
        # 3. 按年份聚合供应面积和成交面积
        # 供应面积: 当 supply_sets=1 时，对 dim_area 求和
        supply_df = (
            raw_df[raw_df["supply_sets"] == 1]
            .groupby("year")["dim_area"]
            .sum()
            .reset_index(name="supply_area")
        )
        # 成交面积: 当 trade_sets=1 时，对 dim_area 求和
        deal_df = (
            raw_df[raw_df["trade_sets"] == 1]
            .groupby("year")["dim_area"]
            .sum()
            .reset_index(name="deal_area")
        )
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

    # ==================== Theme 5: resale yearly metrics ====================

    @staticmethod
    def _build_year_dimension() -> BinningRule:
        """Build a reusable yearly dimension config."""
        return BinningRule(
            source_col="date_code",
            target_col="year",
            method="period",
            time_granularity="year",
        )

    def _get_yearly_resale_trade_data(
        self,
        *,
        function_key: str,
        columns: list[str],
    ) -> pd.DataFrame:
        """Fetch yearly resale rows and keep traded records only."""
        raw_df = self._fetch_raw_data_or_raise(
            columns=columns, function_key=function_key
        )
        raw_df = raw_df.copy()
        raw_df["year"] = pd.to_datetime(raw_df["date_code"], errors="coerce").dt.year
        if "trade_sets" in raw_df.columns:
            raw_df = raw_df[raw_df["trade_sets"] == 1].copy()
        raw_df = raw_df.dropna(subset=["year"]).copy()
        if raw_df.empty:
            return raw_df
        raw_df["year"] = raw_df["year"].astype(int)
        return raw_df.sort_values("year").reset_index(drop=True)

    def get_resale_summary_stats(self) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """Get yearly resale summary rows for the table variants."""
        config = TableAnalysisConfig(
            table_type="constraint-field",
            dimensions=[self._build_year_dimension()],
            metrics=[
                MetricRule(
                    name="trade_counts",
                    source_col="trade_sets",
                    agg_func="count",
                    filter_condition={"trade_sets": 1},
                ),
                MetricRule(
                    name="avg_unit_price",
                    source_col="dim_unit_price",
                    agg_func="mean",
                    filter_condition={"trade_sets": 1},
                ),
                MetricRule(
                    name="dim_area",
                    source_col="dim_area",
                    agg_func="sum",
                    filter_condition={"trade_sets": 1},
                ),
            ],
        )
        traded_df = self._get_yearly_resale_trade_data(
            function_key="Historical Delivery Metrics",
            columns=["date_code", "trade_sets", "dim_area", "dim_unit_price"],
        )
        if traded_df.empty:
            return pd.DataFrame(columns=["metric"]), config
        grouped = traded_df.groupby("year", observed=False)
        result = pd.DataFrame(
            {
                "trade_counts": grouped.size(),
                "avg_unit_price": grouped["dim_unit_price"].mean(),
                "dim_area": grouped["dim_area"].sum(),
            }
        ).fillna(0)
        result["trade_counts"] = result["trade_counts"].astype(int)
        result["avg_unit_price"] = result["avg_unit_price"].round(0).astype(int)
        result["dim_area"] = result["dim_area"].round(0).astype(int)
        result = result.T.reset_index()
        result.rename(columns={"index": "metric"}, inplace=True)
        result.columns = [str(col) for col in result.columns]
        return result, config

    def get_resale_transaction_count_stats(
        self,
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """Get yearly resale transaction counts for chart variants."""
        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[self._build_year_dimension()],
            metrics=[
                MetricRule(
                    name="trade_counts",
                    source_col="trade_sets",
                    agg_func="count",
                    filter_condition={"trade_sets": 1},
                )
            ],
        )
        traded_df = self._get_yearly_resale_trade_data(
            function_key="Annual Delivery Unit Count",
            columns=["date_code", "trade_sets"],
        )
        if traded_df.empty:
            return pd.DataFrame(columns=["year", "trade_counts"]), config
        result = (
            traded_df.groupby("year", observed=False)
            .size()
            .reset_index(name="trade_counts")
            .sort_values("year")
            .reset_index(drop=True)
        )
        result["trade_counts"] = result["trade_counts"].astype(int)
        return result, config

    def get_resale_avg_price_stats(
        self,
    ) -> tuple[pd.DataFrame, TableAnalysisConfig]:
        """Get yearly resale average prices for chart variants."""
        config = TableAnalysisConfig(
            table_type="field-constraint",
            dimensions=[self._build_year_dimension()],
            metrics=[
                MetricRule(
                    name="avg_unit_price",
                    source_col="dim_unit_price",
                    agg_func="mean",
                    filter_condition={"trade_sets": 1},
                )
            ],
        )
        traded_df = self._get_yearly_resale_trade_data(
            function_key="Annual Average Price Trend",
            columns=["date_code", "trade_sets", "dim_unit_price"],
        )
        if traded_df.empty:
            return pd.DataFrame(columns=["year", "avg_unit_price"]), config
        result = (
            traded_df.groupby("year", observed=False)["dim_unit_price"]
            .mean()
            .reset_index(name="avg_unit_price")
            .sort_values("year")
            .reset_index(drop=True)
        )
        result["avg_unit_price"] = (
            result["avg_unit_price"].fillna(0).round(0).astype(int)
        )
        return result, config

    def get_resale_summary_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """Get yearly resale summary data plus summary variables."""
        df, config = self.get_resale_summary_stats()
        conclusion_vars = self.conclusion_gen.get_resale_historical_delivery_metrics(df)
        return df, conclusion_vars, config

    def get_resale_transaction_count_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """Get yearly resale transaction counts plus summary variables."""
        df, config = self.get_resale_transaction_count_stats()
        conclusion_vars = self.conclusion_gen.get_resale_annual_delivery_unit_count(df)
        df_ppt = self._transform_to_ppt_format(df, index_col="year")
        return df_ppt, conclusion_vars, config

    def get_resale_avg_price_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str], TableAnalysisConfig]:
        """Get yearly resale average prices plus summary variables."""
        df, config = self.get_resale_avg_price_stats()
        conclusion_vars = self.conclusion_gen.get_resale_annual_average_price_trend(df)
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
