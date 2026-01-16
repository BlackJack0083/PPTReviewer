import re
from typing import Any

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

    # ==================== 主题1: Block Area Segment Distribution ====================

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

        numeric_cols = df.select_dtypes(include="number")
        df["total_volume"] = numeric_cols.sum(axis=1)

        main_idx = df["total_volume"].iloc[1:].idxmax()
        core_area_range = df.loc[main_idx, "area_range"]

        def parse_start_area(s: Any) -> int:
            match = re.search(r"(\d+)", str(s))
            return int(match.group(1)) if match else 0

        df["start_area"] = df["area_range"].apply(parse_start_area)

        upgrade_df = df[df["start_area"] >= threshold]

        if not upgrade_df.empty:
            upgrade_idx = upgrade_df["total_volume"].idxmax()
            upgrade_area_range = df.loc[upgrade_idx, "area_range"]
        else:
            upgrade_area_range = "N/A"

        logger.info(f"Core area: {core_area_range}, Upgrade area: {upgrade_area_range}")

        return {
            "Seg_SupplyDemand_Core_Area": str(core_area_range),
            "Seg_SupplyDemand_Upgrade_Area": str(upgrade_area_range),
        }

    # ==================== 主题2: Area x Price Cross Pivot ====================

    def get_cross_structure_conclusion(self, df_data: pd.DataFrame) -> dict[str, str]:
        """
        计算交叉结构分析的结论（面积x价格）

        Args:
            df_data: 交叉表数据（面积x价格）

        Returns:
            dict: 包含交叉分析的结论变量
        """
        df = df_data.copy()
        df = df.set_index("price_area")
        if "total" in df.index:
            df = df.drop("total")
        if "total" in df.columns:
            df = df.drop("total", axis=1)
        df = df.apply(pd.to_numeric, errors="coerce").fillna(0).astype(int)
        total = df.values.sum()
        i, j = np.unravel_index(df.values.argmax(), df.shape)
        modal_price = df.index[i]
        modal_area = df.columns[j]
        peak_value = df.values.max()

        logger.info(
            f"Cross analysis - Total: {total}, Modal Price: {modal_price}, "
            f"Modal Area: {modal_area}, Peak: {peak_value}"
        )

        return {
            "Metric_Transaction_Volume_Cumulative": str(total),
            "Seg_Price_Stratum_Modal": str(modal_price),
            "Seg_Area_Stratum_Modal": str(modal_area),
            "Metric_Transaction_Velocity_Peak": str(peak_value),
        }

    # ==================== 主题2: Area Segment Distribution ====================

    def get_area_distribution_conclusion(
        self,
        df_data: pd.DataFrame,
    ) -> dict[str, str]:
        """
        计算面积分布结论

        Args:
            df_data: 包含 'area_range' 和 'trade_sets' 两列的DataFrame

        Returns:
            dict: 包含面积分布结论的变量
        """
        df = df_data.copy()

        cols = df.select_dtypes(include="number").columns
        count_col = [c for c in cols if c != "area_range"][0]

        best_selling_row = df.loc[df[count_col].idxmax()]

        main_area_str = best_selling_row["area_range"]
        main_area_count = best_selling_row[count_col]

        logger.info(
            f"Area distribution - Dominant: {main_area_str}, Count: {main_area_count}"
        )

        return {
            "Seg_Area_Stratum_Dominant": main_area_str,
            "Metric_Volume_Dominant_Cluster": str(main_area_count),
        }

    # ==================== 主题2: Price Segment Distribution ====================

    def get_price_distribution_conclusion(
        self,
        df_data: pd.DataFrame,
    ) -> dict[str, str]:
        """
        计算价格分布结论

        Args:
            df_data: 包含 'price_range' 和 'trade_sets' 两列的DataFrame

        Returns:
            dict: 包含价格分布结论的变量
        """
        df = df_data.copy()

        cols = df.select_dtypes(include="number").columns
        count_col = [c for c in cols if c != "price_range"][0]

        best_selling_row = df.loc[df[count_col].idxmax()]

        main_price_str = best_selling_row["price_range"]
        main_price_count = best_selling_row[count_col]

        logger.info(
            f"Price distribution - Dominant: {main_price_str}, Count: {main_price_count}"
        )

        return {
            "Seg_Price_Stratum_Dominant": main_price_str,
            "Metric_Volume_Dominant_Cluster": str(main_price_count),
        }

    # ==================== 主题4: Historical Capacity Summary ====================

    def get_market_volume_price_trend(self, df_data: pd.DataFrame) -> dict[str, str]:
        """
        计算市场量价趋势结论

        Args:
            df_data: 包含量价数据的DataFrame

        Returns:
            dict: 包含起止价格/面积及变化率的结论变量
        """
        df = df_data.copy()

        s_area = df.iloc[0, 2]  # 起始面积
        e_area = df.iloc[-1, 2]  # 结束面积
        s_price = df.iloc[0, -1]  # 起始价格
        e_price = df.iloc[-1, -1]  # 结束价格

        # 优化除零保护逻辑
        pct_area = (e_area / s_area) - 1 if (s_area and s_area != 0) else 0
        pct_price = (e_price / s_price) - 1 if (s_price and s_price != 0) else 0

        def fmt_num(n: float) -> str:
            return f"{n:,.0f}"

        def fmt_pct(p: float) -> str:
            return f"{int(p)}" if abs(p) > 1 else f"{p:.2f}"

        area_trend = "decreased" if pct_area < 0 else "increased"
        area_change_val = fmt_pct(abs(pct_area * 100))

        price_trend = "decreased" if pct_price < 0 else "increased"
        price_change_val = fmt_pct(abs(pct_price * 100))

        logger.info(
            f"Trend Analysis - "
            f"Area: {s_area:.0f}->{e_area:.0f} ({area_trend} {area_change_val}%), "
            f"Price: {s_price:.0f}->{e_price:.0f} ({price_trend} {price_change_val}%)"
        )

        return {
            "Metric_Area_Start": str(s_area),
            "Metric_Area_End": str(e_area),
            "Metric_Area_Change_Rate": area_change_val,
            "Enum_Area_Trend_Direction": area_trend,
            "Metric_Price_Start": str(s_price),
            "Metric_Price_End": str(e_price),
            "Metric_Price_Change_Rate": price_change_val,
            "Enum_Price_Trend_Direction": price_trend,
        }

    # ==================== 主题4: Annual Supply-Demand Comparison ====================
    def get_supply_deal_flow_detail(self, df_data: pd.DataFrame) -> dict[str, str]:
        """
        计算供需流转详细数据（供应量 vs 成交量趋势）

        Args:
            df_data: 包含供需数据的DataFrame

        Returns:
            dict: 包含供需起止值、变化率及趋势方向
        """
        df = df_data.copy()

        try:
            s_series = pd.to_numeric(df.iloc[:, 1], errors="coerce").fillna(0)
            d_series = pd.to_numeric(df.iloc[:, 2], errors="coerce").fillna(0)

            sup_first, sup_last = s_series.iloc[0], s_series.iloc[-1]
            deal_first, deal_last = d_series.iloc[0], d_series.iloc[-1]
        except (IndexError, ValueError) as e:
            logger.error(f"Error parsing supply/deal columns: {e}")
            return {}

        sup_diff = sup_last - sup_first
        deal_diff = deal_last - deal_first

        sup_pct = (sup_diff / sup_first * 100) if sup_first != 0 else 0.0
        deal_pct = (deal_diff / deal_first * 100) if deal_first != 0 else 0.0

        def fmt_num(x: float) -> str:
            return f"{int(x):,}"

        def fmt_pct(x: float) -> str:
            val = abs(x)
            return f"{int(val)}" if val >= 1 else f"{val:.2f}"

        def get_trend_noun(diff: float) -> str:
            return "increase" if diff >= 0 else "decrease"

        sup_trend = get_trend_noun(sup_diff)
        deal_trend = get_trend_noun(deal_diff)

        sup_pct_str = fmt_pct(sup_pct)
        deal_pct_str = fmt_pct(deal_pct)

        logger.info(
            f"Flow Detail - "
            f"Supply: {sup_first:.0f}->{sup_last:.0f} ({sup_trend} {sup_pct_str}%), "
            f"Deal: {deal_first:.0f}->{deal_last:.0f} ({deal_trend} {deal_pct_str}%)"
        )

        return {
            "Metric_Supply_Volume_Start": fmt_num(sup_first),
            "Metric_Supply_Volume_End": fmt_num(sup_last),
            "Metric_Supply_Change_Rate": sup_pct_str,
            "Enum_Supply_Trend_Direction": sup_trend,
            "Metric_Deal_Volume_Start": fmt_num(deal_first),
            "Metric_Deal_Volume_End": fmt_num(deal_last),
            "Metric_Deal_Change_Rate": deal_pct_str,
            "Enum_Deal_Trend_Direction": deal_trend,
        }

    # ==================== 主题4: Supply-Transaction Area ====================
    def get_supply_deal_area_trend(self, df_data: pd.DataFrame) -> dict[str, str]:
        """
        计算供需面积的变化趋势（面积变化率 & 方向）

        Args:
            df_data: 包含供需面积数据的DataFrame

        Returns:
            dict: 包含供需面积的趋势方向和变化率
        """
        df = df_data.copy()

        try:
            s_series = pd.to_numeric(df.iloc[:, 1], errors="coerce").fillna(0)
            d_series = pd.to_numeric(df.iloc[:, 2], errors="coerce").fillna(0)

            sup_first, sup_last = s_series.iloc[0], s_series.iloc[-1]
            deal_first, deal_last = d_series.iloc[0], d_series.iloc[-1]
        except (IndexError, ValueError):
            logger.error("Error parsing area trend columns")
            return {}

        sup_diff = sup_last - sup_first
        deal_diff = deal_last - deal_first

        sup_pct = (sup_diff / sup_first * 100) if sup_first != 0 else 0.0
        deal_pct = (deal_diff / deal_first * 100) if deal_first != 0 else 0.0

        def fmt_pct(x: float) -> str:
            val = abs(x)
            return f"{int(val)}" if val >= 1 else f"{val:.2f}"

        def get_trend_status(diff: float) -> str:
            return "increased" if diff >= 0 else "decreased"

        sup_trend = get_trend_status(sup_diff)
        deal_trend = get_trend_status(deal_diff)

        sup_change_val = fmt_pct(sup_pct)
        deal_change_val = fmt_pct(deal_pct)

        logger.info(
            f"Area Trend - "
            f"Supply: {sup_trend} by {sup_change_val}%, "
            f"Deal: {deal_trend} by {deal_change_val}%"
        )

        return {
            "Enum_Supply_Area_Trend": sup_trend,
            "Metric_Supply_Area_Change_Rate": sup_change_val,
            "Enum_Deal_Area_Trend": deal_trend,
            "Metric_Deal_Area_Change_Rate": deal_change_val,
        }

    # ==================== 主题5: Historical Delivery Metrics ====================
    def get_resale_volume_trend_detailed(self, df_data: pd.DataFrame) -> dict[str, str]:
        """
        计算二手房成交量详细趋势（起止量、绝对变化量、变化率）

        Args:
            df_data: 包含年份和成交量的数据

        Returns:
            dict: 包含起止值、绝对差值、变化率及两种词性的趋势描述
        """
        df = df_data.copy()

        if df.index.name == "year" and "year" not in df.columns:
            df = df.reset_index()

        sort_col = "year" if "year" in df.columns else df.columns[0]

        try:
            df_sorted = df.sort_values(by=sort_col)
            vol_series = pd.to_numeric(df_sorted.iloc[:, 1], errors="coerce").fillna(0)
            first_val = int(vol_series.iloc[0])
            last_val = int(vol_series.iloc[-1])

        except (IndexError, KeyError, ValueError) as e:
            logger.error(f"Error processing resale volume data: {e}")
            return {}

        diff = last_val - first_val
        abs_diff = abs(diff)
        pct = (diff / first_val * 100) if first_val != 0 else 0.0

        def fmt_num(x: float) -> str:
            return f"{int(x):,}"

        def fmt_pct(x: float) -> str:
            val = abs(x)
            return f"{int(val)}" if val >= 1 else f"{val:.2f}"

        trend_noun = "increase" if diff >= 0 else "decrease"
        trend_status = "increased" if diff >= 0 else "decreased"

        change_abs_str = fmt_num(abs_diff)
        change_rate_str = fmt_pct(pct)

        logger.info(
            f"Resale Volume Trend - {first_val}->{last_val} "
            f"({trend_status} by {change_abs_str} / {change_rate_str}%)"
        )

        return {
            "Metric_Volume_Start": fmt_num(first_val),
            "Metric_Volume_End": fmt_num(last_val),
            "Metric_Volume_Change_Abs": change_abs_str,
            "Metric_Volume_Change_Rate": change_rate_str,
            "Enum_Trend_Direction": trend_noun,
            "Enum_Trend_Status": trend_status,
        }

    # ==================== 主题5: Annual Delivery Unit Count ====================
    def get_resale_volume_trend_simple(self, df_data: pd.DataFrame) -> dict[str, str]:
        """
        计算二手房成交量简要趋势（无百分比，仅起止值与绝对变化）

        Args:
            df_data: 包含年份和成交量的数据

        Returns:
            dict: 包含起止值、绝对差值及两种词性的趋势描述
        """
        df = df_data.copy()

        if df.index.name == "year" and "year" not in df.columns:
            df = df.reset_index()

        sort_col = "year" if "year" in df.columns else df.columns[0]

        try:
            df_sorted = df.sort_values(by=sort_col)
            vol_series = pd.to_numeric(df_sorted.iloc[:, 1], errors="coerce").fillna(0)
            first_val = int(vol_series.iloc[0])
            last_val = int(vol_series.iloc[-1])

        except (IndexError, KeyError, ValueError) as e:
            logger.error(f"Error processing resale volume simple data: {e}")
            return {}

        diff = last_val - first_val
        abs_diff = abs(diff)

        def fmt_num(x: float) -> str:
            return f"{int(x):,}"

        trend_noun = "increase" if diff >= 0 else "decrease"
        trend_status = "increased" if diff >= 0 else "decreased"

        change_abs_str = fmt_num(abs_diff)

        logger.info(
            f"Resale Volume Brief - "
            f"{first_val}->{last_val} ({trend_status} by {change_abs_str})"
        )

        return {
            "Enum_Trend_Status": trend_status,
            "Metric_Volume_Start": fmt_num(first_val),
            "Metric_Volume_End": fmt_num(last_val),
            "Enum_Trend_Direction": trend_noun,
            "Metric_Volume_Change_Abs": change_abs_str,
        }

    # ==================== 主题5: Annual Average Price Trend ====================
    def get_resale_price_trend(self, df_data: pd.DataFrame) -> dict[str, str]:
        """
        计算二手房均价趋势（含起止年份、价格及变化描述）

        Args:
            df_data: 包含年份和价格的数据

        Returns:
            dict: 包含6个核心变量
        """
        df = df_data.copy()

        if df.index.name == "year" and "year" not in df.columns:
            df = df.reset_index()

        sort_col = "year" if "year" in df.columns else df.columns[0]
        df_sorted = df.sort_values(by=sort_col)

        years = df_sorted.iloc[:, 0]
        prices = pd.to_numeric(df_sorted.iloc[:, 1], errors="coerce").fillna(0)

        start_year = str(years.iloc[0])
        end_year = str(years.iloc[-1])

        start_price = prices.iloc[0]
        end_price = prices.iloc[-1]

        pct_change = (
            (end_price - start_price) / start_price * 100 if start_price != 0 else 0.0
        )
        is_increase = pct_change >= 0

        def fmt_num(x: float) -> str:
            return f"{int(x):,}"

        def fmt_pct(x: float) -> str:
            return f"{int(abs(x))}" if abs(x) >= 1 else f"{abs(x):.2f}"

        trend_adj = "upward" if is_increase else "downward"
        change_verb = "increased" if is_increase else "decreased"
        change_desc = f"{change_verb} {fmt_pct(pct_change)}%"

        logger.info(
            f"Price Trend: {start_year}({start_price}) -> "
            f"{end_year}({end_price}) | {change_desc}"
        )

        return {
            "Enum_Trend_Direction": trend_adj,
            "Metric_Price_Start": fmt_num(start_price),
            "Metric_Year_Start": start_year,
            "Metric_Price_End": fmt_num(end_price),
            "Metric_Year_End": end_year,
            "Text_Change_Description": change_desc,
        }

    # ==================== 主题6: Annual Average Price Trend ====================
    def get_apartment_price_trend(self, df_data: pd.DataFrame) -> dict[str, str]:
        """
        计算社区公寓均价趋势（起止价格、变化方向及绝对值）

        Args:
            df_data: 包含时间与价格的数据

        Returns:
            dict: 包含5个核心变量
        """
        df = df_data.copy()

        # 修复逻辑冗余：等价于 "month" not in df.columns
        if "month" not in df.columns:
            df = df.reset_index()

        first_price = float(df.iloc[0, 1])
        last_price = float(df.iloc[-1, 1])

        change_abs = last_price - first_price
        is_increase = change_abs >= 0

        def fmt_num(x: float) -> str:
            return f"{x:,.0f}"

        trend_noun = "increase" if is_increase else "decrease"
        trend_dir = "upward" if is_increase else "downward"
        change_abs_str = fmt_num(abs(change_abs))

        logger.info(
            f"Apartment Price Trend: {first_price:.0f}->{last_price:.0f} "
            f"({trend_dir} {trend_noun} of {change_abs_str})"
        )

        return {
            "Enum_Trend_Direction": trend_dir,
            "Metric_Price_Start": fmt_num(first_price),
            "Metric_Price_End": fmt_num(last_price),
            "Enum_Trend_Noun": trend_noun,
            "Metric_Price_Change_Abs": change_abs_str,
        }
