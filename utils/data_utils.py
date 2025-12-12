import re

import pandas as pd


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
