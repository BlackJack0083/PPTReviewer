import pandas as pd
from loguru import logger

from utils import compact_dataframe


class StatTransformer:
    """
    数据转换器
    职责：负责清洗、分箱、聚合、重塑
    """

    @staticmethod
    def bin_and_agg_supply_stats(
        df: pd.DataFrame, step: int = 20, compact_rows: int = 15
    ) -> pd.DataFrame:
        """
        供应统计数据分箱聚合
        """
        if df.empty:
            return pd.DataFrame()

        df = df.copy()

        # 业务逻辑：分箱
        df["bin_start"] = (df["dim_area"] // step) * step
        df["Category"] = df["bin_start"].apply(lambda x: f"{int(x)}-{int(x+step)}m²")

        # 业务逻辑：聚合
        stats = (
            df.groupby("Category", observed=False)
            .agg(
                {
                    "supply_sets": "sum",
                    "trade_sets": "sum",
                }
            )
            .reset_index()
        )

        # 压缩长尾
        stats = compact_dataframe(
            stats, "Category", ["supply_sets", "trade_sets"], keep_rows=compact_rows
        )

        # 4. 展现逻辑：重命名与转置
        stats = stats.rename(
            columns={"supply_sets": "Supply", "trade_sets": "Transaction"}
        )
        return stats.set_index("Category").T

    @staticmethod
    def pivot_area_price(
        df: pd.DataFrame, area_step: int = 20, price_step: int = 1
    ) -> pd.DataFrame:
        """处理面积x价格交叉表逻辑"""
        if df.empty:
            return pd.DataFrame()

        # 这里的逻辑从 Provider 移过来了
        max_area = int(df["dim_area"].max())
        area_bins = range(0, max_area + area_step * 2, area_step)
        area_labels = [f"{i}-{i+area_step}m²" for i in area_bins[:-1]]

        max_price = int(df["dim_price"].max())
        price_bins = range(0, max_price + price_step * 2, price_step)
        price_labels = [f"{i}-{i+price_step}M" for i in price_bins[:-1]]

        # Cut
        df["Area_Range"] = pd.cut(df["dim_area"], bins=area_bins, labels=area_labels)
        df["Price_Range"] = pd.cut(
            df["dim_price"], bins=price_bins, labels=price_labels
        )

        result = pd.crosstab(df["Area_Range"], df["Price_Range"])

        # 如果表格过大，进行折叠
        from utils.data_utils import fold_large_table

        if result.shape[0] > 15 or result.shape[1] > 17:
            original_shape = result.shape
            result = fold_large_table(result, max_rows=15, max_cols=17)
            logger.info(f"Cross-table folded from {original_shape} to {result.shape}")

        return result

    @staticmethod
    def bin_area_distribution(
        df: pd.DataFrame, step: int = 20, compact_rows: int = 15
    ) -> pd.DataFrame:
        """
        面积分布统计 - 分箱聚合

        用于 Resale-House 和 New-House 的面积分布分析

        Args:
            df: 原始数据，包含 dim_area 和 trade_sets 列
            step: 面积分箱步长（默认20）
            compact_rows: 压缩长尾保留行数

        Returns:
            DataFrame: 包含 area_range 和 trade_sets 列
        """
        if df.empty:
            return pd.DataFrame()

        df = df.copy()

        # 分箱
        df["bin_start"] = (df["dim_area"] // step) * step
        df["area_range"] = df["bin_start"].apply(lambda x: f"{int(x)}-{int(x+step)}m²")

        # 聚合
        stats = (
            df.groupby("area_range", observed=False)
            .agg({"trade_sets": "sum"})
            .reset_index()
        )

        # 压缩长尾
        from utils import compact_dataframe

        stats = compact_dataframe(
            stats, "area_range", ["trade_sets"], keep_rows=compact_rows
        )

        # 将 area_range 设为索引，然后转置。
        # 结果：Columns变成面积段(X轴)，Index变成'trade_sets'(系列名)
        return stats.set_index("area_range").T

    @staticmethod
    def bin_price_distribution(
        df: pd.DataFrame, step: int = 1, compact_rows: int = 15
    ) -> pd.DataFrame:
        """
        价格分布统计 - 分箱聚合

        用于 New-House Market Capacity Analysis 的价格分布

        Args:
            df: 原始数据，包含 dim_price 和 trade_sets 列
            step: 价格分箱步长（默认1，单位M）
            compact_rows: 压缩长尾保留行数

        Returns:
            DataFrame: 包含 price_range 和 trade_sets 列
        """
        if df.empty:
            return pd.DataFrame()

        df = df.copy()

        # 分箱
        df["bin_start"] = (df["dim_price"] // step) * step
        df["price_range"] = df["bin_start"].apply(lambda x: f"{int(x)}-{int(x+step)}M")

        # 聚合
        stats = (
            df.groupby("price_range", observed=False)
            .agg({"trade_sets": "sum"})
            .reset_index()
        )

        # 压缩长尾
        from utils import compact_dataframe

        stats = compact_dataframe(
            stats, "price_range", ["trade_sets"], keep_rows=compact_rows
        )

        return stats.set_index("price_range").T
