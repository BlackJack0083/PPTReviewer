from typing import Any

import numpy as np
import pandas as pd


class DataProvider:
    """数据提供者：负责解析 YAML 中的 args 并获取/生成 DataFrame"""

    @staticmethod
    def get_data(role: str, args: list[Any] = None) -> pd.DataFrame:
        """
        根据 role 和 args 路由到具体的数据生成函数。
        实际项目中，这里会连接数据库或 API。
        """
        role = str(role) if role is not None else ""
        args = args or []

        # 简单的 args 签名识别 (基于您提供的 yaml 结构)
        # args 结构示例: [['field-constraint'], [['Area Rng Stats', ...]], ...]

        data_tag = ""
        try:
            if args and len(args) > 1 and len(args[1]) > 0 and len(args[1][0]) > 0:
                data_tag = str(
                    args[1][0][0]
                )  # e.g., "Area Rng Stats" or "Price Rng Stats"
        except (IndexError, TypeError):
            data_tag = ""

        # 优先根据data_tag匹配
        if "Area" in data_tag:
            return DataProvider._mock_area_range_data()
        elif "Price" in data_tag:
            return DataProvider._mock_price_range_data()

        # 根据role匹配
        if "table" in role.lower():
            return DataProvider._mock_table_data()
        elif "bar" in role.lower():
            return DataProvider._mock_default_bar_data()
        elif "line" in role.lower():
            return DataProvider._mock_default_line_data()
        else:
            return DataProvider._mock_default_data()

    @staticmethod
    def _mock_area_distribution_data() -> pd.DataFrame:
        """
        模拟单栏柱状图数据 (如: 面积段供销分析)
        Args hint: [['supply_counts', 'trade_counts'], ['area_range', ...], ...]
        """
        # 构造 X 轴：面积段
        categories = [f"{i}-{i+10}m²" for i in range(60, 160, 10)]
        categories.append(">160m²")

        # 构造 Series：供应套数 & 成交套数
        # 模拟数据：呈现正态分布或特定趋势
        supply = [np.random.randint(20, 100) for _ in range(len(categories))]
        trade = [int(s * np.random.uniform(0.6, 0.95)) for s in supply]

        # 构建 DataFrame
        # Index = Legend (Series Names)
        # Columns = X-Axis (Categories)
        df = pd.DataFrame(
            [supply, trade],
            index=["供应套数(Supply)", "成交套数(Trade)"],
            columns=categories,
        )
        return df

    @staticmethod
    def _mock_price_trend_data(args: list) -> pd.DataFrame:
        """模拟折线图数据"""
        months = ["2023-01", "2023-02", "2023-03", "2023-04", "2023-05", "2023-06"]
        price = [45000, 45200, 45800, 46000, 45500, 45900]
        df = pd.DataFrame([price], index=["成交均价"], columns=months)
        return df

    @staticmethod
    def _mock_default_bar_data() -> pd.DataFrame:
        return pd.DataFrame(
            [[50, 80, 40], [45, 75, 35]],
            index=["Supply", "Trade"],
            columns=["Cat A", "Cat B", "Cat C"],
        )

    @staticmethod
    def _mock_default_line_data() -> pd.DataFrame:
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
        values = [25000 + x * 500 + np.random.randint(-200, 200) for x in range(6)]
        return pd.DataFrame([values], index=["Price Trend"], columns=months)

    @staticmethod
    def _mock_default_data() -> pd.DataFrame:
        return pd.DataFrame({"Data": [10, 20, 30]}, index=["Series1"])

    @staticmethod
    def _mock_area_range_data() -> pd.DataFrame:
        """模拟面积段分布数据 (双栏示例1)"""
        # X轴: 面积段
        categories = ["0-80m²", "80-100m²", "100-120m²", "120-140m²", "140m²+"]
        # 数据: 计数
        counts = [1200, 3931, 2500, 800, 400]  # 80-100m² 是 mainstream

        df = pd.DataFrame([counts], index=["成交套数"], columns=categories)
        return df

    @staticmethod
    def _mock_price_range_data() -> pd.DataFrame:
        """模拟价格段分布数据 (双栏示例2)"""
        # X轴: 价格段 (M = Million)
        categories = ["0-2M", "2-3M", "3-5M", "5-8M", "8M+"]
        counts = [500, 1500, 4200, 1800, 600]

        df = pd.DataFrame([counts], index=["成交套数"], columns=categories)
        return df

    @staticmethod
    def _mock_table_data() -> pd.DataFrame:
        """模拟表格数据 (单栏表格示例)"""
        # 模拟房地产项目详细数据表
        data = {
            "项目名称": ["万科城市花园", "恒大绿洲", "碧桂园凤凰城", "保利香槟国际"],
            "区域": ["朝阳区", "海淀区", "丰台区", "西城区"],
            "均价(元/㎡)": ["45,000", "52,000", "38,000", "68,000"],
            "主力户型": ["89-120㎡", "95-140㎡", "78-110㎡", "120-180㎡"],
            "交房时间": ["2024-06", "2024-12", "2025-03", "2024-09"],
            "绿化率": ["35%", "40%", "30%", "45%"],
        }

        df = pd.DataFrame(data)
        return df
