# core/data_provider.py
import re

import pandas as pd

from .conclusion_generator import ConclusionGenerator
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

        # 初始化结论生成器
        self.conclusion_gen = ConclusionGenerator(start_year, end_year, block)

    def get_supply_transaction_stats(self, area_range_size=20) -> pd.DataFrame:
        # 1. 获取原料 (IO Bound)
        # 我们只需要这几列，减少网络传输压力
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

    def get_area_price_cross_stats(self, area_step=20, price_step=1) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(self.filter, columns=["dim_area", "dim_price"])

        analysis_config = ["cross-constraint",
                          [["area_range", '{}-{}m²', 10],["price_range", '{}-{}M', 1]],
                          ["dim_price", "dim_area"],
                          ["count"]]

        # 2. 加工产品 (CPU Bound)
        result_df = self.process_data_pipeline(raw_data=raw_df, options=analysis_config)

        return result_df

    def get_area_distribution_stats(self, step=20, unit="m²") -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_area", "trade_sets"]
        )
        analysis_config = ["field-constraint",
                          [["Area Rng Stats"], ["area_range", '{}-{}m²', 10]],
                          ["dim_area", "trade_sets"],
                          ["count"]]

        # 2. 加工产品 (CPU Bound)
        result_df = self.process_data_pipeline(raw_data=raw_df, options=analysis_config)

        return result_df

    def get_price_distribution_stats(self, price_range_size=1) -> pd.DataFrame:
        # 1. 获取原料
        raw_df = self.dao.fetch_raw_data(
            self.filter, columns=["dim_price", "trade_sets"]
        )

        analysis_config = ["field-constraint",
                          [['Price Rng Stats'], ["price_range", '{}-{}M', '1']],
                          ["dim_price", "trade_sets"],
                          ["count"]]

        # 2. 加工产品 (CPU Bound)
        result_df = self.process_data_pipeline(raw_data=raw_df, options=analysis_config)

        return result_df

    # ==================== 带结论的获取方法 ====================

    def get_supply_transaction_stats_with_conclusion(
        self, area_range_size=20
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """
        获取供需统计数据，并返回计算结论

        Returns:
            Tuple[DataFrame, dict]:
        """
        df = self.get_supply_transaction_stats(area_range_size)

        # 计算结论
        conclusion_vars = self.conclusion_gen.get_supply_transaction_conclusion(df)

        return df, conclusion_vars

    def get_area_price_cross_stats_with_conclusion(
        self
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """
        获取面积x价格交叉统计，并返回计算结论

        Returns:
            Tuple[DataFrame, dict]: (数据, 结论变量字典)
        """
        df = self.get_area_price_cross_stats()

        # 计算结论
        conclusion_vars = self.conclusion_gen.get_cross_structure_conclusion(df)

        return df, conclusion_vars

    def get_area_distribution_with_conclusion(
        self
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """
        获取面积分布，并返回计算结论

        Args:
            step: 分箱步长（默认20）
            unit: 单位（默认'm²'）

        Returns:
            Tuple[DataFrame, dict]: (数据, 结论变量字典)
        """
        # 1. 获取给 PPT 用的数据 (已经是转置后的宽表，适合画图)
        df_for_ppt = self.get_area_distribution_stats()

        # # 2. 准备给计算器用的数据 (还原回长表)
        # # 逻辑：先转置回去(.T)，把索引恢复成列(.reset_index)
        # df_for_calc = df_for_ppt.T.reset_index()

        # 3. 计算结论
        conclusion_vars = self.conclusion_gen.get_area_distribution_conclusion(
            df_for_ppt,
        )

        # 4. 返回给 Context (df 给图表用，vars 给文本用)
        return df_for_ppt, conclusion_vars

    def get_price_distribution_with_conclusion(
        self
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """
        获取新房价格分布统计

        用于 New-House Market Capacity Analysis 中的价格分布

        Args:
            price_range_size: 价格分箱步长（默认1M）

        Returns:
            DataFrame: 包含 price_range 和 trade_sets 列
        """
        # 1. 获取给 PPT 用的数据 (宽表)
        df_for_ppt = self.get_price_distribution_stats()

        # # 2. 准备给计算器用的数据 (还原为长表)
        # df_for_calc = df_for_ppt.T.reset_index()

        # 3. 计算结论
        conclusion_vars = self.conclusion_gen.get_price_distribution_conclusion(
            df_for_ppt,  # ✅ 传入还原后的数据
            # price_col="price_range",
            # count_col="trade_sets",
        )

        return df_for_ppt, conclusion_vars

    def preprocess_raw_data(self, raw_data):
        df = raw_data
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
    ):
        with pd.ExcelWriter(output_path) as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
            print(
                "supply_and_sales_counts_and_share运行成功,数据已保存到Excel文件：",
                output_path,
            )

    def create_bins(self, df, column_name, range_size, table_args):
        """
        Create bins for specified column based on the given range size.
        """

        min_value = df[column_name].min()
        max_value = df[column_name].max()
        if column_name == "dim_price":
            range_size = int(float(range_size) * 100)
        range_size = int(range_size)

        start = int(min_value // range_size) * range_size
        end = int((max_value // range_size) + 1) * range_size
        bins = list(range(start, end + range_size, range_size))
        print("bins:", bins)

        if column_name == "dim_area":
            labels = [
                table_args.format(bins[i], bins[i + 1]) for i in range(len(bins) - 1)
            ]
            df["area_range"] = pd.cut(
                df["dim_area"],
                bins=bins,
                labels=labels,
                right=False,
                include_lowest=True,
            )
            return df

        elif column_name == "dim_price":
            labels = [
                table_args.format(round(bins[i] / 100, 2), round(bins[i + 1] / 100, 2))
                for i in range(len(bins) - 1)
            ]
            df["price_range"] = pd.cut(
                df["dim_price"],
                bins=bins,
                labels=labels,
                right=False,
                include_lowest=True,
            )
            return df

        else:
            raise ValueError("bins_lables error")

    def aggregate_data(
        slef,
        df: pd.DataFrame,
        group_args: list[str],
        col_name: str,
        agg_func: str,
        *agg_args,
    ) -> pd.DataFrame:
        """
        根据指定的列和聚合函数对数据进行聚合。

        参数:
        df (pd.DataFrame): 要处理的数据框。
        group_args (list): 分组依据的列名列表。
        col_name (str): 返回结果中聚合后的列名。
        agg_func (str): 聚合函数名称，例如 'count' 或 'sum'。
        *agg_args: 额外的聚合参数，视聚合函数而定。

        返回:
        pd.DataFrame: 包含聚合结果的数据框。
        """
        print("aggregate_data开始运行")
        # 构建聚合参数字典
        agg_dict = {col_name: (agg_args[0] if agg_args else col_name, agg_func)}
        result = df.groupby(group_args, observed=False).agg(**agg_dict).reset_index()
        result[col_name] = result[col_name].astype(int)
        # 执行分组和聚合
        return result

    def compact_dataframe(
        self, df, max_rows=15, max_cols=None, range_col=None, mode="auto"
    ):
        """
        通用的数据框压缩函数，支持行、列或交叉表的合并
        """

        def extract_range_value(range_str):
            """从范围字符串中提取数值"""
            if pd.isna(range_str):
                return 0
            # 修正：去掉了多余的反斜杠
            nums = re.findall(r"\d+\.?\d*", str(range_str))
            return float(nums[0]) if nums else 0

        def get_merge_label(range_str, is_price=False):
            """从范围字符串生成合并标签"""
            # 修正：去掉了多余的反斜杠
            if "." in str(range_str):
                match = re.search(r"(\d+\.?\d*)-(\d+\.?\d*)([^\d]*)", str(range_str))
            else:
                match = re.search(r"(\d+)-(\d+)([^\d]*)", str(range_str))

            if match:
                end_val = match.group(2)
                unit = (
                    match.group(3) if match.group(3) else ("M" if is_price else "m²")
                )
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
            if max_cols is None:
                max_cols = max_rows

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
            if len(result_df.columns) > max_cols:
                kept_cols = result_df.columns[:max_cols]
                merged_cols = result_df.columns[max_cols:]

                merge_label = get_merge_label(kept_cols[-1])
                merged_data = result_df[merged_cols].sum(axis=1)

                result_df = result_df[kept_cols]
                result_df[merge_label] = merged_data

            if summary_col is not None:
                result_df["total"] = result_df.sum(axis=1)

            if summary_row is not None:
                result_df.loc["total"] = result_df.sum()

        # 普通表格模式
        else:
            if range_col is None:
                for col in result_df.columns:
                    if "range" in col or result_df[col].dtype == "object":
                        range_col = col
                        break

            if range_col is None:
                range_col = result_df.columns[0]

            result_df["_lower"] = result_df[range_col].apply(extract_range_value)
            result_df = result_df.sort_values("_lower").reset_index(drop=True)

            if len(result_df) <= max_rows:
                return result_df.drop(columns="_lower")

            keep_part = result_df.iloc[:max_rows]
            merge_part = result_df.iloc[max_rows:]

            merged_lower = merge_part["_lower"].min()
            is_price = "price" in range_col
            # 确保 merged_lower 是整数展示，除非它有小数
            lower_str = (
                f"{int(merged_lower)}"
                if merged_lower.is_integer()
                else f"{merged_lower}"
            )
            merged_name = f"≥{lower_str}{'M' if is_price else 'm²'}"

            merged_row = {range_col: merged_name}
            for col in result_df.columns:
                if col != range_col and col != "_lower":
                    if pd.api.types.is_numeric_dtype(result_df[col]):
                        merged_row[col] = merge_part[col].sum()
                    else:
                        merged_row[col] = ""

            result_df = pd.concat(
                [keep_part.drop(columns="_lower"), pd.DataFrame([merged_row])],
                ignore_index=True,
            )

        return result_df

    def transpose_dataframe(
        self, df: pd.DataFrame, index_col: str, new_index_name: str = None
    ) -> pd.DataFrame:
        """
        通用数据框转置函数。
        将指定的索引列转为列头，原来的列名变为新的一列。

        :param df: 输入数据框
        :param index_col: 用作转置后列头的列名 (例如 'year', 'month', 'category')
        :param new_index_name: 转置后第一列的新名称 (如果不传，默认使用 index_col)
        :return: 转置后的数据框
        """
        if index_col not in df.columns:
            return df

        # 1. 设置索引并转置
        transposed = df.set_index(index_col).T

        # 2. 清理索引名称 (移除 columns.name)
        transposed.columns.name = None

        # 3. 重置索引，将原来的列名变成一列数据
        result = transposed.reset_index()

        # 4. 重命名第一列
        target_name = new_index_name if new_index_name else index_col
        result.rename(columns={"index": target_name}, inplace=True)

        return result

    def process_data_pipeline(
        self, raw_data, options, output_path="./temp/output.xlsx"
    ):
        df_data = self.preprocess_raw_data(raw_data)
        df_data_copy = df_data.copy()
        print("process_data_pipeline 开始执行了")
        tableType, constraintInfo, dataSourceField, calculationOperation = options
        option_range = []
        if tableType == "field-constraint" or tableType == "constraint-field":
            table_col_names = constraintInfo[0]
            constraint_type = constraintInfo[1][0]
            parameterizedTemplate = constraintInfo[1][1]
            parameterInterval = constraintInfo[1][2]
            option_range.append(constraint_type)

        else:
            for i in range(len(constraintInfo)):
                option_range.append(constraintInfo[i][0])

        if option_range == ["month"] or option_range == ["year"]:
            if option_range == ["month"]:
                df_data_copy["month"] = df_data_copy["date_code"].dt.to_period("M")
            else:
                df_data_copy["year"] = df_data_copy["date_code"].dt.year
        else:
            if option_range == ["price_range"]:
                df_data_copy = self.create_bins(
                    df_data_copy, "dim_price", parameterInterval, parameterizedTemplate
                )
            elif option_range == ["area_range"]:
                df_data_copy = self.create_bins(
                    df_data_copy, "dim_area", parameterInterval, parameterizedTemplate
                )
            else:
                parameterizedTemplate_a = constraintInfo[0][1]
                parameterInterval_a = constraintInfo[0][2]

                parameterizedTemplate_b = constraintInfo[1][1]
                parameterInterval_b = constraintInfo[1][2]

                df_data_bin = self.create_bins(
                    df_data_copy,
                    "dim_area",
                    parameterInterval_a,
                    parameterizedTemplate_a,
                )
                df_data_copy = self.create_bins(
                    df_data_bin,
                    "dim_price",
                    parameterInterval_b,
                    parameterizedTemplate_b,
                )

        res_list = []
        if tableType == "field-constraint" or tableType == "constraint-field":
            filtered_data = df_data_copy
            for table_col_name, database_col_name, arg_fun in zip(
                table_col_names, dataSourceField, calculationOperation, strict=False
            ):
                if database_col_name == ["dim_area", "supply_sets"]:
                    database_col_name = "dim_area"
                    filtered_data = df_data_copy[df_data_copy["supply_sets"] == 1.0]
                elif database_col_name == ["dim_area", "trade_sets"]:
                    database_col_name = "dim_area"
                    filtered_data = df_data_copy[df_data_copy["trade_sets"] == 1.0]

                res = self.aggregate_data(
                    filtered_data,
                    option_range,
                    table_col_name,
                    arg_fun,
                    database_col_name,
                )
                res_list.append(res)

            result = res_list[0]
            for res in res_list[1:]:
                result = pd.merge(result, res, on=option_range[0], how="outer")

            if option_range == ["area_range"] or option_range == ["price_range"]:
                result = self.compact_dataframe(result, max_rows=15)

            if tableType == "constraint-field":
                pivot_col = option_range[0]
                result = self.transpose_dataframe(result, index_col=pivot_col)

        elif tableType == "cross-constraint":
            filtered_data = df_data_copy
            if "price_range" in option_range:
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
        self.export_to_excel(result, output_path)
        result = pd.read_excel(output_path)
        return result
