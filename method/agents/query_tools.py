from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


YEAR_RE = re.compile(r"\b(20\d{2})\b")
CITY_RE = re.compile(r"\b(Beijing|Guangzhou|Shenzhen)\b", re.I)


@dataclass
class SlideQueryIntent:
    """Structured query intent inferred from visible slide context."""

    element_id: str
    connection: dict[str, Any]
    select_columns: list[str]
    filters: dict[str, Any]
    source: str = "visible_slide"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MetricLogic:
    name: str
    metric_kind: str
    source_columns: list[str]
    agg_func: str
    support_values: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisLogic:
    """SlideAgent-style function logic without binding to the old LangGraph stack."""

    element_id: str
    table_type: str
    dimensions: list[str]
    metrics: list[MetricLogic]
    fun_tool: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metrics"] = [metric.to_dict() for metric in self.metrics]
        return payload


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped


def _extract_year_range(*texts: str, fallback: list[int] | tuple[int, int] | None = None) -> dict[str, int]:
    years: list[int] = []
    for text in texts:
        years.extend(int(match.group(1)) for match in YEAR_RE.finditer(text or ""))
    if not years and fallback:
        years.extend(int(year) for year in fallback)
    if not years:
        return {}
    return {"start_year": min(years), "end_year": max(years)}


def _extract_city(text: str) -> str | None:
    match = CITY_RE.search(text or "")
    return match.group(1).title() if match else None


def _infer_table(city: str | None, text: str) -> str | None:
    if not city:
        return None
    suffix = "resale_house" if "resale" in text.lower() else "new_house"
    return f"{city.lower()}_{suffix}"


def _metric_source(metric_kind: str) -> tuple[list[str], str]:
    if metric_kind == "price":
        return ["dim_unit_price"], "mean"
    if metric_kind == "transaction":
        return ["trade_sets"], "sum"
    if metric_kind == "supply":
        return ["supply_sets"], "sum"
    if metric_kind == "area":
        return ["dim_area"], "sum"
    return [], "count"


def _dimension_from_granularity(granularity: str) -> str | None:
    if granularity == "month":
        return "month"
    if granularity == "year":
        return "year"
    if granularity == "area_segment":
        return "area_range"
    return None


def _payloads(body_data: dict[str, Any]) -> list[dict[str, Any]]:
    return list(body_data.get("series", [])) + list(body_data.get("rows", []))


