# core/context_builder.py

"""
Context Builder
根据模板元数据自动构建 PresentationContext
"""
from typing import Any

import pandas as pd
from loguru import logger

from .data_provider import RealEstateDataProvider
from .resources import TemplateMeta


class PresentationContext:
    """
    数据上下文容器
    用于在生成过程中传递真实的 DataFrame 和 文本变量
    只负责存入数据，不负责处理数据
    """

    def __init__(self):
        # 存放所有的 DataFrame，Key 需要与 TemplateMeta.data_mapping 对应
        self._datasets: dict[str, pd.DataFrame] = {}

        # 存放所有的文本变量 (如城市名、日期、趋势结论等)
        self._variables: dict[str, Any] = {}

    def add_dataset(self, key: str, df: pd.DataFrame):
        """注入表格数据，key 要和 catalog 里定义的一致"""
        self._datasets[key] = df
        logger.debug(f"Context: Added dataset '{key}' shape={df.shape}")

    def add_variable(self, key: str, value: Any):
        """注入文本变量，如 city='北京'"""
        self._variables[key] = value
        logger.debug(f"Context: Added variable '{key}'={value}")

    def get_dataset(self, key: str) -> pd.DataFrame:
        if key not in self._datasets:
            raise ValueError(f"数据缺失: Context 中找不到 key='{key}' 的数据表")
        return self._datasets[key]

    @property
    def variables(self) -> dict[str, Any]:
        return self._variables


class ContextBuilder:
    """
    上下文构建器
    根据 TemplateMeta 中的 function_key 和 data_keys 自动调用对应的数据方法
    支持单个或多个 function_key（多数据源）
    """

    # 定义每个 function_key 的默认参数
    DEFAULT_PARAMS = {
        "Supply-Transaction Unit Statistic": {"area_range_size": 20},
        "Area x Price Cross Pivot": {"area_step": 20, "price_step": 5},
        "Area Segment Distribution": {"step": 20},
        "Price Segment Distribution": {"price_range_size": 1},
    }

    @staticmethod
    def build_context(
        template_meta: TemplateMeta,
        provider: RealEstateDataProvider,
        city: str,
        block: str,
        start_year: str,
        end_year: str,
        **function_params,
    ) -> PresentationContext:
        """
        根据模板元数据构建上下文

        Args:
            template_meta: 模板元数据
            provider: 数据提供者实例
            city: 城市名
            block: 板块名
            start_year: 起始年份
            end_year: 结束年份
            **function_params: 传递给数据函数的额外参数（会覆盖默认参数）

        Returns:
            PresentationContext: 构建好的上下文
        """
        context = PresentationContext()

        # 1. 添加基础变量
        context.add_variable("Geo_City_Name", city)
        context.add_variable("Geo_Block_Name", block)
        context.add_variable("Temporal_Start_Year", start_year)
        context.add_variable("Temporal_End_Year", end_year)

        # 2. 获取所有的 function_keys
        function_keys = template_meta.function_keys

        # 3. 判断是单数据源还是多数据源
        if len(function_keys) == 1:
            # 单数据源模式
            function_key = function_keys[0]
            logger.info(f"单数据源模式: function_key='{function_key}'")
            ContextBuilder._build_single_datasource(
                context, template_meta, provider, function_key, **function_params
            )
        else:
            # 多数据源模式
            logger.info(f"多数据源模式: function_keys={function_keys}")
            ContextBuilder._build_multiple_datasources(
                context, template_meta, provider, function_keys, **function_params
            )

        logger.success(
            f"Context 构建完成: template={template_meta.uid}, "
            f"datasets={list(context._datasets.keys())}, "
            f"variables={len(context._variables)} 个"
        )

        return context

    @staticmethod
    def _build_single_datasource(
        context: PresentationContext,
        template_meta: TemplateMeta,
        provider: RealEstateDataProvider,
        function_key: str,
        **function_params,
    ):
        """单数据源模式构建"""
        # 获取默认参数并合并用户提供的参数
        params = ContextBuilder.DEFAULT_PARAMS.get(function_key, {}).copy()
        params.update(function_params)

        # 调用数据方法
        logger.info(f"调用数据方法: function_key='{function_key}', params={params}")
        df, conclusion_vars = provider.execute_by_function_key(function_key, **params)

        # 根据模板的 data_keys 将数据添加到 context
        # 注意：单数据源模式下，data_keys 的所有 values 都指向同一个数据集
        for data_key_name in template_meta.data_keys.values():
            context.add_dataset(data_key_name, df)

        # 添加结论变量
        for key, value in conclusion_vars.items():
            context.add_variable(key, value)

    @staticmethod
    def _build_multiple_datasources(
        context: PresentationContext,
        template_meta: TemplateMeta,
        provider: RealEstateDataProvider,
        function_keys: list[str],
        **function_params,
    ):
        """多数据源模式构建"""
        # 获取 data_keys 的所有槽位名（按顺序）
        slot_names = list(template_meta.data_keys.keys())

        # 验证数量一致
        if len(function_keys) != len(slot_names):
            raise ValueError(
                f"function_keys 数量 ({len(function_keys)}) 与 data_keys 槽位数量 ({len(slot_names)}) 不匹配"
            )

        # 按顺序遍历：第一个 function_key 对应第一个槽位（左图），第二个对应第二个（右图）
        for i, function_key in enumerate(function_keys):
            slot_name = slot_names[i]
            data_key_name = template_meta.data_keys[slot_name]

            # 获取默认参数并合并用户提供的参数
            params = ContextBuilder.DEFAULT_PARAMS.get(function_key, {}).copy()
            params.update(function_params)

            # 调用数据方法
            logger.info(
                f"调用数据方法 [{i+1}/{len(function_keys)}]: "
                f"function_key='{function_key}' -> slot='{slot_name}' (key='{data_key_name}'), "
                f"params={params}"
            )
            df, conclusion_vars = provider.execute_by_function_key(
                function_key, **params
            )

            # 添加数据集
            context.add_dataset(data_key_name, df)
            logger.info(
                f"  -> 数据已添加: slot='{slot_name}', key='{data_key_name}', shape={df.shape}"
            )

            # 只使用第一个 function_key 的结论（左图）
            if i == 0:
                for key, value in conclusion_vars.items():
                    context.add_variable(key, value)
                logger.info(
                    f"  -> 结论变量已添加: {len(conclusion_vars)} 个（来自左图/上图）"
                )
            else:
                logger.info("  -> 跳过结论变量（非左图/上图）")
