from typing import Any

import pandas as pd


class PresentationContext:
    """
    数据上下文容器
    用于在生成过程中传递真实的 DataFrame 和 文本变量
    """

    def __init__(self):
        # 存放所有的 DataFrame，Key 需要与 TemplateMeta.data_mapping 对应
        self._datasets: dict[str, pd.DataFrame] = {}

        # 存放所有的文本变量 (如城市名、日期、趋势结论等)
        self._variables: dict[str, Any] = {}

    def add_dataset(self, key: str, df: pd.DataFrame):
        """注入表格数据，key 要和 catalog 里定义的一致"""
        self._datasets[key] = df

    def add_variable(self, key: str, value: Any):
        """注入文本变量，如 city='北京'"""
        self._variables[key] = value

    def get_dataset(self, key: str) -> pd.DataFrame:
        if key not in self._datasets:
            raise ValueError(f"数据缺失: Context 中找不到 key='{key}' 的数据表")
        return self._datasets[key]

    @property
    def variables(self) -> dict[str, Any]:
        return self._variables
