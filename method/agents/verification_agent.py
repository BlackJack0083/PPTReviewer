from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from core.dao import RealEstateDAO
from core.schemas import QueryFilter, TableAnalysisConfig
from core.transformers import StatTransformer

from .types import DetectedIssue, merge_fields

PRESENTATION_LABEL_RE = re.compile(r"\((bar chart|line chart|pie chart|table)\)\s*$", re.I)
ROUNDING_ABS_TOLERANCE = 0.5


class VerificationAgent:
    """Verify extracted slide state against the underlying database.

    Verification does not infer a new state. It treats `analysis_state` as the
    slide's stated data source and calculation logic, recomputes the table from
    the real database, then compares that result with the CSV exported from PPT.
    """

    def __init__(
        self,
        *,
        dao: RealEstateDAO | None = None,
        transformer: StatTransformer | None = None,
    ) -> None:
        self.dao = dao or RealEstateDAO()
        self.transformer = transformer or StatTransformer()

    def run(
        self,
        *,
        ppt_representation: dict[str, Any],
        analysis_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Run deterministic verification over one parsed slide.

        Args:
            ppt_representation: Parser output containing visible title, summary,
                captions, and exported table/chart CSV paths.
            analysis_state: Analysis output containing `data_source` and
                `calculation_logic` for every structured table.

        Returns:
            A list of detected issue dictionaries for downstream interaction.
        """
        issues: list[DetectedIssue] = []
        parsed_tables = list(ppt_representation.get("structured_tables", []))
        analyzed_tables = list(analysis_state.get("tables", []))

        for index, parsed_table in enumerate(parsed_tables):
            issues.extend(_verify_presentation_type(parsed_table))
            if index >= len(analyzed_tables):
                continue
            issues.extend(self._verify_table_against_database(analyzed_tables[index]))

        return _dedupe_issues(issues)

    def _verify_table_against_database(self, table_state: dict[str, Any]) -> list[DetectedIssue]:
        """Compare visible CSV with DB recomputation from analysis state."""
        visible = _read_visible_table(table_state["data_path"])
        expected = self._compute_expected_table(table_state)

        if expected.empty and not visible.empty:
            return [
                DetectedIssue(
                    targets=["st.caption"],
                    error_types=["scope_error"],
                    evidence=_scope_empty_query_evidence(table_state),
                    required_fields_guess=[
                        "scope.city",
                        "scope.block",
                        "scope.start_year",
                        "scope.end_year",
                    ],
                    confidence=0.9,
                )
            ]

        if _tables_equal(visible, expected):
            return []

        if _same_shape_and_columns(visible, expected):
            return [
                DetectedIssue(
                    targets=["st.body"],
                    error_types=["value_error"],
                    evidence="Visible CSV values differ from DB recomputation using extracted data_source and calculation_logic.",
                    required_fields_guess=[],
                    confidence=0.85,
                )
            ]

        if _same_first_column_values(visible, expected):
            return [
                DetectedIssue(
                    targets=["st.body"],
                    error_types=["value_error"],
                    evidence="Visible table columns differ from DB recomputation using extracted calculation_logic.",
                    required_fields_guess=[],
                    confidence=0.85,
                )
            ]

        return [
            DetectedIssue(
                targets=["st.body"],
                error_types=["value_error"],
                evidence="Visible table structure differs from DB recomputation after data-source validation.",
                required_fields_guess=[],
                confidence=0.85,
            )
        ]

    def _compute_expected_table(self, table_state: dict[str, Any]) -> pd.DataFrame:
        data_source = table_state["data_source"]
        filters = data_source["filters"]
        query_filter = QueryFilter(
            city=filters["city"],
            block=filters["block"],
            start_date=filters["start_date"],
            end_date=filters["end_date"],
            table_name=data_source["connection"]["table"],
        )
        raw_df = self.dao.fetch_raw_data(query_filter, columns=data_source["select_columns"])
        config = TableAnalysisConfig.model_validate(table_state["calculation_logic"])
        return self.transformer.process_data_pipeline(raw_df, config)


def _verify_presentation_type(parsed_table: dict[str, Any]) -> list[DetectedIssue]:
    caption_text = str((parsed_table.get("caption") or {}).get("text", ""))
    caption_label = _extract_presentation_label(caption_text)
    if not caption_label:
        return []

    body = parsed_table.get("body") or {}
    actual_type = _body_presentation_type(str(body.get("type", "")))
    if caption_label == actual_type:
        return []

    return [
        DetectedIssue(
            targets=["st.caption"],
            error_types=["claim_error"],
            evidence=f"caption says '{caption_label}' but body type is '{actual_type}'.",
            required_fields_guess=["claim.presentation_type"],
            confidence=0.9,
        )
    ]


def _extract_presentation_label(text: str) -> str | None:
    match = PRESENTATION_LABEL_RE.search(text.strip())
    if not match:
        return None
    return match.group(1).lower()


def _body_presentation_type(body_type: str) -> str:
    if body_type == "table":
        return "table"
    if body_type.startswith("chart-"):
        return f"{body_type.removeprefix('chart-')} chart"
    return body_type


def _read_visible_table(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def _tables_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    left_norm = _normalize_columns(left)
    right_norm = _normalize_columns(right)
    if list(left_norm.columns) != list(right_norm.columns):
        return False
    if left_norm.shape != right_norm.shape:
        return False
    return all(
        _series_equal(left_norm[column], right_norm[column])
        for column in left_norm.columns
    )


def _same_shape_and_columns(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    return left.shape == right.shape and list(left.columns) == list(right.columns)


def _same_first_column_values(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    if left.empty or right.empty or left.shape[0] != right.shape[0]:
        return False
    return _series_equal(left.iloc[:, 0], right.iloc[:, 0])


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    return normalized.reset_index(drop=True)


def _series_equal(left: pd.Series, right: pd.Series) -> bool:
    left_numeric = pd.to_numeric(left, errors="coerce")
    right_numeric = pd.to_numeric(right, errors="coerce")
    if left_numeric.notna().all() and right_numeric.notna().all():
        delta = (left_numeric - right_numeric).abs()
        return bool((delta <= ROUNDING_ABS_TOLERANCE).all())

    left_text = left.astype(str).str.strip().reset_index(drop=True)
    right_text = right.astype(str).str.strip().reset_index(drop=True)
    return bool(left_text.equals(right_text))


def _scope_empty_query_evidence(table_state: dict[str, Any]) -> str:
    data_source = table_state["data_source"]
    filters = data_source["filters"]
    return (
        "Extracted data_source returned no DB rows while the visible PPT table is non-empty: "
        f"table={data_source['connection']['table']}, city={filters['city']}, "
        f"block={filters['block']}, start_date={filters['start_date']}, "
        f"end_date={filters['end_date']}."
    )


def _dedupe_issues(issues: list[DetectedIssue]) -> list[dict[str, Any]]:
    deduped: dict[tuple[tuple[str, ...], tuple[str, ...]], DetectedIssue] = {}
    for issue in issues:
        key = (tuple(issue.targets), tuple(issue.error_types))
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = issue
            continue
        existing.required_fields_guess = merge_fields(
            existing.required_fields_guess,
            issue.required_fields_guess,
        )
        if issue.evidence not in existing.evidence:
            existing.evidence = f"{existing.evidence} | {issue.evidence}"
        if issue.confidence is not None and (
            existing.confidence is None or issue.confidence > existing.confidence
        ):
            existing.confidence = issue.confidence
    return [issue.to_dict() for issue in deduped.values()]
