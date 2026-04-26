from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from loguru import logger

from utils.data_utils import compact_dataframe, preprocess_raw_data, transpose_dataframe

from .schemas import BinningRule, MetricRule, TableAnalysisConfig

RANGE_DIMENSIONS = {"area_range", "price_range"}
TABLE_TYPE_ALIASES = {
    "constraint-filed": "constraint-field",
}
SUPPORTED_TABLE_TYPES = {"field-constraint", "constraint-field", "cross-constraint"}


@dataclass(slots=True)
class _ExecutionPlan:
    """归一化后的执行计划。"""

    table_type: str
    primary_dim: str | None
    group_dims: list[str]
    crosstab_row: str | None
    crosstab_col: str | None
    metrics: list[MetricRule]


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
        """
        执行统一的数据处理流水线。

        `output_path` 仍然保留在签名中，避免影响现有调用方；
        当前实现暂不在此方法内直接导出文件。
        """
        del output_path

        df = preprocess_raw_data(raw_data)
        execution_plan = self._normalize_config(config)
        df = self._prepare_dimensions(df, config.dimensions)

        if execution_plan.table_type in {"field-constraint", "constraint-field"}:
            return self._process_standard_table(df, execution_plan)

        if execution_plan.table_type == "cross-constraint":
            return self._process_crosstab_table(df, execution_plan)

        raise ValueError(f"Unknown table type: {execution_plan.table_type}")

    def _normalize_config(self, config: TableAnalysisConfig) -> _ExecutionPlan:
        """将 schema 配置归一化为统一执行语义。"""
        table_type = TABLE_TYPE_ALIASES.get(config.table_type, config.table_type)
        if table_type not in SUPPORTED_TABLE_TYPES:
            raise ValueError(f"Unknown table type: {config.table_type}")

        primary_dim = config.dimensions[0].target_col if config.dimensions else None
        crosstab_row = config.crosstab_row
        crosstab_col = config.crosstab_col

        if table_type == "cross-constraint":
            if crosstab_row is None and len(config.dimensions) >= 1:
                crosstab_row = config.dimensions[0].target_col
            if crosstab_col is None and len(config.dimensions) >= 2:
                crosstab_col = config.dimensions[1].target_col
            primary_dim = crosstab_row
            group_dims = [dim for dim in [crosstab_row, crosstab_col] if dim]
        else:
            group_dims = [primary_dim] if primary_dim else []

        return _ExecutionPlan(
            table_type=table_type,
            primary_dim=primary_dim,
            group_dims=group_dims,
            crosstab_row=crosstab_row,
            crosstab_col=crosstab_col,
            metrics=list(config.metrics),
        )

    def _prepare_dimensions(
        self, df: pd.DataFrame, dimensions: list[BinningRule]
    ) -> pd.DataFrame:
        """按声明顺序预处理所有维度。"""
        result = df.copy()
        for rule in dimensions:
            result = self._apply_dimension_rule(result, rule)
        return result

    def _apply_dimension_rule(
        self, df: pd.DataFrame, rule: BinningRule
    ) -> pd.DataFrame:
        """执行单个维度规则。"""
        if rule.method == "range":
            return self._apply_range_binning(df, rule)
        if rule.method == "period":
            return self._apply_period_dimension(df, rule)
        raise ValueError(f"Unsupported dimension method: {rule.method}")

    def _apply_range_binning(self, df: pd.DataFrame, rule: BinningRule) -> pd.DataFrame:
        """应用区间分箱，保持 area/price range 的业务语义。"""
        if rule.source_col not in df.columns:
            raise KeyError(f"Missing source column for binning: {rule.source_col}")

        result = df.copy()
        series = pd.to_numeric(result[rule.source_col], errors="coerce")
        if series.dropna().empty:
            result[rule.target_col] = pd.Series(
                pd.NA, index=result.index, dtype="object"
            )
            return result

        step = rule.step if rule.step not in (None, 0) else 1
        step_value = self._resolve_range_step(rule.source_col, step)

        min_value = float(rule.min) if rule.min is not None else float(series.min())
        max_value = float(rule.max) if rule.max is not None else float(series.max())

        start = int(min_value // step_value) * step_value
        end = int((max_value // step_value) + 1) * step_value
        bins = list(range(start, end + step_value, step_value))
        if len(bins) < 2:
            bins = [start, start + step_value]

        labels = self._build_range_labels(rule, bins)
        result[rule.target_col] = pd.cut(
            series,
            bins=bins,
            labels=labels,
            right=False,
            include_lowest=True,
        )
        return result

    def _apply_period_dimension(
        self, df: pd.DataFrame, rule: BinningRule
    ) -> pd.DataFrame:
        """应用时间维度预处理。"""
        if rule.source_col not in df.columns:
            raise KeyError(
                f"Missing source column for period dimension: {rule.source_col}"
            )

        result = df.copy()
        datetime_series = pd.to_datetime(result[rule.source_col], errors="coerce")

        if rule.time_granularity == "year":
            result[rule.target_col] = datetime_series.dt.year
            return result

        if rule.time_granularity == "month":
            result[rule.target_col] = datetime_series.dt.to_period("M").astype(str)
            return result

        raise ValueError(
            f"Unsupported time granularity for {rule.target_col}: {rule.time_granularity}"
        )

    @staticmethod
    def _resolve_range_step(source_col: str, step: float) -> int:
        """将 schema 中的 step 转为底层实际分箱步长。"""
        if source_col == "dim_price":
            resolved = int(float(step) * 100)
        else:
            resolved = int(float(step))
        return max(resolved, 1)

    @staticmethod
    def _build_range_labels(rule: BinningRule, bins: list[int]) -> list[str]:
        """根据分箱边界构造输出标签。"""
        if rule.source_col == "dim_price":
            template = rule.format_str or "{}-{}M"
            return [
                template.format(round(bins[i] / 100, 2), round(bins[i + 1] / 100, 2))
                for i in range(len(bins) - 1)
            ]

        template = rule.format_str or "{}-{}m²"
        return [template.format(bins[i], bins[i + 1]) for i in range(len(bins) - 1)]

    def _process_standard_table(
        self, df: pd.DataFrame, execution_plan: _ExecutionPlan
    ) -> pd.DataFrame:
        """处理标准聚合表和转置聚合表。"""
        if not execution_plan.primary_dim or not execution_plan.metrics:
            logger.warning(
                "Standard table skipped because dimensions or metrics are empty."
            )
            return pd.DataFrame()

        result = self._aggregate_metrics(
            df=df,
            group_cols=[execution_plan.primary_dim],
            metrics=execution_plan.metrics,
        )
        result = self._finalize_grouped_result(result, execution_plan.primary_dim)

        if execution_plan.table_type == "constraint-field":
            result = transpose_dataframe(result, index_col=execution_plan.primary_dim)

        return result

    def _process_crosstab_table(
        self, df: pd.DataFrame, execution_plan: _ExecutionPlan
    ) -> pd.DataFrame:
        """处理交叉表，支持单指标交叉和多指标透视两种输出。"""
        if not execution_plan.crosstab_row or not execution_plan.crosstab_col:
            raise ValueError("Crosstab requires row and col dimensions")

        if not execution_plan.metrics:
            raise ValueError("Crosstab requires at least one metric")

        if len(execution_plan.metrics) == 1:
            return self._build_single_metric_crosstab(
                df=df,
                row_dim=execution_plan.crosstab_row,
                col_dim=execution_plan.crosstab_col,
                metric=execution_plan.metrics[0],
            )

        return self._build_multi_metric_pivot(
            df=df,
            row_dim=execution_plan.crosstab_row,
            col_dim=execution_plan.crosstab_col,
            metrics=execution_plan.metrics,
        )

    def _aggregate_metrics(
        self, df: pd.DataFrame, group_cols: list[str], metrics: list[MetricRule]
    ) -> pd.DataFrame:
        """按指标分别聚合并合并结果。"""
        results: list[pd.DataFrame] = []
        for metric in metrics:
            filtered_df = self._apply_metric_filter(df, metric)
            aggregated = self._aggregate_single_metric(filtered_df, group_cols, metric)
            results.append(aggregated)

        if not results:
            return pd.DataFrame(columns=group_cols)

        merged = results[0]
        for partial in results[1:]:
            merged = pd.merge(merged, partial, on=group_cols, how="outer")

        for metric in metrics:
            if metric.name in merged.columns:
                merged[metric.name] = self._normalize_metric_series(
                    merged[metric.name].fillna(0), metric.agg_func
                )

        return self._sort_result(merged, group_cols)

    def _aggregate_single_metric(
        self, df: pd.DataFrame, group_cols: list[str], metric: MetricRule
    ) -> pd.DataFrame:
        """聚合单个指标。"""
        if metric.source_col not in df.columns:
            raise KeyError(f"Missing metric source column: {metric.source_col}")

        try:
            return (
                df.groupby(group_cols, observed=False)
                .agg(**{metric.name: (metric.source_col, metric.agg_func)})
                .reset_index()
            )
        except KeyError as exc:
            logger.error(f"Aggregation failed for {metric.name}: {exc}")
            raise

    def _apply_metric_filter(
        self, df: pd.DataFrame, metric: MetricRule
    ) -> pd.DataFrame:
        """按指标过滤条件裁剪输入数据。"""
        if not metric.filter_condition:
            return df

        filtered = df.copy()
        for column, expected in metric.filter_condition.items():
            if column not in filtered.columns:
                raise KeyError(f"Missing filter column: {column}")

            if isinstance(expected, list | tuple | set):
                filtered = filtered[filtered[column].isin(list(expected))]
            else:
                filtered = filtered[filtered[column] == expected]

        return filtered

    def _build_single_metric_crosstab(
        self, df: pd.DataFrame, row_dim: str, col_dim: str, metric: MetricRule
    ) -> pd.DataFrame:
        """构建单指标交叉表，保留现有 total 行列协议。"""
        filtered = self._apply_metric_filter(df, metric)

        if metric.agg_func == "count":
            result = pd.crosstab(
                index=filtered[row_dim],
                columns=filtered[col_dim],
                margins=True,
                margins_name="total",
                dropna=False,
            )
        else:
            result = pd.crosstab(
                index=filtered[row_dim],
                columns=filtered[col_dim],
                values=filtered[metric.source_col],
                aggfunc=metric.agg_func,
                margins=True,
                margins_name="total",
                dropna=False,
            ).fillna(0)
            for column in result.columns:
                result[column] = self._normalize_metric_series(
                    result[column], metric.agg_func
                )

        result = compact_dataframe(result, max_rows=16, max_cols=18, mode="crosstab")
        result.index.name = row_dim
        return result.reset_index()

    def _build_multi_metric_pivot(
        self,
        df: pd.DataFrame,
        row_dim: str,
        col_dim: str,
        metrics: list[MetricRule],
    ) -> pd.DataFrame:
        """构建多指标交叉透视表，列名扁平化为 metric(dim)。"""
        merged = self._aggregate_metrics(df, [row_dim, col_dim], metrics)
        if merged.empty:
            return pd.DataFrame(columns=[row_dim])

        metric_names = [metric.name for metric in metrics]
        pivot = merged.pivot(index=row_dim, columns=col_dim, values=metric_names)
        pivot = pivot.fillna(0)
        pivot.columns = [
            f"{metric_name}({dim_value})" for metric_name, dim_value in pivot.columns
        ]

        for metric in metrics:
            metric_prefix = f"{metric.name}("
            target_columns = [
                col for col in pivot.columns if col.startswith(metric_prefix)
            ]
            for column in target_columns:
                pivot[column] = self._normalize_metric_series(
                    pivot[column], metric.agg_func
                )

        result = pivot.reset_index()
        if row_dim in RANGE_DIMENSIONS:
            result = compact_dataframe(result, max_rows=15, range_col=row_dim)
        return result

    def _finalize_grouped_result(
        self, df: pd.DataFrame, primary_dim: str | None
    ) -> pd.DataFrame:
        """统一整理标准聚合输出。"""
        if df.empty or not primary_dim or primary_dim not in df.columns:
            return df

        result = df.copy()
        if primary_dim in RANGE_DIMENSIONS:
            result = compact_dataframe(result, max_rows=15, range_col=primary_dim)
        return result

    @staticmethod
    def _sort_result(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
        """按分组维度稳定排序。"""
        sortable_cols = [col for col in group_cols if col in df.columns]
        if not sortable_cols or df.empty:
            return df.reset_index(drop=True)
        return df.sort_values(sortable_cols).reset_index(drop=True)

    @staticmethod
    def _normalize_metric_series(series: pd.Series, agg_func: str) -> pd.Series:
        """统一处理聚合结果的数据类型和舍入规则。"""
        numeric = pd.to_numeric(series, errors="coerce").fillna(0)
        if agg_func == "mean":
            return numeric.round(0).astype(int)
        if agg_func == "count":
            return numeric.astype(int)
        if ((numeric % 1) == 0).all():
            return numeric.astype(int)
        return numeric