class SlideAgentInspiredToolPlanner:
    """Infer query and aggregation tool specs from real visible PPTX payloads.

    This mirrors the useful part of baseline/SlideAgent: caption/table/chart context
    is converted into a query intent plus a deterministic function-logic spec. The
    current project keeps it side-effect free so verification can inspect the plan
    even when a database is not configured.
    """

    def build_for_units(
        self,
        body_units: list[dict[str, Any]],
        summary_text: str = "",
    ) -> dict[str, list[dict[str, Any]]]:
        query_intents: list[dict[str, Any]] = []
        analysis_logic: list[dict[str, Any]] = []
        aggregation_profiles: list[dict[str, Any]] = []

        for unit in body_units:
            body_element = unit.get("body_element", {})
            body_data = unit.get("body_data", {})
            caption = unit.get("paired_caption")
            caption_text = str(caption.get("text", "")).strip() if caption else ""
            element_id = str(body_element.get("id"))
            context_text = "\n".join(text for text in [caption_text, summary_text] if text)

            query_intents.append(
                self.infer_query_intent(
                    element_id=element_id,
                    context_text=context_text,
                    body_data=body_data,
                ).to_dict()
            )
            logic = self.infer_analysis_logic(
                element_id=element_id,
                body_data=body_data,
            )
            analysis_logic.append(logic.to_dict())
            aggregation_profiles.append(
                VisibleAggregationTool().profile(
                    element_id=element_id,
                    body_data=body_data,
                    analysis_logic=logic,
                )
            )

        return {
            "query_intents": query_intents,
            "analysis_logic": analysis_logic,
            "aggregation_profiles": aggregation_profiles,
        }

    def infer_query_intent(
        self,
        *,
        element_id: str,
        context_text: str,
        body_data: dict[str, Any],
    ) -> SlideQueryIntent:
        city = _extract_city(context_text)
        table = _infer_table(city, context_text)
        columns = self._select_columns(body_data)
        filters: dict[str, Any] = {}
        if city:
            filters["city"] = city
        filters.update(_extract_year_range(context_text, fallback=body_data.get("time_range")))

        return SlideQueryIntent(
            element_id=element_id,
            connection={"table": [table] if table else []},
            select_columns=columns,
            filters=filters,
        )

    def infer_analysis_logic(self, *, element_id: str, body_data: dict[str, Any]) -> AnalysisLogic:
        granularity = str(body_data.get("category_granularity") or "")
        dimension = _dimension_from_granularity(granularity)
        dimensions = [dimension] if dimension else []
        metrics: list[MetricLogic] = []
        table_col_names: list[str] = []
        database_col_names: list[str | list[str]] = []
        agg_funs: list[str] = []

        for payload in _payloads(body_data):
            metric_kind = str(payload.get("metric_kind") or "unknown")
            source_columns, agg_func = _metric_source(metric_kind)
            metric_name = str(payload.get("name") or metric_kind)
            metrics.append(
                MetricLogic(
                    name=metric_name,
                    metric_kind=metric_kind,
                    source_columns=source_columns,
                    agg_func=agg_func,
                    support_values=list(payload.get("support_values", [])),
                )
            )
            table_col_names.append(metric_name)
            database_col_names.append(source_columns if len(source_columns) > 1 else (source_columns[0] if source_columns else ""))
            agg_funs.append(agg_func)

        table_type = "constraint-field" if body_data.get("body_kind") == "table" else "field-constraint"
        header_info: Any
        if table_type == "constraint-field":
            header_info = [table_col_names, dimensions]
        else:
            header_info = [[dimension or "category", table_col_names]]

        return AnalysisLogic(
            element_id=element_id,
            table_type=table_type,
            dimensions=dimensions,
            metrics=metrics,
            fun_tool={
                "quadruples": [
                    table_type,
                    header_info,
                    database_col_names,
                    agg_funs,
                ],
                "args": {
                    "area_range_size": 20,
                    "price_range_size": 1,
                },
            },
        )

    def _select_columns(self, body_data: dict[str, Any]) -> list[str]:
        columns: list[str] = []
        granularity = body_data.get("category_granularity")
        if granularity in {"year", "month"}:
            columns.append("date_code")
        if granularity == "area_segment":
            columns.append("dim_area")

        for payload in _payloads(body_data):
            source_columns, _ = _metric_source(str(payload.get("metric_kind") or "unknown"))
            columns.extend(source_columns)
        return _dedupe(columns)


class VisibleAggregationTool:
    """Deterministic profile tool over visible PPTX data.

    It does not replace database aggregation. It gives the verifier an executable
    profile of what the slide visibly contains, so checks can be anchored to real
    chart/table values while DB access remains optional.
    """

    def profile(
        self,
        *,
        element_id: str,
        body_data: dict[str, Any],
        analysis_logic: AnalysisLogic,
    ) -> dict[str, Any]:
        return {
            "element_id": element_id,
            "source": "visible_pptx",
            "category_granularity": body_data.get("category_granularity"),
            "time_range": body_data.get("time_range"),
            "dimensions": list(analysis_logic.dimensions),
            "metrics": [
                {
                    "name": metric.name,
                    "metric_kind": metric.metric_kind,
                    "agg_func": metric.agg_func,
                    "source_columns": list(metric.source_columns),
                    "trend_direction": payload.get("trend_direction"),
                    "max_value": payload.get("max_value"),
                }
                for metric, payload in zip(analysis_logic.metrics, _payloads(body_data))
            ],
            "support_values": list(body_data.get("support_values", [])),
        }


class DatabaseAggregationTool:
    """Optional DB-backed execution hook for future full repair.

    The benchmark agent should not fabricate DB results. This tool only builds a
    transparent SQL skeleton from `SlideQueryIntent`; callers must inject a real
    database executor before running it.
    """

    def build_sql(self, intent: SlideQueryIntent) -> tuple[str, dict[str, Any]]:
        table = intent.connection.get("table", [None])[0]
        if not table:
            raise ValueError("Cannot build SQL without a concrete table name.")
        columns = intent.select_columns or ["*"]
        where_clauses = []
        params: dict[str, Any] = {}
        if "start_year" in intent.filters:
            where_clauses.append("EXTRACT(YEAR FROM date_code) >= :start_year")
            params["start_year"] = intent.filters["start_year"]
        if "end_year" in intent.filters:
            where_clauses.append("EXTRACT(YEAR FROM date_code) <= :end_year")
            params["end_year"] = intent.filters["end_year"]
        where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        return f"SELECT {', '.join(columns)} FROM {table}{where_sql}", params
