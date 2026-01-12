# core/data_provider.py

import pandas as pd

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

    def get_supply_transaction_stats(self, area_range_size=20) -> pd.DataFrame:
        # 1. 获取原料 (IO Bound)
        # 我们只需要这几列，减少网络传输压力
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_area", "supply_sets", "trade_sets"]
        )

        # 2. 加工产品 (CPU Bound)
        result_df = StatTransformer.bin_and_agg_supply_stats(
            raw_df, step=area_range_size
        )

        return result_df

    def get_area_price_cross_stats(self, area_step=20, price_step=1) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(self.filter, columns=["dim_area", "dim_price"])

        # 2. 加工产品
        return StatTransformer.pivot_area_price(
            raw_df, area_step=area_step, price_step=price_step
        )

    def get_area_distribution_stats(self, step=20, unit="m²") -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_area", "trade_sets"]
        )

        # 2. 加工产品
        return StatTransformer.bin_area_distribution(raw_df, step=step)

    def get_newhouse_price_distribution_stats(self, price_range_size=1) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_price", "trade_sets"]
        )

        # 使用 Transformer 处理
        return StatTransformer.bin_price_distribution(raw_df, step=price_range_size)

    # ==================== 带结论的获取方法 ====================

    def get_supply_transaction_stats_with_conclusion(
        self, area_range_size=20
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """
        获取供需统计数据，并返回计算结论

        Returns:
            Tuple[DataFrame, dict]: (数据, 结论变量字典)
        """
        df = self.get_supply_transaction_stats(area_range_size)

        # 计算结论
        conclusion_vars = self.conclusion_gen.get_supply_transaction_conclusion(df)

        return df, conclusion_vars

    def get_area_price_cross_stats_with_conclusion(
        self, area_step=20, price_step=1
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """
        获取面积x价格交叉统计，并返回计算结论

        Returns:
            Tuple[DataFrame, dict]: (数据, 结论变量字典)
        """
        df = self.get_area_price_cross_stats(area_step, price_step)

        # 计算结论
        conclusion_vars = self.conclusion_gen.get_cross_structure_conclusion(df)

        return df, conclusion_vars

    def get_newhouse_area_distribution_with_conclusion(
        self, step=20, unit="m²"
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """
        获取面积分布，并返回计算结论

        Args:
            step: 分箱步长（默认20）
            unit: 单位（默认'm²'）

        Returns:
            Tuple[DataFrame, dict]: (数据, 结论变量字典)
        """
        # 1. 获取给 PPT 用的数据 (已经是转置后的宽表，适合画图)
        df_for_ppt = self.get_area_distribution_stats(step, unit)

        # 2. 准备给计算器用的数据 (还原回长表)
        # 逻辑：先转置回去(.T)，把索引恢复成列(.reset_index)
        df_for_calc = df_for_ppt.T.reset_index()

        # 3. 计算结论
        conclusion_vars = self.conclusion_gen.get_area_distribution_conclusion(
            df_for_calc,  # ✅ 传入还原后的数据
            area_col="area_range",
            count_col="trade_sets",
        )

        # 4. 返回给 Context (df 给图表用，vars 给文本用)
        return df_for_ppt, conclusion_vars

    def get_newhouse_price_distribution_with_conclusion(
        self, price_range_size: int = 1
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """
        获取新房价格分布统计

        用于 New-House Market Capacity Analysis 中的价格分布

        Args:
            price_range_size: 价格分箱步长（默认1M）

        Returns:
            DataFrame: 包含 price_range 和 trade_sets 列
        """
        # 1. 获取给 PPT 用的数据 (宽表)
        df_for_ppt = self.get_newhouse_price_distribution_stats(price_range_size)

        # 2. 准备给计算器用的数据 (还原为长表)
        df_for_calc = df_for_ppt.T.reset_index()

        # 3. 计算结论
        conclusion_vars = self.conclusion_gen.get_price_distribution_conclusion(
            df_for_calc,  # ✅ 传入还原后的数据
            price_col="price_range",
            count_col="trade_sets",
        )

        return df_for_ppt, conclusion_vars
