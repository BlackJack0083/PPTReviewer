import re
from typing import Any

import pandas as pd
from loguru import logger


def preprocess_raw_data(raw_data: pd.DataFrame) -> pd.DataFrame:
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
    df: pd.DataFrame, output_path: str, sheet_name: str = "Sheet1"
) -> None:
    try:
        with pd.ExcelWriter(output_path) as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
            logger.info(f"数据已保存到Excel文件：{output_path}")
    except Exception as e:
        logger.error(f"Excel导出失败: {e}")


def create_bins(
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
        labels = [table_args.format(bins[i], bins[i + 1]) for i in range(len(bins) - 1)]
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
    result = df.groupby(group_args, observed=False).agg(agg_dict).reset_index()

    # 重命名回 col_name 以匹配预期输出
    if target_col != col_name:
        result.rename(columns={target_col: col_name}, inplace=True)

    result[col_name] = pd.to_numeric(result[col_name], errors="coerce").fillna(0)
    # 仅当结果是整数时转换，避免价格变整数
    if (result[col_name] % 1 == 0).all():
        result[col_name] = result[col_name].astype(int)

    return result


def compact_dataframe(
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

        # 合并超出的行（需要为 total 行预留 1 行，所以数据部分最多 max_rows-1 行）
        # 如果需要添加 total 行，则数据部分为 max_rows-1 行，否则为 max_rows 行
        data_max_rows = max_rows - 1 if summary_row is not None else max_rows

        if len(result_df) > data_max_rows:
            # 如果有合并行，保留 data_max_rows-1 行普通数据 + 1 行合并行 = data_max_rows 行
            kept_rows = result_df.iloc[: data_max_rows - 1]
            merged_rows = result_df.iloc[data_max_rows - 1 :]

            merge_label = get_merge_label(kept_rows.index[-1])
            merged_data = merged_rows.sum()
            merged_data.name = merge_label

            result_df = pd.concat([kept_rows, merged_data.to_frame().T])

        # 合并超出的列（需要为 total 列预留 1 列，所以数据部分最多 limit_cols-1 列）
        # 如果需要添加 total 列，则数据部分为 limit_cols-1 列，否则为 limit_cols 列
        data_max_cols = limit_cols - 1 if summary_col is not None else limit_cols

        if len(result_df.columns) > data_max_cols:
            # 如果有合并列，保留 data_max_cols-1 列普通数据 + 1 列合并列 = data_max_cols 列
            kept_cols = result_df.columns[: data_max_cols - 1]
            merged_cols = result_df.columns[data_max_cols - 1 :]

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
            f"{int(merged_lower)}" if merged_lower.is_integer() else f"{merged_lower}"
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
    df: pd.DataFrame, index_col: str, new_index_name: str | None = None
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


# def fold_large_table(
#     df: pd.DataFrame,
#     max_rows: int = 15,
#     max_cols: int = 17,
# ) -> pd.DataFrame:
#     """
#     折叠过大的表格，使其不超过指定的最大行列数
#
#     保留前 max_rows 行和前 max_cols 列，剩余的行和列分别合并为 ">= X" 的形式。
#
#     Args:
#         df: 输入 DataFrame
#         max_rows: 最大行数（默认17）
#         max_cols: 最大列数（默认19）
#
#     Returns:
#         DataFrame: 折叠后的表格
#     """
#     rows, cols = df.shape
#
#     # 如果表格没有超过限制，直接返回
#     if rows <= max_rows and cols <= max_cols:
#         return df.copy()
#
#     df = df.copy()
#
#     # 处理行折叠：保留前 max_rows 行，合并剩余行为 ">= X"
#     if rows > max_rows:
#         # 保留前 max_rows 行
#         folded_rows = df.iloc[:max_rows].copy()
#
#         # 合并剩余行为一行
#         remaining_rows = df.iloc[max_rows:]
#         if not remaining_rows.empty:
#             # 获取被合并的第一行的索引（用于生成 >= X 标签）
#             first_folded_idx = remaining_rows.index[0]
#             fold_label = f">= {first_folded_idx}"
#
#             # 对数值列求和，非数值列使用 fold_label
#             fold_row = {}
#             for col in df.columns:
#                 if pd.api.types.is_numeric_dtype(df[col]):
#                     fold_row[col] = remaining_rows[col].sum()
#                 else:
#                     fold_row[col] = fold_label
#
#             # 将合并行添加到结果中（此时是 max_rows + 1 行）
#             folded_rows = pd.concat(
#                 [folded_rows, pd.DataFrame([fold_row])], ignore_index=True
#             )
#     else:
#         folded_rows = df
#
#     # 处理列折叠：保留前 max_cols 列，合并剩余列为 ">= X"
#     if cols > max_cols:
#         # 保留前 max_cols 列
#         folded_cols = folded_rows.iloc[:, :max_cols].copy()
#
#         # 合并剩余列为一列
#         remaining_cols = folded_rows.iloc[:, max_cols:]
#         if not remaining_cols.empty:
#             # 获取被合并的第一列的列名（用于生成 >= X 标签）
#             first_folded_col = remaining_cols.columns[0]
#             fold_col_name = f">= {first_folded_col}"
#
#             # 对每一行，合并剩余列的数值
#             fold_col_data = []
#             for idx in range(len(folded_rows)):
#                 row_data = remaining_cols.iloc[idx]
#
#                 # 尝试对数值求和（Series需要用pd.to_numeric转换）
#                 numeric_vals = pd.to_numeric(row_data, errors="coerce")
#                 if not numeric_vals.isna().all():
#                     # 如果有数值，求和（忽略NaN）
#                     fold_col_data.append(numeric_vals.sum())
#                 else:
#                     # 如果没有数值，使用占位符
#                     fold_col_data.append("...")
#
#             # 将合并列添加到结果中
#             folded_cols[fold_col_name] = fold_col_data
#     else:
#         folded_cols = folded_rows
#
#     return folded_cols
#
#
# def compact_dataframe(
#     df: pd.DataFrame,
#     group_col: str,
#     value_cols: list[str],
#     keep_rows: int = 15,
#     sort_by_range: bool = True,
# ) -> pd.DataFrame:
#     """
#     通用表格压缩工具：保留前 N 行，剩余行合并为 "≥X"
#
#     Args:
#         df: 输入 DataFrame
#         group_col: 分组列名 (如 'area_range', 'price_range')
#         value_cols: 需要求和的数值列名 (如 ['supply_count', 'trade_count'])
#         keep_rows: 保留行数
#         sort_by_range: 是否尝试解析区间数值进行排序 (针对 "80-100m²" 这种格式)
#     """
#     if len(df) <= keep_rows:
#         return df.copy()
#
#     df = df.copy()
#
#     # 1. 辅助排序：提取区间下限
#     if sort_by_range:
#
#         def get_lower_bound(val):
#             # 提取字符串中的第一个数字
#             nums = re.findall(r"\d+", str(val))
#             return int(nums[0]) if nums else 999999
#
#         df["_temp_sort"] = df[group_col].apply(get_lower_bound)
#         df = df.sort_values("_temp_sort").reset_index(drop=True)
#         df = df.drop(columns=["_temp_sort"])
#
#     # 2. 切分数据
#     keep_part = df.iloc[:keep_rows].copy()
#     merge_part = df.iloc[keep_rows:].copy()
#
#     if merge_part.empty:
#         return keep_part
#
#     # 3. 生成合并行
#     # 获取被合并部分的最小下限值
#     lower_match = re.findall(r"\d+", str(merge_part[group_col].iloc[0]))
#     min_val = lower_match[0] if lower_match else "其他"
#
#     # 根据列名猜测单位 (这是一个临时的 heuristic，你可以改为参数传入)
#     # TODO 这里需要修改为更通用的方式
#     unit = "m²" if "area" in group_col.lower() or "面积" in group_col else ""
#     unit = "M" if "price" in group_col.lower() or "价格" in group_col else unit
#
#     merged_label = f"≥{min_val}{unit}"
#
#     merged_row = {group_col: merged_label}
#     for col in value_cols:
#         if col in df.columns:
#             merged_row[col] = merge_part[col].sum()
#
#     # 4. 拼装
#     result = pd.concat([keep_part, pd.DataFrame([merged_row])], ignore_index=True)
#     return result
