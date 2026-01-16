# core/data_provider.py
import re
from typing import Any

import pandas as pd
from loguru import logger

from .conclusion_generator import ConclusionGenerator
from .dao import RealEstateDAO
from .schemas import QueryFilter


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

    def get_supply_transaction_stats(self, area_range_size: int = 20) -> pd.DataFrame:
        # 1. 获取原料 (IO Bound)
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_area", "supply_sets", "trade_sets"]
        )

        analysis_config = [
            "field-constraint",
            [["Supply Count", "Sales Count"], ["area_range", "{}-{}m²", "20"]],
            [["dim_area", "supply_sets"], ["dim_area", "trade_sets"]],
            ["count", "count"],
        ]

        # 2. 加工产品 (CPU Bound)
        result_df = self.process_data_pipeline(raw_data=raw_df, options=analysis_config)
        return result_df

    def get_area_price_cross_stats(
        self, area_step: int = 20, price_step: int = 1
    ) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(self.filter, columns=["dim_area", "dim_price"])

        analysis_config = [
            "cross-constraint",
            [["area_range", "{}-{}m²", 10], ["price_range", "{}-{}M", 1]],
            ["dim_price", "dim_area"],
            ["count"],
        ]

        # 2. 加工产品
        result_df = self.process_data_pipeline(raw_data=raw_df, options=analysis_config)
        return result_df

    def get_area_distribution_stats(
        self, step: int = 20, unit: str = "m²"
    ) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_area", "trade_sets"]
        )
        analysis_config = [
            "field-constraint",
            [["Area Rng Stats"], ["area_range", "{}-{}m²", 10]],
            ["dim_area", "trade_sets"],
            ["count"],
        ]

        # 2. 加工产品
        result_df = self.process_data_pipeline(raw_data=raw_df, options=analysis_config)
        return result_df

    def get_price_distribution_stats(self, price_range_size: int = 1) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_price", "trade_sets"]
        )

        analysis_config = [
            "field-constraint",
            [["Price Rng Stats"], ["price_range", "{}-{}M", "1"]],
            ["dim_price", "trade_sets"],
            ["count"],
        ]

        # 2. 加工产品
        result_df = self.process_data_pipeline(raw_data=raw_df, options=analysis_config)
        return result_df

    # ==================== 带结论的获取方法 ====================

    def get_supply_transaction_stats_with_conclusion(
        self, area_range_size: int = 20
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取供需统计数据，并返回计算结论"""
        df = self.get_supply_transaction_stats(area_range_size)
        conclusion_vars = self.conclusion_gen.get_supply_transaction_conclusion(df)
        return df, conclusion_vars

    def get_area_price_cross_stats_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取面积x价格交叉统计，并返回计算结论"""
        df = self.get_area_price_cross_stats()
        conclusion_vars = self.conclusion_gen.get_cross_structure_conclusion(df)
        return df, conclusion_vars

    def get_area_distribution_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取面积分布，并返回计算结论"""
        df_for_ppt = self.get_area_distribution_stats()
        conclusion_vars = self.conclusion_gen.get_area_distribution_conclusion(
            df_for_ppt,
        )
        return df_for_ppt, conclusion_vars

    def get_price_distribution_with_conclusion(
        self,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """获取新房价格分布统计"""
        df_for_ppt = self.get_price_distribution_stats()
        conclusion_vars = self.conclusion_gen.get_price_distribution_conclusion(
            df_for_ppt,
        )
        return df_for_ppt, conclusion_vars

    def preprocess_raw_data(self, raw_data: pd.DataFrame) -> pd.DataFrame:
        df = raw_data.copy()
        standardization_steps = {
            "date_code": lambda x: pd.to_datetime(x, errors="coerce"),
            "supply_sets": lambda x: pd.to_numeric(x, errors="coerce"),
            "trade_sets": lambda x: pd.to_numeric(x, errors="coerce"),
            "dim_area": lambda x: pd.to_numeric(x, errors="coerce"),
            "dim_unit_price": lambda x: pd.to_numeric(x, errors="coerce"),
        }
        for column, func in standardization_steps.items():
            if column in df.columns:
                df[column] = func(df[column])
        return df

    def export_to_excel(
        self, df: pd.DataFrame, output_path: str, sheet_name: str = "Sheet1"
    ) -> None:
        try:
            with pd.ExcelWriter(output_path) as writer:
                df.to_excel(writer, index=False, sheet_name=sheet_name)
                logger.info(f"数据已保存到Excel文件：{output_path}")
        except Exception as e:
            logger.error(f"Excel导出失败: {e}")

    def create_bins(
        self,
        df: pd.DataFrame,
        column_name: str,
        range_size: float | str,
        table_args: str,
    ) -> pd.DataFrame:
        """Create bins for specified column based on the given range size."""
        df_copy = df.copy()
        min_value = df_copy[column_name].min()
        max_value = df_copy[column_name].max()

        # Handle potentially empty data
        if pd.isna(min_value) or pd.isna(max_value):
            return df_copy

        if column_name == "dim_price":
            range_size = int(float(range_size) * 100)
        else:
            range_size = int(float(range_size))

        # Avoid zero division
        if range_size == 0:
            range_size = 1

        start = int(min_value // range_size) * range_size
        end = int((max_value // range_size) + 1) * range_size
        bins = list(range(start, end + range_size, range_size))

        if len(bins) < 2:
            return df_copy

        if column_name == "dim_area":
            labels = [
                table_args.format(bins[i], bins[i + 1]) for i in range(len(bins) - 1)
            ]
            df_copy["area_range"] = pd.cut(
                df_copy["dim_area"],
                bins=bins,
                labels=labels,
                right=False,
                include_lowest=True,
            )

        elif column_name == "dim_price":
            labels = [
                table_args.format(round(bins[i] / 100, 2), round(bins[i + 1] / 100, 2))
                for i in range(len(bins) - 1)
            ]
            df_copy["price_range"] = pd.cut(
                df_copy["dim_price"],
                bins=bins,
                labels=labels,
                right=False,
                include_lowest=True,
            )
        else:
            raise ValueError("bins_lables error")

        return df_copy

    def aggregate_data(
        self,  # 修复: slef -> self
        df: pd.DataFrame,
        group_args: list[str],
        col_name: str,
        agg_func: str,
        *agg_args: Any,
    ) -> pd.DataFrame:
        """
        根据指定的列和聚合函数对数据进行聚合。
        """
        # 构建聚合参数字典
        target_col = agg_args[0] if agg_args else col_name
        agg_dict = {target_col: agg_func}

        # 确保 observed=False 兼容性
        result = (
            df.groupby(group_args, observed=False).agg(agg_dict).reset_index()
            if "observed" in pd.DataFrame.groupby.__code__.co_varnames
            else df.groupby(group_args).agg(agg_dict).reset_index()
        )

        # 重命名回 col_name 以匹配预期输出
        if target_col != col_name:
            result.rename(columns={target_col: col_name}, inplace=True)

        result[col_name] = pd.to_numeric(result[col_name], errors="coerce").fillna(0)
        # 仅当结果是整数时转换，避免价格变整数
        if (result[col_name] % 1 == 0).all():
            result[col_name] = result[col_name].astype(int)

        return result

    def compact_dataframe(
        self,
        df: pd.DataFrame,
        max_rows: int = 15,
        max_cols: int | None = None,
        range_col: str | None = None,
        mode: str = "auto",
    ) -> pd.DataFrame:
        """
        通用的数据框压缩函数，支持行、列或交叉表的合并
        """

        def extract_range_value(range_str: Any) -> float:
            """从范围字符串中提取数值"""
            if pd.isna(range_str):
                return 0.0
            nums = re.findall(r"\d+\.?\d*", str(range_str))
            return float(nums[0]) if nums else 0.0

        def get_merge_label(range_str: Any, is_price: bool = False) -> str:
            """从范围字符串生成合并标签"""
            s_val = str(range_str)
            if "." in s_val:
                match = re.search(r"(\d+\.?\d*)-(\d+\.?\d*)([^\d]*)", s_val)
            else:
                match = re.search(r"(\d+)-(\d+)([^\d]*)", s_val)

            if match:
                end_val = match.group(2)
                unit = match.group(3) if match.group(3) else ("M" if is_price else "m²")
                return f"≥{end_val}{unit}"
            return "≥其他"

        # 自动检测模式
        if mode == "auto":
            has_total_row = "total" in df.index
            has_total_col = "total" in df.columns
            mode = "crosstab" if (has_total_row or has_total_col) else "table"

        result_df = df.copy()

        # 交叉表模式
        if mode == "crosstab":
            limit_cols = max_cols if max_cols is not None else max_rows

            summary_row = None
            summary_col = None

            if "total" in result_df.index:
                summary_row = result_df.loc["total"]
                result_df = result_df.drop("total")

            if "total" in result_df.columns:
                summary_col = result_df["total"]
                result_df = result_df.drop("total", axis=1)

            # 合并超出的行
            if len(result_df) > max_rows:
                kept_rows = result_df.iloc[:max_rows]
                merged_rows = result_df.iloc[max_rows:]

                merge_label = get_merge_label(kept_rows.index[-1])
                merged_data = merged_rows.sum()
                merged_data.name = merge_label

                result_df = pd.concat([kept_rows, merged_data.to_frame().T])

            # 合并超出的列
            if len(result_df.columns) > limit_cols:
                kept_cols = result_df.columns[:limit_cols]
                merged_cols = result_df.columns[limit_cols:]

                merge_label = get_merge_label(kept_cols[-1])
                merged_data = result_df[merged_cols].sum(axis=1)

                result_df = result_df[kept_cols].copy()
                result_df[merge_label] = merged_data

            if summary_col is not None:
                result_df["total"] = result_df.sum(axis=1)

            if summary_row is not None:
                # Re-calculate total row to ensure accuracy after merging
                result_df.loc["total"] = result_df.sum()

        # 普通表格模式
        else:
            target_col = range_col
            if target_col is None:
                for col in result_df.columns:
                    if "range" in col or result_df[col].dtype == "object":
                        target_col = col
                        break

            # Fallback
            if target_col is None:
                target_col = result_df.columns[0]

            # 临时列用于排序
            result_df["_lower"] = result_df[target_col].apply(extract_range_value)
            result_df = result_df.sort_values("_lower").reset_index(drop=True)

            if len(result_df) <= max_rows:
                return result_df.drop(columns=["_lower"])

            keep_part = result_df.iloc[:max_rows]
            merge_part = result_df.iloc[max_rows:]

            merged_lower = merge_part["_lower"].min()
            is_price = "price" in str(target_col)

            lower_str = (
                f"{int(merged_lower)}"
                if merged_lower.is_integer()
                else f"{merged_lower}"
            )
            merged_name = f"≥{lower_str}{'M' if is_price else 'm²'}"

            merged_row = {target_col: merged_name}
            for col in result_df.columns:
                if col != target_col and col != "_lower":
                    if pd.api.types.is_numeric_dtype(result_df[col]):
                        merged_row[col] = merge_part[col].sum()
                    else:
                        merged_row[col] = ""

            result_df = pd.concat(
                [
                    keep_part.drop(columns=["_lower"]),
                    pd.DataFrame([merged_row]),
                ],
                ignore_index=True,
            )

        return result_df

    def transpose_dataframe(
        self, df: pd.DataFrame, index_col: str, new_index_name: str | None = None
    ) -> pd.DataFrame:
        """
        通用数据框转置函数。
        """
        if index_col not in df.columns:
            return df

        transposed = df.set_index(index_col).T
        transposed.columns.name = None
        result = transposed.reset_index()

        target_name = new_index_name if new_index_name else index_col
        result.rename(columns={"index": target_name}, inplace=True)

        return result

    def process_data_pipeline(
        self,
        raw_data: pd.DataFrame,
        options: list[Any],
        output_path: str = "./temp/output.xlsx",
    ) -> pd.DataFrame:
        df_data = self.preprocess_raw_data(raw_data)
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
            df_data_copy = self.create_bins(
                df_data_copy, "dim_price", parameterInterval, parameterizedTemplate
            )
        elif option_range == ["area_range"]:
            df_data_copy = self.create_bins(
                df_data_copy, "dim_area", parameterInterval, parameterizedTemplate
            )
        else:
            # 交叉表分箱
            param_temp_a = constraintInfo[0][1]
            param_int_a = constraintInfo[0][2]
            param_temp_b = constraintInfo[1][1]
            param_int_b = constraintInfo[1][2]

            df_data_bin = self.create_bins(
                df_data_copy, "dim_area", param_int_a, param_temp_a
            )
            df_data_copy = self.create_bins(
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

                res = self.aggregate_data(
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
                result = self.compact_dataframe(result, max_rows=15)

            if tableType == "constraint-field":
                pivot_col = option_range[0]
                result = self.transpose_dataframe(result, index_col=pivot_col)

        elif tableType == "cross-constraint":
            filtered_data = df_data_copy
            if "price_range" in option_range and len(option_range) >= 2:
                result = pd.crosstab(
                    filtered_data[option_range[0]],
                    filtered_data[option_range[1]],
                    margins=True,
                    margins_name="total",
                )
                result = self.compact_dataframe(
                    result, max_rows=14, max_cols=16, mode="crosstab"
                )
                result.index.name = "price_area"
                result.reset_index(inplace=True)

        # 移除文件写入后再读取的冗余逻辑，直接返回内存中的 DataFrame
        return result
