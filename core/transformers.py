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
        elif config.table_type == "cross-constrain":
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
        result = compact_dataframe(result, max_rows=14, max_cols=16, mode="crosstab")

        # 整理索引，保持原有格式习惯
        result.index.name = "price_area"
        result.reset_index(inplace=True)

        return result

    # def process_data_pipeline(
    #     self,
    #     raw_data: pd.DataFrame,
    #     options: list[Any],
    #     output_path: str = "./temp/output.xlsx",
    # ) -> pd.DataFrame:
    # df_data = preprocess_raw_data(raw_data)
    # df_data_copy = df_data.copy()

    # tableType = options[0]
    # constraintInfo = options[1]
    # dataSourceField = options[2]
    # calculationOperation = options[3]

    # option_range = []

    # if tableType in ["field-constraint", "constraint-field"]:
    #     table_col_names = constraintInfo[0]
    #     constraint_type = constraintInfo[1][0]
    #     parameterizedTemplate = constraintInfo[1][1]
    #     parameterInterval = constraintInfo[1][2]
    #     option_range.append(constraint_type)
    # else:
    #     for i in range(len(constraintInfo)):
    #         option_range.append(constraintInfo[i][0])

    # # 时间维度处理
    # if option_range == ["month"]:
    #     df_data_copy["month"] = df_data_copy["date_code"].dt.to_period("M")
    # elif option_range == ["year"]:
    #     df_data_copy["year"] = df_data_copy["date_code"].dt.year
    # # 分箱逻辑
    # elif option_range == ["price_range"]:
    #     df_data_copy = create_bins(
    #         df_data_copy, "dim_price", parameterInterval, parameterizedTemplate
    #     )
    # elif option_range == ["area_range"]:
    #     df_data_copy = create_bins(
    #         df_data_copy, "dim_area", parameterInterval, parameterizedTemplate
    #     )
    # else:
    #     # 交叉表分箱
    #     param_temp_a = constraintInfo[0][1]
    #     param_int_a = constraintInfo[0][2]
    #     param_temp_b = constraintInfo[1][1]
    #     param_int_b = constraintInfo[1][2]

    #     df_data_bin = create_bins(
    #         df_data_copy, "dim_area", param_int_a, param_temp_a
    #     )
    #     df_data_copy = create_bins(
    #         df_data_bin, "dim_price", param_int_b, param_temp_b
    #     )

    # result = pd.DataFrame()

    # # 聚合逻辑
    # if tableType in ["field-constraint", "constraint-field"]:
    #     filtered_data = df_data_copy
    #     res_list = []

    #     # 使用 enumerate 替代 zip(strict=False) 以兼容 Python < 3.10
    #     # 且 zip(a,b,c) 可能会有长度不一致风险，这里假设配置是齐的
    #     for idx, table_col_name in enumerate(table_col_names):
    #         db_col_name = dataSourceField[idx]
    #         calc_op = calculationOperation[idx]

    #         # 特殊逻辑处理
    #         current_filter = filtered_data
    #         agg_target = db_col_name

    #         if db_col_name == ["dim_area", "supply_sets"]:
    #             agg_target = "dim_area"
    #             current_filter = filtered_data[filtered_data["supply_sets"] == 1.0]
    #         elif db_col_name == ["dim_area", "trade_sets"]:
    #             agg_target = "dim_area"
    #             current_filter = filtered_data[filtered_data["trade_sets"] == 1.0]

    #         res = aggregate_data(
    #             current_filter,
    #             option_range,
    #             table_col_name,
    #             calc_op,
    #             agg_target,
    #         )
    #         res_list.append(res)

    #     if res_list:
    #         result = res_list[0]
    #         for res in res_list[1:]:
    #             result = pd.merge(result, res, on=option_range[0], how="outer")

    #     if option_range in [["area_range"], ["price_range"]]:
    #         result = compact_dataframe(result, max_rows=15)

    #     if tableType == "constraint-field":
    #         pivot_col = option_range[0]
    #         result = transpose_dataframe(result, index_col=pivot_col)

    # elif tableType == "cross-constraint":
    #     filtered_data = df_data_copy
    #     if "price_range" in option_range and len(option_range) >= 2:
    #         result = pd.crosstab(
    #             filtered_data[option_range[0]],
    #             filtered_data[option_range[1]],
    #             margins=True,
    #             margins_name="total",
    #         )
    #         result = compact_dataframe(
    #             result, max_rows=14, max_cols=16, mode="crosstab"
    #         )
    #         result.index.name = "price_area"
    #         result.reset_index(inplace=True)

    # export_to_excel(result, output_path)
    # result = pd.read_excel(output_path)
    # return result
