# core/data_provider.py
import pandas as pd

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
