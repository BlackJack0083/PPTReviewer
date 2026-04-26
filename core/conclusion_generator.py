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
        df = df.set_index("area_range")
        if "total" in df.index:
            df = df.drop("total")
        if "total" in df.columns:
            df = df.drop("total", axis=1)
        df = df.apply(pd.to_numeric, errors="coerce").fillna(0).astype(int)
        total = df.values.sum()
        i, j = np.unravel_index(df.values.argmax(), df.shape)
        # crosstab_row=area_range (index), crosstab_col=price_range (columns)
        modal_area = df.index[i]
        modal_price = df.columns[j]
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
        cols = [
            c for c in df.select_dtypes(include="number").columns if c != "price_range"
        ]
        if not cols:
            raise ValueError(
                "No numeric metric column found for price distribution conclusion."
            )
        count_col = cols[0]
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

    def _build_share_conclusion(
        self,
        df_data: pd.DataFrame,
        *,
        bucket_col: str,
        segment_key: str,
    ) -> dict[str, str]:
        """Build a reusable dominant-segment/share conclusion contract."""
        df = df_data.copy()
        numeric_cols = [
            col
            for col in df.select_dtypes(include="number").columns
            if col != bucket_col
        ]
        if not numeric_cols:
            raise ValueError(
                f"No numeric metric column found for share analysis: {bucket_col}"
            )
        count_col = numeric_cols[0]
        working_df = df[[bucket_col, count_col]].copy()
        working_df[count_col] = pd.to_numeric(
            working_df[count_col], errors="coerce"
        ).fillna(0)
        dominant_row = working_df.loc[working_df[count_col].idxmax()]
        dominant_segment = str(dominant_row[bucket_col])
        dominant_count = int(working_df[count_col].max())
        total_count = int(working_df[count_col].sum())
        dominant_share = (dominant_count / total_count * 100) if total_count else 0.0

        def fmt_num(val: int) -> str:
            return f"{val:,}"

        def fmt_pct(val: float) -> str:
            return f"{val:.1f}" if val < 10 else f"{val:.0f}"

        logger.info(
            f"Share analysis - {segment_key}: dominant={dominant_segment}, "
            f"count={dominant_count}, share={dominant_share:.2f}%"
        )
        return {
            segment_key: dominant_segment,
            "Metric_Volume_Dominant_Cluster": fmt_num(dominant_count),
            "Metric_Share_Dominant_Cluster": fmt_pct(dominant_share),
            "Metric_Volume_Total": fmt_num(total_count),
        }

    def get_area_share_conclusion(
        self,
        df_data: pd.DataFrame,
    ) -> dict[str, str]:
        """主题8：面积段成交套数占比分析结论。"""
        return self._build_share_conclusion(
            df_data,
            bucket_col="area_range",
            segment_key="Seg_Area_Stratum_Dominant",
        )

    def get_price_share_conclusion(
        self,
        df_data: pd.DataFrame,
    ) -> dict[str, str]:
        """主题7：价格段成交套数占比分析结论。"""
        return self._build_share_conclusion(
            df_data,
            bucket_col="price_range",
            segment_key="Seg_Price_Stratum_Dominant",
        )

    # ==================== 主题4: Historical Capacity Summary ====================

    # ==================== 主题9：Monthly Supply Analysis ====================

    def get_monthly_supply_conclusion(self, df_data: pd.DataFrame) -> dict[str, str]:
        """生成主题9月度供需分析结论变量。"""
        df = df_data.copy()
        if df.empty:
            return {}
        value_columns = [col for col in df.columns if col != "month"]
        if len(value_columns) < 2:
            return {}
        supply_col, trade_col = value_columns[0], value_columns[1]
        supply_series = pd.to_numeric(df[supply_col], errors="coerce").fillna(0)
        trade_series = pd.to_numeric(df[trade_col], errors="coerce").fillna(0)
        peak_idx = int(trade_series.idxmax())
        peak_month = str(df.loc[peak_idx, "month"])
        peak_trade = int(trade_series.iloc[peak_idx])
        avg_trade = float(trade_series.mean()) if not trade_series.empty else 0.0
        supply_total = int(supply_series.sum())
        trade_total = int(trade_series.sum())
        supply_demand_ratio = (supply_total / trade_total * 100) if trade_total else 0.0
        logger.info(
            "Monthly supply analysis - "
            f"peak_month={peak_month}, peak_trade={peak_trade}, ratio={supply_demand_ratio:.1f}%"
        )
        return {
            "Temporal_Month_Peak": peak_month,
            "Metric_Volume_Trade_Peak": f"{peak_trade:,}",
            "Metric_Volume_Trade_Average": f"{avg_trade:,.0f}",
            "Metric_Volume_Supply_Total": f"{supply_total:,}",
            "Metric_Volume_Trade_Total": f"{trade_total:,}",
            "Metric_Supply_Demand_Ratio": f"{supply_demand_ratio:.0f}",
        }

    # ==================== 主题10：Annual Avg Price Growth ====================

    def get_yoy_price_change_conclusion(self, df_data: pd.DataFrame) -> dict[str, str]:
        """生成主题10年度均价与同比增长结论变量。"""
        df = df_data.copy()
        if df.empty:
            return {}
        year_col = "year" if "year" in df.columns else df.columns[0]
        metric_cols = [col for col in df.columns if col != year_col]
        if len(metric_cols) < 2:
            return {}
        price_col, yoy_col = metric_cols[0], metric_cols[1]
        years = df[year_col].astype(str).tolist()
        price_series = pd.to_numeric(df[price_col], errors="coerce").fillna(0)
        yoy_series = pd.to_numeric(df[yoy_col], errors="coerce").fillna(0)
        first_price = float(price_series.iloc[0])
        last_price = float(price_series.iloc[-1])
        price_delta = last_price - first_price
        cumulative_pct = (price_delta / first_price * 100) if first_price else 0.0
        peak_yoy_idx = int(yoy_series.idxmax())
        peak_yoy_year = years[peak_yoy_idx]
        peak_yoy_value = float(yoy_series.iloc[peak_yoy_idx])
        trend_label, trajectory_type, secular_direction = self._trend_direction_words(
            price_delta
        )
        logger.info(
            "YoY price analysis - "
            f"start={first_price:.0f}, end={last_price:.0f}, peak_yoy={peak_yoy_value:.1f}%@{peak_yoy_year}"
        )
        return {
            "Metric_Val_Price_Base": f"{first_price:,.0f}",
            "Metric_Val_Price_Terminal": f"{last_price:,.0f}",
            "Metric_Var_Price_Delta": f"{abs(price_delta):,.0f}",
            "Metric_Var_Price_Pct": f"{abs(cumulative_pct):.1f}",
            "Metric_YoY_Peak": f"{peak_yoy_value:.1f}",
            "Temporal_Year_YoY_Peak": peak_yoy_year,
            "Trend_Direction_Label": trend_label,
            "Trend_Trajectory_Type": trajectory_type,
            "Trend_Secular_Direction": secular_direction,
            "Trend_Market_Absorption_State": (
                "seller-favorable" if price_delta >= 0 else "buyer-favorable"
            ),
        }

    # ==================== 主题11：Annual Supply Ratio ====================

    def get_supply_ratio_conclusion(self, df_data: pd.DataFrame) -> dict[str, str]:
        """生成主题11年度供需比率结论变量。"""
        df = df_data.copy()
        if df.empty:
            return {}
        year_col = "year" if "year" in df.columns else df.columns[0]
        ratio_col = next((col for col in df.columns if col != year_col), None)
        if ratio_col is None:
            return {}
        working_df = df[[year_col, ratio_col]].copy()
        working_df[ratio_col] = pd.to_numeric(
            working_df[ratio_col], errors="coerce"
        ).fillna(0.0)
        if working_df.empty:
            return {}
        base_ratio = float(working_df[ratio_col].iloc[0])
        terminal_ratio = float(working_df[ratio_col].iloc[-1])
        avg_ratio = float(working_df[ratio_col].mean())
        peak_idx = int(working_df[ratio_col].idxmax())
        peak_year = str(working_df.loc[peak_idx, year_col])
        peak_ratio = float(working_df.loc[peak_idx, ratio_col])
        low_ratio = float(working_df[ratio_col].min())
        direction_label, trajectory_type, secular_direction = (
            self._trend_direction_words(terminal_ratio - base_ratio)
        )
        balance_state = (
            "oversupplied"
            if avg_ratio > 110
            else ("balanced" if avg_ratio >= 90 else "undersupplied")
        )
        balance_assessment = (
            "Supply and demand were relatively matched."
            if 90 <= avg_ratio <= 110
            else "Supply and demand were relatively unmatched."
        )
        logger.info(
            "Supply ratio analysis - "
            f"avg={avg_ratio:.1f}%, peak={peak_ratio:.1f}%@{peak_year}, "
            f"state={balance_state}"
        )
        return {
            "Metric_Supply_Ratio_Base": f"{base_ratio:.1f}",
            "Metric_Supply_Ratio_Terminal": f"{terminal_ratio:.1f}",
            "Metric_Supply_Ratio_Average": f"{avg_ratio:.1f}",
            "Metric_Supply_Ratio_Peak": f"{peak_ratio:.1f}",
            "Metric_Supply_Ratio_Low": f"{low_ratio:.1f}",
            "Temporal_Year_Ratio_Peak": peak_year,
            "Trend_Direction_Label": direction_label,
            "Trend_Trajectory_Type": trajectory_type,
            "Trend_Secular_Direction": secular_direction,
            "Trend_Market_Balance_State": balance_state,
            "Text_Market_Balance_Assessment": balance_assessment,
        }

    # ==================== 主题12：Area Segment Annual Trend ====================

    def get_area_year_pivot_conclusion(self, df_data: pd.DataFrame) -> dict[str, str]:
        """生成主题12面积段年度透视宽表结论变量。"""
        df = df_data.copy()
        if df.empty or "area_range" not in df.columns:
            return {}
        trade_cols = [col for col in df.columns if "trade_counts(" in str(col)]
        if not trade_cols:
            trade_cols = [
                col
                for col in df.select_dtypes(include="number").columns
                if col != "area_range"
            ]
        if not trade_cols:
            return {}
        year_pattern = re.compile(r"\((\d{4})\)")

        def sort_key(column: str) -> tuple[int, int | str]:
            match = year_pattern.search(str(column))
            if match:
                return (0, int(match.group(1)))
            return (1, str(column))

        trade_cols = sorted(trade_cols, key=sort_key)
        working_df = df[["area_range", *trade_cols]].copy()
        for col in trade_cols:
            working_df[col] = pd.to_numeric(working_df[col], errors="coerce").fillna(0)
        area_totals = working_df[trade_cols].sum(axis=1)
        total_volume = float(area_totals.sum())
        if total_volume <= 0:
            return {}
        dominant_idx = int(area_totals.idxmax())
        dominant_segment = str(working_df.loc[dominant_idx, "area_range"])
        dominant_share = float(area_totals.loc[dominant_idx] / total_volume * 100)
        yearly_totals = working_df[trade_cols].sum(axis=0)
        base_volume = int(yearly_totals.iloc[0])
        terminal_volume = int(yearly_totals.iloc[-1])
        direction_label, trajectory_type, secular_direction = (
            self._trend_direction_words(terminal_volume - base_volume)
        )
        logger.info(
            "Area year pivot analysis - "
            f"dominant={dominant_segment}, share={dominant_share:.1f}%, "
            f"volume={base_volume}->{terminal_volume}"
        )
        share_text = (
            f"{dominant_share:.1f}" if dominant_share < 10 else f"{dominant_share:.0f}"
        )
        return {
            "Seg_Area_Stratum_Dominant": dominant_segment,
            "Metric_Share_Dominant_Cluster": share_text,
            "Metric_Volume_Total": f"{int(total_volume):,}",
            "Metric_Volume_Trade_Base": f"{base_volume:,}",
            "Metric_Volume_Trade_Terminal": f"{terminal_volume:,}",
            "Trend_Direction_Label": direction_label,
            "Trend_Trajectory_Type": trajectory_type,
            "Trend_Secular_Direction": secular_direction,
        }

    def get_annual_supply_trade_conclusion(
        self, df_data: pd.DataFrame
    ) -> dict[str, str]:
        """生成主题12年度供需堆积图结论变量。"""
        df = df_data.copy()
        if df.empty:
            return {}
        year_col = "year" if "year" in df.columns else df.columns[0]
        supply_col = "supply_counts" if "supply_counts" in df.columns else None
        trade_col = "trade_counts" if "trade_counts" in df.columns else None
        if supply_col is None:
            candidates = [col for col in df.columns if col != year_col]
            supply_col = candidates[0] if candidates else None
        if trade_col is None:
            candidates = [
                col for col in df.columns if col not in {year_col, supply_col}
            ]
            trade_col = candidates[0] if candidates else None
        if supply_col is None or trade_col is None:
            return {}
        working_df = df[[year_col, supply_col, trade_col]].copy()
        working_df = working_df.sort_values(year_col).reset_index(drop=True)
        supply_series = pd.to_numeric(working_df[supply_col], errors="coerce").fillna(0)
        trade_series = pd.to_numeric(working_df[trade_col], errors="coerce").fillna(0)
        sup_first = float(supply_series.iloc[0])
        sup_last = float(supply_series.iloc[-1])
        deal_first = float(trade_series.iloc[0])
        deal_last = float(trade_series.iloc[-1])
        sup_diff = sup_last - sup_first
        deal_diff = deal_last - deal_first
        sup_pct = (sup_diff / sup_first * 100) if sup_first else 0.0
        deal_pct = (deal_diff / deal_first * 100) if deal_first else 0.0

        def fmt_num(value: float) -> str:
            return f"{int(round(value)):,}"

        def fmt_pct(value: float) -> str:
            abs_value = abs(value)
            return f"{int(abs_value)}" if abs_value >= 1 else f"{abs_value:.2f}"

        def get_trend_noun(diff: float) -> str:
            return "increase" if diff >= 0 else "decrease"

        def get_trend_label(trend_noun: str) -> str:
            return f"an {trend_noun}" if trend_noun == "increase" else f"a {trend_noun}"

        supply_trend = get_trend_noun(sup_diff)
        deal_trend = get_trend_noun(deal_diff)
        logger.info(
            "Annual supply trade analysis - "
            f"supply={sup_first:.0f}->{sup_last:.0f}, trade={deal_first:.0f}->{deal_last:.0f}"
        )
        return {
            "Metric_Vol_Supply_Base": fmt_num(sup_first),
            "Metric_Vol_Supply_Terminal": fmt_num(sup_last),
            "Metric_Var_Supply_Pct": fmt_pct(sup_pct),
            "Enum_Supply_Trend": supply_trend,
            "Enum_Supply_Trend_Label": get_trend_label(supply_trend),
            "Metric_Vol_Trans_Base": fmt_num(deal_first),
            "Metric_Vol_Trans_Terminal": fmt_num(deal_last),
            "Metric_Var_Trans_Pct": fmt_pct(deal_pct),
            "Enum_Deal_Trend": deal_trend,
            "Enum_Deal_Trend_Label": get_trend_label(deal_trend),
        }

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

        def get_trend_label(trend_noun: str) -> str:
            """获取趋势的标签形式: increase -> an increase, decrease -> a decrease"""
            return f"an {trend_noun}" if trend_noun == "increase" else f"a {trend_noun}"

        return {
            "Metric_Vol_Supply_Base": fmt_num(sup_first),
            "Metric_Vol_Supply_Terminal": fmt_num(sup_last),
            "Metric_Var_Supply_Pct": sup_pct_str,
            "Enum_Supply_Trend": sup_trend,
            "Enum_Supply_Trend_Label": get_trend_label(sup_trend),
            "Metric_Vol_Trans_Base": fmt_num(deal_first),
            "Metric_Vol_Trans_Terminal": fmt_num(deal_last),
            "Metric_Var_Trans_Pct": deal_pct_str,
            "Enum_Deal_Trend": deal_trend,
            "Enum_Deal_Trend_Label": get_trend_label(deal_trend),
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
        except (IndexError, ValueError) as exc:
            logger.error("Error parsing area trend columns")
            raise ValueError(
                "Invalid data format for supply/deal area trend analysis"
            ) from exc
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
            "Enum_Supply_Trend": sup_trend,
            "Metric_Var_Supply_Pct": sup_change_val,
            "Enum_Deal_Trend": deal_trend,
            "Metric_Var_Trans_Pct": deal_change_val,
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

        trend_status = "increased" if diff >= 0 else "decreased"
        change_abs_str = fmt_num(abs_diff)
        change_rate_str = fmt_pct(pct)
        logger.info(
            f"Resale Volume Trend - {first_val}->{last_val} "
            f"({trend_status} by {change_abs_str} / {change_rate_str}%)"
        )
        trend_label, trajectory_type, _ = self._trend_direction_words(diff)
        return {
            "Metric_Volume_Start": fmt_num(first_val),
            "Metric_Volume_End": fmt_num(last_val),
            "Metric_Volume_Change_Abs": change_abs_str,
            "Metric_Volume_Change_Rate": change_rate_str,
            "Enum_Trend_Direction": trend_label,
            "Enum_Trend_Status": trajectory_type,
            "Metric_Vol_Trans_Base": fmt_num(first_val),
            "Metric_Vol_Trans_Terminal": fmt_num(last_val),
            "Metric_Var_Trans_Delta": change_abs_str,
            "Metric_Var_Trans_Pct": change_rate_str,
            "Trend_Direction_Label": trend_label,
            "Trend_Trajectory_Type": trajectory_type,
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

        trend_status = "increased" if diff >= 0 else "decreased"
        change_abs_str = fmt_num(abs_diff)
        logger.info(
            f"Resale Volume Brief - "
            f"{first_val}->{last_val} ({trend_status} by {change_abs_str})"
        )
        trend_label, trajectory_type, _ = self._trend_direction_words(diff)
        return {
            "Enum_Trend_Status": trajectory_type,
            "Metric_Volume_Start": fmt_num(first_val),
            "Metric_Volume_End": fmt_num(last_val),
            "Enum_Trend_Direction": trend_label,
            "Metric_Volume_Change_Abs": change_abs_str,
            "Metric_Vol_Trans_Base": fmt_num(first_val),
            "Metric_Vol_Trans_Terminal": fmt_num(last_val),
            "Metric_Var_Trans_Delta": change_abs_str,
            "Trend_Direction_Label": trend_label,
            "Trend_Trajectory_Type": trajectory_type,
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
        price_delta = fmt_num(abs(end_price - start_price))
        market_state = "seller-favorable" if is_increase else "buyer-favorable"
        return {
            "Enum_Trend_Direction": trend_adj,
            "Metric_Price_Start": fmt_num(start_price),
            "Metric_Year_Start": start_year,
            "Metric_Price_End": fmt_num(end_price),
            "Metric_Year_End": end_year,
            "Text_Change_Description": change_desc,
            "Metric_Val_Price_Base": fmt_num(start_price),
            "Metric_Val_Price_Terminal": fmt_num(end_price),
            "Metric_Var_Price_Delta": price_delta,
            "Trend_Secular_Direction": trend_adj,
            "Trend_Market_Absorption_State": market_state,
        }

    # ==================== 主题6: Annual Average Price Trend ====================

    @staticmethod
    def _trend_direction_words(diff: float) -> tuple[str, str, str]:
        """Return reusable trend words for positive and negative deltas."""
        if diff >= 0:
            return "increase", "increased", "rising"
        return "decrease", "decreased", "falling"

    def get_resale_historical_delivery_metrics(
        self,
        df_data: pd.DataFrame,
    ) -> dict[str, str]:
        """Map resale summary-table stats to the theme-5 summary contract."""
        yearly_df = df_data.copy()
        if yearly_df.empty:
            return {}
        if "metric" in yearly_df.columns:
            year_columns = [col for col in yearly_df.columns if col != "metric"]
            metrics = yearly_df.set_index("metric")
            if "trade_counts" not in metrics.index:
                return {}
            trade_row = pd.to_numeric(
                metrics.loc["trade_counts", year_columns],
                errors="coerce",
            ).fillna(0)
            yearly_df = pd.DataFrame(
                {
                    "year": [int(str(col)) for col in trade_row.index],
                    "trade_counts": trade_row.astype(int).tolist(),
                }
            )
        return self.get_resale_volume_trend_detailed(yearly_df)

    def get_resale_annual_delivery_unit_count(
        self,
        df_data: pd.DataFrame,
    ) -> dict[str, str]:
        """Map yearly resale count charts to the theme-5 summary contract."""
        return self.get_resale_volume_trend_simple(df_data)

    def get_resale_annual_average_price_trend(
        self,
        df_data: pd.DataFrame,
    ) -> dict[str, str]:
        """Map yearly resale price charts to the theme-5 summary contract."""
        return self.get_resale_price_trend(df_data)

    # ==================== 主题6：Annual Average Price Trend ====================

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
