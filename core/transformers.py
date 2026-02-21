import pandas as pd
from loguru import logger

from utils.data_utils import (
    compact_dataframe,
    create_bins,
    preprocess_raw_data,
)

from .schemas import BinningRule, TableAnalysisConfig


class StatTransformer:
    """
    数据转换器
    职责：负责清洗、分箱、聚合、重塑
    """

    def process_data_pipeline(
        self,
        raw_data: pd.DataFrame,
        config: TableAnalysisConfig,
        output_path: str = "./temp/output.xlsx",
    ) -> pd.DataFrame:

        # 1. 基础清洗 (类型转换等)
        df = preprocess_raw_data(raw_data)

        # 2. 应用维度分箱 (Binning)
        for dim in config.dimensions:
            df = self._apply_binning(df, dim)

        # 3. 根据表格类型分流处理
        if config.table_type == "field-constraint":
            result = self._process_standard_table(df, config)
        elif config.table_type == "cross-constraint":
            result = self._process_crosstab_table(df, config)
        else:
            raise ValueError(f"Unknown table type: {config.table_type}")

        # 4. 导出
        # from utils.data_utils import export_to_excel
        # export_to_excel(result, output_path)

        return result

    def _apply_binning(self, df: pd.DataFrame, rule: BinningRule) -> pd.DataFrame:
        """执行分箱逻辑"""
        if rule.method == "range":
            # 调用 utils 中的 create_bins
            return create_bins(
                df,
                column_name=rule.source_col,
                range_size=rule.step,
                table_args=rule.format_str,
            )
        elif rule.method == "period":
            if rule.time_granularity == "year":
                df[rule.target_col] = df[rule.source_col].dt.year
            elif rule.time_granularity == "month":
                df[rule.target_col] = df[rule.source_col].dt.to_period("M")
        return df

    def _process_standard_table(
        self, df: pd.DataFrame, config: TableAnalysisConfig
    ) -> pd.DataFrame:
        """处理标准聚合表 (对应原 field-constraint)"""
        results = []
        if not config.dimensions:
            return pd.DataFrame()

        # 获取主维度 (通常是第一个维度，如 area_range)
        primary_dim = config.dimensions[0].target_col

        for metric in config.metrics:
            # 1. 过滤 (显式处理 supply_sets=1 这种逻辑)
            temp_df = df.copy()
            if metric.filter_condition:
                for k, v in metric.filter_condition.items():
                    temp_df = temp_df[temp_df[k] == v]

            # 2. 聚合
            # 使用原生 pandas 语法，比原来的 aggregate_data 包装器更清晰
            try:
                agg_df = (
                    temp_df.groupby(primary_dim, observed=False)
                    .agg({metric.source_col: metric.agg_func})
                    .rename(columns={metric.source_col: metric.name})
                    .reset_index()
                )

                agg_df[metric.name] = agg_df[metric.name].fillna(0)

                results.append(agg_df)
            except KeyError as e:
                logger.error(f"Aggregation failed for {metric.name}: {e}")
                continue

        # 3. 合并所有指标列
        if not results:
            return pd.DataFrame()

        final_df = results[0]
        for res in results[1:]:
            final_df = pd.merge(final_df, res, on=primary_dim, how="outer")

        # 4. 压缩长尾 (针对 Range 类型的维度自动压缩)
        if primary_dim in ["area_range", "price_range"]:
            final_df = compact_dataframe(final_df, max_rows=15)

        return final_df

    def _process_crosstab_table(
        self, df: pd.DataFrame, config: TableAnalysisConfig
    ) -> pd.DataFrame:
        """处理交叉表 (对应原 cross-constraint)"""
        if not config.crosstab_row or not config.crosstab_col:
            raise ValueError("Crosstab requires row and col dimensions")

        # 交叉表统计通常只支持一个指标
        metric = config.metrics[0]

        result = pd.crosstab(
            index=df[config.crosstab_row],
            columns=df[config.crosstab_col],
            values=df[metric.source_col] if metric.agg_func != "count" else None,
            aggfunc=metric.agg_func if metric.agg_func != "count" else None,
            margins=True,
            margins_name="total",
        )

        # 压缩交叉表
        result = compact_dataframe(result, max_rows=16, max_cols=18, mode="crosstab")

        # 整理索引，保持原有格式习惯
        result.index.name = "price_area"
        result.reset_index(inplace=True)

        return result
