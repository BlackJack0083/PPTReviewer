from typing import Any

import pandas as pd
from loguru import logger

from utils.data_utils import *


class StatTransformer:
    """
    数据转换器
    职责：负责清洗、分箱、聚合、重塑
    """
    def process_data_pipeline(
        self,
        raw_data: pd.DataFrame,
        options: list[Any],
        output_path: str = "./temp/output.xlsx",
    ) -> pd.DataFrame:
        df_data = preprocess_raw_data(raw_data)
        df_data_copy = df_data.copy()

        tableType = options[0]
        constraintInfo = options[1]
        dataSourceField = options[2]
        calculationOperation = options[3]

        option_range = []

        if tableType in ["field-constraint", "constraint-field"]:
            table_col_names = constraintInfo[0]
            constraint_type = constraintInfo[1][0]
            parameterizedTemplate = constraintInfo[1][1]
            parameterInterval = constraintInfo[1][2]
            option_range.append(constraint_type)
        else:
            for i in range(len(constraintInfo)):
                option_range.append(constraintInfo[i][0])

        # 时间维度处理
        if option_range == ["month"]:
            df_data_copy["month"] = df_data_copy["date_code"].dt.to_period("M")
        elif option_range == ["year"]:
            df_data_copy["year"] = df_data_copy["date_code"].dt.year
        # 分箱逻辑
        elif option_range == ["price_range"]:
            df_data_copy = create_bins(
                df_data_copy, "dim_price", parameterInterval, parameterizedTemplate
            )
        elif option_range == ["area_range"]:
            df_data_copy = create_bins(
                df_data_copy, "dim_area", parameterInterval, parameterizedTemplate
            )
        else:
            # 交叉表分箱
            param_temp_a = constraintInfo[0][1]
            param_int_a = constraintInfo[0][2]
            param_temp_b = constraintInfo[1][1]
            param_int_b = constraintInfo[1][2]

            df_data_bin = create_bins(
                df_data_copy, "dim_area", param_int_a, param_temp_a
            )
            df_data_copy = create_bins(
                df_data_bin, "dim_price", param_int_b, param_temp_b
            )

        result = pd.DataFrame()

        # 聚合逻辑
        if tableType in ["field-constraint", "constraint-field"]:
            filtered_data = df_data_copy
            res_list = []

            # 使用 enumerate 替代 zip(strict=False) 以兼容 Python < 3.10
            # 且 zip(a,b,c) 可能会有长度不一致风险，这里假设配置是齐的
            for idx, table_col_name in enumerate(table_col_names):
                db_col_name = dataSourceField[idx]
                calc_op = calculationOperation[idx]

                # 特殊逻辑处理
                current_filter = filtered_data
                agg_target = db_col_name

                if db_col_name == ["dim_area", "supply_sets"]:
                    agg_target = "dim_area"
                    current_filter = filtered_data[filtered_data["supply_sets"] == 1.0]
                elif db_col_name == ["dim_area", "trade_sets"]:
                    agg_target = "dim_area"
                    current_filter = filtered_data[filtered_data["trade_sets"] == 1.0]

                res = aggregate_data(
                    current_filter,
                    option_range,
                    table_col_name,
                    calc_op,
                    agg_target,
                )
                res_list.append(res)

            if res_list:
                result = res_list[0]
                for res in res_list[1:]:
                    result = pd.merge(result, res, on=option_range[0], how="outer")

            if option_range in [["area_range"], ["price_range"]]:
                result = compact_dataframe(result, max_rows=15)

            if tableType == "constraint-field":
                pivot_col = option_range[0]
                result = transpose_dataframe(result, index_col=pivot_col)

        elif tableType == "cross-constraint":
            filtered_data = df_data_copy
            if "price_range" in option_range and len(option_range) >= 2:
                result = pd.crosstab(
                    filtered_data[option_range[0]],
                    filtered_data[option_range[1]],
                    margins=True,
                    margins_name="total",
                )
                result = compact_dataframe(
                    result, max_rows=14, max_cols=16, mode="crosstab"
                )
                result.index.name = "price_area"
                result.reset_index(inplace=True)

        export_to_excel(result, output_path)
        result = pd.read_excel(output_path)
        return result
    # @staticmethod
    # def bin_and_agg_supply_stats(
    #     df: pd.DataFrame, step: int = 20, compact_rows: int = 15
    # ) -> pd.DataFrame:
    #     """
    #     供应统计数据分箱聚合
    #     """
    #     if df.empty:
    #         return pd.DataFrame()
    #
    #     df = df.copy()
    #
    #     # 业务逻辑：分箱
    #     df["bin_start"] = (df["dim_area"] // step) * step
    #     df["Category"] = df["bin_start"].apply(lambda x: f"{int(x)}-{int(x+step)}m²")
    #
    #     # 业务逻辑：聚合
    #     stats = (
    #         df.groupby("Category", observed=False)
    #         .agg(
    #             {
    #                 "supply_sets": "sum",
    #                 "trade_sets": "sum",
    #             }
    #         )
    #         .reset_index()
    #     )
    #
    #     # 压缩长尾
    #     stats = compact_dataframe(
    #         stats, "Category", ["supply_sets", "trade_sets"], keep_rows=compact_rows
    #     )
    #
    #     # 4. 展现逻辑：重命名与转置
    #     stats = stats.rename(
    #         columns={"supply_sets": "Supply", "trade_sets": "Transaction"}
    #     )
    #     return stats.set_index("Category").T
    #
    # @staticmethod
    # def pivot_area_price(
    #     df: pd.DataFrame, area_step: int = 20, price_step: int = 1
    # ) -> pd.DataFrame:
    #     """处理面积x价格交叉表逻辑"""
    #     if df.empty:
    #         return pd.DataFrame()
    #
    #     # 这里的逻辑从 Provider 移过来了
    #     max_area = int(df["dim_area"].max())
    #     area_bins = range(0, max_area + area_step * 2, area_step)
    #     area_labels = [f"{i}-{i+area_step}m²" for i in area_bins[:-1]]
    #
    #     max_price = int(df["dim_price"].max())
    #     price_bins = range(0, max_price + price_step * 2, price_step)
    #     price_labels = [f"{i}-{i+price_step}M" for i in price_bins[:-1]]
    #
    #     # Cut
    #     df["Area_Range"] = pd.cut(df["dim_area"], bins=area_bins, labels=area_labels)
    #     df["Price_Range"] = pd.cut(
    #         df["dim_price"], bins=price_bins, labels=price_labels
    #     )
    #
    #     result = pd.crosstab(df["Area_Range"], df["Price_Range"])
    #
    #     # 如果表格过大，进行折叠
    #     from utils.data_utils import fold_large_table
    #
    #     if result.shape[0] > 15 or result.shape[1] > 17:
    #         original_shape = result.shape
    #         result = fold_large_table(result, max_rows=15, max_cols=17)
    #         logger.info(f"Cross-table folded from {original_shape} to {result.shape}")
    #
    #     return result
    #
    # @staticmethod
    # def bin_area_distribution(
    #     df: pd.DataFrame, step: int = 20, compact_rows: int = 15
    # ) -> pd.DataFrame:
    #     """
    #     面积分布统计 - 分箱聚合
    #
    #     用于 Resale-House 和 New-House 的面积分布分析
    #
    #     Args:
    #         df: 原始数据，包含 dim_area 和 trade_sets 列
    #         step: 面积分箱步长（默认20）
    #         compact_rows: 压缩长尾保留行数
    #
    #     Returns:
    #         DataFrame: 包含 area_range 和 trade_sets 列
    #     """
    #     if df.empty:
    #         return pd.DataFrame()
    #
    #     df = df.copy()
    #
    #     # 分箱
    #     df["bin_start"] = (df["dim_area"] // step) * step
    #     df["area_range"] = df["bin_start"].apply(lambda x: f"{int(x)}-{int(x+step)}m²")
    #
    #     # 聚合
    #     stats = (
    #         df.groupby("area_range", observed=False)
    #         .agg({"trade_sets": "sum"})
    #         .reset_index()
    #     )
    #
    #     # 压缩长尾
    #     from utils import compact_dataframe
    #
    #     stats = compact_dataframe(
    #         stats, "area_range", ["trade_sets"], keep_rows=compact_rows
    #     )
    #
    #     # 将 area_range 设为索引，然后转置。
    #     # 结果：Columns变成面积段(X轴)，Index变成'trade_sets'(系列名)
    #     return stats.set_index("area_range").T
    #
    # @staticmethod
    # def bin_price_distribution(
    #     df: pd.DataFrame, step: int = 1, compact_rows: int = 15
    # ) -> pd.DataFrame:
    #     """
    #     价格分布统计 - 分箱聚合
    #
    #     用于 New-House Market Capacity Analysis 的价格分布
    #
    #     Args:
    #         df: 原始数据，包含 dim_price 和 trade_sets 列
    #         step: 价格分箱步长（默认1，单位M）
    #         compact_rows: 压缩长尾保留行数
    #
    #     Returns:
    #         DataFrame: 包含 price_range 和 trade_sets 列
    #     """
    #     if df.empty:
    #         return pd.DataFrame()
    #
    #     df = df.copy()
    #
    #     # 分箱
    #     df["bin_start"] = (df["dim_price"] // step) * step
    #     df["price_range"] = df["bin_start"].apply(lambda x: f"{int(x)}-{int(x+step)}M")
    #
    #     # 聚合
    #     stats = (
    #         df.groupby("price_range", observed=False)
    #         .agg({"trade_sets": "sum"})
    #         .reset_index()
    #     )
    #
    #     # 压缩长尾
    #     from utils import compact_dataframe
    #
    #     stats = compact_dataframe(
    #         stats, "price_range", ["trade_sets"], keep_rows=compact_rows
    #     )
    #
    #     return stats.set_index("price_range").T
