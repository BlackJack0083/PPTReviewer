import pandas as pd

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

        return pd.crosstab(df["Area_Range"], df["Price_Range"])
