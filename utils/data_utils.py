import re

import pandas as pd


def fold_large_table(
    df: pd.DataFrame,
    max_rows: int = 15,
    max_cols: int = 17,
) -> pd.DataFrame:
    """
    折叠过大的表格，使其不超过指定的最大行列数

    保留前 max_rows 行和前 max_cols 列，剩余的行和列分别合并为 ">= X" 的形式。

    Args:
        df: 输入 DataFrame
        max_rows: 最大行数（默认17）
        max_cols: 最大列数（默认19）

    Returns:
        DataFrame: 折叠后的表格
    """
    rows, cols = df.shape

    # 如果表格没有超过限制，直接返回
    if rows <= max_rows and cols <= max_cols:
        return df.copy()

    df = df.copy()

    # 处理行折叠：保留前 max_rows 行，合并剩余行为 ">= X"
    if rows > max_rows:
        # 保留前 max_rows 行
        folded_rows = df.iloc[:max_rows].copy()

        # 合并剩余行为一行
        remaining_rows = df.iloc[max_rows:]
        if not remaining_rows.empty:
            # 获取被合并的第一行的索引（用于生成 >= X 标签）
            first_folded_idx = remaining_rows.index[0]
            fold_label = f">= {first_folded_idx}"

            # 对数值列求和，非数值列使用 fold_label
            fold_row = {}
            for col in df.columns:
                if pd.api.types.is_numeric_dtype(df[col]):
                    fold_row[col] = remaining_rows[col].sum()
                else:
                    fold_row[col] = fold_label

            # 将合并行添加到结果中（此时是 max_rows + 1 行）
            folded_rows = pd.concat(
                [folded_rows, pd.DataFrame([fold_row])], ignore_index=True
            )
    else:
        folded_rows = df

    # 处理列折叠：保留前 max_cols 列，合并剩余列为 ">= X"
    if cols > max_cols:
        # 保留前 max_cols 列
        folded_cols = folded_rows.iloc[:, :max_cols].copy()

        # 合并剩余列为一列
        remaining_cols = folded_rows.iloc[:, max_cols:]
        if not remaining_cols.empty:
            # 获取被合并的第一列的列名（用于生成 >= X 标签）
            first_folded_col = remaining_cols.columns[0]
            fold_col_name = f">= {first_folded_col}"

            # 对每一行，合并剩余列的数值
            fold_col_data = []
            for idx in range(len(folded_rows)):
                row_data = remaining_cols.iloc[idx]

                # 尝试对数值求和（Series需要用pd.to_numeric转换）
                numeric_vals = pd.to_numeric(row_data, errors="coerce")
                if not numeric_vals.isna().all():
                    # 如果有数值，求和（忽略NaN）
                    fold_col_data.append(numeric_vals.sum())
                else:
                    # 如果没有数值，使用占位符
                    fold_col_data.append("...")

            # 将合并列添加到结果中
            folded_cols[fold_col_name] = fold_col_data
    else:
        folded_cols = folded_rows

    return folded_cols


def compact_dataframe(
    df: pd.DataFrame,
    group_col: str,
    value_cols: list[str],
    keep_rows: int = 15,
    sort_by_range: bool = True,
) -> pd.DataFrame:
    """
    通用表格压缩工具：保留前 N 行，剩余行合并为 "≥X"

    Args:
        df: 输入 DataFrame
        group_col: 分组列名 (如 'area_range', 'price_range')
        value_cols: 需要求和的数值列名 (如 ['supply_count', 'trade_count'])
        keep_rows: 保留行数
        sort_by_range: 是否尝试解析区间数值进行排序 (针对 "80-100m²" 这种格式)
    """
    if len(df) <= keep_rows:
        return df.copy()

    df = df.copy()

    # 1. 辅助排序：提取区间下限
    if sort_by_range:

        def get_lower_bound(val):
            # 提取字符串中的第一个数字
            nums = re.findall(r"\d+", str(val))
            return int(nums[0]) if nums else 999999

        df["_temp_sort"] = df[group_col].apply(get_lower_bound)
        df = df.sort_values("_temp_sort").reset_index(drop=True)
        df = df.drop(columns=["_temp_sort"])

    # 2. 切分数据
    keep_part = df.iloc[:keep_rows].copy()
    merge_part = df.iloc[keep_rows:].copy()

    if merge_part.empty:
        return keep_part

    # 3. 生成合并行
    # 获取被合并部分的最小下限值
    lower_match = re.findall(r"\d+", str(merge_part[group_col].iloc[0]))
    min_val = lower_match[0] if lower_match else "其他"

    # 根据列名猜测单位 (这是一个临时的 heuristic，你可以改为参数传入)
    # TODO 这里需要修改为更通用的方式
    unit = "m²" if "area" in group_col.lower() or "面积" in group_col else ""
    unit = "M" if "price" in group_col.lower() or "价格" in group_col else unit

    merged_label = f"≥{min_val}{unit}"

    merged_row = {group_col: merged_label}
    for col in value_cols:
        if col in df.columns:
            merged_row[col] = merge_part[col].sum()

    # 4. 拼装
    result = pd.concat([keep_part, pd.DataFrame([merged_row])], ignore_index=True)
    return result
