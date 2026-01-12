# core/conclusion_generator.py
"""
结论生成器模块
根据数据自动生成分析结论，返回用于文本模板的变量
"""
import re

import numpy as np
import pandas as pd
from loguru import logger


class ConclusionGenerator:
    """结论生成器 - 根据数据自动生成分析结论"""

    def __init__(self, start_year: str, end_year: str, block: str):
        self.start_year = start_year
        self.end_year = end_year
        self.block = block

    @staticmethod
    def _extract_start_area(area_range: str) -> int | None:
        """
        从面积范围字符串提取起始面积

        Args:
            area_range: 面积范围字符串，例如 '80-100m²'

        Returns:
            起始面积数值，例如 80
        """
        match = re.search(r"(\d+)", str(area_range))
        return int(match.group(1)) if match else None

    # ==================== 场景1: Block Area Segment Distribution ====================

    def get_supply_transaction_conclusion(
        self, df_data: pd.DataFrame, threshold: int = 140
    ) -> dict[str, str]:
        """
        计算供需统计的核心面积段和升级面积段

        Args:
            df_data: 供需统计数据DataFrame (转置后的格式，索引为Category)
            threshold: 升级面积段的阈值（默认140）

        Returns:
            dict: 包含 Seg_SupplyDemand_Core_Area 和 Seg_SupplyDemand_Upgrade_Area
        """
        df = df_data.copy()

        # df是转置后的格式，索引是 "Supply", "Transaction"，列是面积段
        # 我们需要转回来进行分析
        if df.index.tolist() in [["Supply", "Transaction"], ["supply", "transaction"]]:
            df = df.T

        # 确保索引是字符串类型
        df.index = df.index.astype(str)

        # 为每个索引值计算起始面积
        area_starts = df.index.map(self._extract_start_area)
        logger.debug(f"Area starts before fill: {area_starts.tolist()}")

        # 将 area_starts 转换为 Series
        area_starts = pd.Series(area_starts, index=df.index)

        # 计算倒数两个非 NaN 的差值作为间隔
        non_nan = area_starts.dropna()
        if len(non_nan) >= 2:
            second_last = non_nan.iloc[-2]
            last = non_nan.iloc[-1]
            interval = last - second_last
            replacement = last + interval
            area_starts_filled = area_starts.fillna(replacement)
            logger.debug(f"NaN replaced with: {replacement} (interval={interval})")
        else:
            area_starts_filled = area_starts.fillna(0)
            logger.warning("Not enough non-NaN values to compute interval")

        # 分离核心面积段和升级面积段
        df_core = df[area_starts_filled < threshold]
        df_upgrade = df[area_starts_filled >= threshold]

        # 计算核心面积段（<threshold中总量最大的）
        if not df_core.empty:
            # 对数值列求和
            numeric_df_core = df_core.select_dtypes(include="number")
            if not numeric_df_core.empty:
                core_sums = numeric_df_core.sum(axis=1)
                core_area_range = core_sums.idxmax()
            else:
                # 如果没有数值列，取第一个
                core_area_range = df_core.index[0]
        else:
            logger.warning(f"No data found for area < {threshold}")
            core_area_range = "N/A"

        # 计算升级面积段（>=threshold中总量最大的）
        if not df_upgrade.empty:
            numeric_df_upgrade = df_upgrade.select_dtypes(include="number")
            if not numeric_df_upgrade.empty:
                upgrade_sums = numeric_df_upgrade.sum(axis=1)
                upgrade_area_range = upgrade_sums.idxmax()
            else:
                upgrade_area_range = df_upgrade.index[0]
        else:
            logger.warning(f"No data found for area >= {threshold}")
            upgrade_area_range = "N/A"

        logger.info(f"Core area: {core_area_range}, Upgrade area: {upgrade_area_range}")

        return {
            "Seg_SupplyDemand_Core_Area": str(core_area_range),
            "Seg_SupplyDemand_Upgrade_Area": str(upgrade_area_range),
        }

    # ==================== 场景2: Area x Price Cross Pivot ====================

    def get_cross_structure_conclusion(self, df_data: pd.DataFrame) -> dict[str, str]:
        """
        计算交叉结构分析的结论（面积x价格）

        返回变量:
        - Metric_Transaction_Volume_Cumulative: 总交易量
        - Seg_Price_Stratum_Modal: 最热门价格段
        - Seg_Area_Stratum_Modal: 最热门面积段
        - Metric_Transaction_Velocity_Peak: 峰值交易量

        Args:
            df_data: 交叉表数据（面积x价格）

        Returns:
            dict: 包含交叉分析的结论变量
        """
        df = df_data.copy()

        # 移除 total 行和列
        if "total" in df.index:
            df = df.drop(index="total")
        if "total" in df.columns:
            df = df.drop(columns="total")

        # 转换为数值类型
        df = df.apply(pd.to_numeric, errors="coerce").fillna(0).astype(int)

        # 计算总量
        total = df.values.sum()

        # 找到最大值的位置（最热门的价格段和面积段组合）
        i, j = np.unravel_index(df.values.argmax(), df.shape)
        modal_price = df.index[i]
        modal_area = df.columns[j]
        peak_value = df.values.max()

        logger.info(
            f"Cross analysis - Total: {total}, Modal Price: {modal_price}, Modal Area: {modal_area}, Peak: {peak_value}"
        )

        return {
            "Metric_Transaction_Volume_Cumulative": str(total),
            "Seg_Price_Stratum_Modal": str(modal_price),
            "Seg_Area_Stratum_Modal": str(modal_area),
            "Metric_Transaction_Velocity_Peak": str(peak_value),
        }

    # ==================== 场景3: Area Segment Distribution ====================

    def get_area_distribution_conclusion(
        self,
        df: pd.DataFrame,
        area_col: str = "area_range",
        count_col: str = "trade_sets",
        top_n: int = 1,
    ) -> dict[str, str]:
        """
        计算面积分布结论

        Args:
            df: 包含 'area_range' 和 'trade_sets' 两列的DataFrame
            area_col: 面积段列名（默认 'area_range'）
            count_col: 数量列名（默认 'trade_sets'）
            top_n: 主流面积段输出前几个

        Returns:
            dict: 包含面积分布结论的变量
        """
        df = df.copy()

        # 检查数据是否为空
        if df.empty:
            logger.warning("Area distribution DataFrame is empty")
            return {
                "Seg_Area_Stratum_Dominant": "N/A",
                "Metric_Volume_Dominant_Cluster": "0",
            }

        # 确保有指定列
        if area_col not in df.columns or count_col not in df.columns:
            logger.error(
                f"DataFrame must contain '{area_col}' and '{count_col}' columns"
            )
            logger.info(f"Available columns: {df.columns.tolist()}")
            return {
                "Seg_Area_Stratum_Dominant": "N/A",
                "Metric_Volume_Dominant_Cluster": "0",
            }

        # 计算总量
        total = df[count_col].sum()

        if total == 0:
            logger.warning("Area distribution total count is 0")
            return {
                "Seg_Area_Stratum_Dominant": "N/A",
                "Metric_Volume_Dominant_Cluster": "0",
            }

        # 找到数量最多的面积段
        main_areas = df.nlargest(top_n, count_col).copy()

        # 按面积段的起始值排序
        def extract_area_start(x):
            match = re.search(r"(\d+)", str(x))
            return int(match.group(1)) if match else 999999

        main_areas = main_areas.sort_values(
            area_col, key=lambda x: x.apply(extract_area_start)
        )

        main_area_str = main_areas[area_col].iloc[0]
        main_area_count = main_areas[count_col].sum()

        logger.info(
            f"Area distribution - Dominant: {main_area_str}, Count: {main_area_count}"
        )

        return {
            "Seg_Area_Stratum_Dominant": main_area_str,
            "Metric_Volume_Dominant_Cluster": str(main_area_count),
        }

    # ==================== 场景4: Price Segment Distribution ====================

    def get_price_distribution_conclusion(
        self,
        df: pd.DataFrame,
        price_col: str = "price_range",
        count_col: str = "trade_sets",
        top_n: int = 1,
    ) -> dict[str, str]:
        """
        计算价格分布结论

        Args:
            df: 包含 'price_range' 和 'trade_sets' 两列的DataFrame
            price_col: 价格段列名（默认 'price_range'）
            count_col: 数量列名（默认 'trade_sets'）
            top_n: 主流价格段输出前几个

        Returns:
            dict: 包含价格分布结论的变量
        """
        df = df.copy()

        # 检查数据是否为空
        if df.empty:
            logger.warning("Price distribution DataFrame is empty")
            return {
                "Seg_Price_Stratum_Dominant": "N/A",
                "Metric_Volume_Dominant_Cluster": "0",
            }

        # 确保有指定列
        if price_col not in df.columns or count_col not in df.columns:
            logger.error(
                f"DataFrame must contain '{price_col}' and '{count_col}' columns"
            )
            logger.info(f"Available columns: {df.columns.tolist()}")
            return {
                "Seg_Price_Stratum_Dominant": "N/A",
                "Metric_Volume_Dominant_Cluster": "0",
            }

        # 计算总量
        total = df[count_col].sum()

        if total == 0:
            logger.warning("Price distribution total count is 0")
            return {
                "Seg_Price_Stratum_Dominant": "N/A",
                "Metric_Volume_Dominant_Cluster": "0",
            }

        # 找到数量最多的价格段
        main_prices = df.nlargest(top_n, count_col).copy()

        # 按价格段的起始值排序
        def extract_price_start(x):
            match = re.search(r"(\d+)", str(x))
            return int(match.group(1)) if match else 999999

        main_prices = main_prices.sort_values(
            price_col, key=lambda x: x.apply(extract_price_start)
        )

        main_price_str = main_prices[price_col].iloc[0]
        main_price_count = main_prices[count_col].sum()

        logger.info(
            f"Price distribution - Dominant: {main_price_str}, Count: {main_price_count}"
        )

        return {
            "Seg_Price_Stratum_Dominant": main_price_str,
            "Metric_Volume_Dominant_Cluster": str(main_price_count),
        }
