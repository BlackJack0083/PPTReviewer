from __future__ import annotations

import re
from typing import Any

from .types import DetectedIssue, merge_fields

YEAR_RE = re.compile(r"\b(20\d{2})\b")
NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")
PRESENTATION_LABEL_RE = re.compile(r"\((bar chart|line chart|pie chart|table)\)\s*$", re.I)
TREND_RE = re.compile(r"\b(increase|increased|growth|upward|decrease|decreased|decline|downward)\b", re.I)
STOPWORDS = {
    "from",
    "to",
    "with",
    "the",
    "and",
    "for",
    "chart",
    "table",
    "analysis",
    "trend",
    "market",
    "monthly",
    "annual",
    "resale",
    "house",
    "transactions",
    "transaction",
    "supply",
    "price",
    "avg",
    "volume",
    "distribution",
}


def parse_number(text: str) -> float | None:
    match = NUMBER_RE.search(str(text))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "").replace("%", ""))
    except ValueError:
        return None


def extract_year_range(text: str) -> tuple[int, int] | None:
    years = [int(match.group(1)) for match in YEAR_RE.finditer(text)]
    if not years:
        return None
    return min(years), max(years)


def extract_presentation_label(text: str) -> str | None:
    match = PRESENTATION_LABEL_RE.search(text.strip())
    if not match:
        return None
    return match.group(1).lower()
def summary_metric_mentions(text: str) -> set[str]:
    lower = text.lower()
    metric_kinds = set()
    if any(keyword in lower for keyword in {"trade", "sales", "transaction"}):
        metric_kinds.add("transaction")
    if "supply" in lower:
        metric_kinds.add("supply")
    if "price" in lower:
        metric_kinds.add("price")
    if "area" in lower:
        metric_kinds.add("area")
    return metric_kinds


def summary_trend_direction(text: str) -> str | None:
    match = TREND_RE.search(text)
    if not match:
        return None
    word = match.group(1).lower()
    if word in {"increase", "increased", "growth", "upward"}:
        return "increase"
    return "decrease"


def extract_location_phrase(text: str) -> str | None:
    cleaned = re.sub(r"\([^)]*\)", " ", text)
    cleaned = YEAR_RE.sub(" ", cleaned)
    tokens = re.findall(r"[A-Za-z][A-Za-z&.-]+", cleaned)
    kept = []
    for token in tokens:
        if not token[:1].isupper():
            if kept:
                break
            continue
        if token.lower() in STOPWORDS:
            if kept:
                break
            continue
        kept.append(token)
    if not kept:
        return None
    return " ".join(kept)


def approximately_matches(number: float, support_values: list[float]) -> bool:
    for support in support_values:
        tolerance = max(2.0, abs(support) * 0.015)
        if abs(number - support) <= tolerance:
            return True
    return False


def metric_value_profile_mismatch(metric_kind: str, values: list[float]) -> bool:
    if not values:
        return False
    max_value = max(values)
    if metric_kind == "price":
        return max_value < 1000
    if metric_kind == "transaction":
        return max_value > 5000
    return False


class VerificationAgent:
    """ST-first verifier using visible chart/table data and text consistency checks."""

    def run(
        self,
        observed_slide: dict[str, Any],
        structured_understanding: dict[str, Any],
    ) -> list[dict[str, Any]]:
        del observed_slide
        issues: list[DetectedIssue] = []

        summary_elements = structured_understanding["targets"]["summary"]
        summary_text = "\n".join(
            str(element.get("text", "")).strip() for element in summary_elements if str(element.get("text", "")).strip()
        )
        summary_year_range = extract_year_range(summary_text) if summary_text else None
        summary_location = extract_location_phrase(summary_text) if summary_text else None
        summary_numbers = [
            parse_number(match.group(0))
            for match in NUMBER_RE.finditer(summary_text)
            if parse_number(match.group(0)) is not None and not YEAR_RE.fullmatch(match.group(0))
        ]
        summary_metric_kinds = summary_metric_mentions(summary_text)
        summary_trend = summary_trend_direction(summary_text) if summary_text else None

        body_support_values: list[float] = []
        body_metric_kinds: set[str] = set()
        body_granularities: set[str] = set()
        body_trends: set[str] = set()
        analysis_logic_by_element = {
            str(item.get("element_id")): item
            for item in structured_understanding.get("analysis_logic", [])
        }

        for unit in structured_understanding["body_units"]:
            body_element = unit["body_element"]
            body_data = unit["body_data"]
            caption = unit["paired_caption"]
            caption_text = str(caption.get("text", "")).strip() if caption else ""
            caption_scope_emitted = False
            element_id = str(body_element.get("id"))
            metric_logic_by_name = {
                str(metric.get("name")): metric
                for metric in analysis_logic_by_element.get(element_id, {}).get("metrics", [])
            }

            body_support_values.extend(body_data.get("support_values", []))
            body_metric_kinds.update(body_data.get("metric_kinds", []))
            if body_data.get("category_granularity"):
                body_granularities.add(body_data["category_granularity"])

            for payload in body_data.get("series", []) + body_data.get("rows", []):
                if payload.get("trend_direction") in {"increase", "decrease"}:
                    body_trends.add(payload["trend_direction"])
                if metric_value_profile_mismatch(
                    str(payload.get("metric_kind", "")),
                    list(payload.get("values", [])),
                ):
                    metric_logic = metric_logic_by_name.get(str(payload.get("name"))) or {}
                    source_columns = metric_logic.get("source_columns", [])
                    agg_func = metric_logic.get("agg_func")
                    logic_hint = (
                        f" planned as {agg_func} over {source_columns}"
                        if source_columns and agg_func
                        else ""
                    )
                    issues.append(
                        DetectedIssue(
                            targets=["st.header"],
                            error_types=["logic_error"],
                            evidence=(
                                f"metric label '{payload.get('name')}' is inconsistent with "
                                f"its visible value profile{logic_hint}."
                            ),
                            required_fields_guess=["logic.metrics", "logic.aggregation"],
                            confidence=0.75,
                        )
                    )

            caption_label = extract_presentation_label(caption_text) if caption_text else None
            actual_presentation = str(body_data.get("presentation_type", "")).lower()
            if caption_label and actual_presentation and caption_label != actual_presentation:
                issues.append(
                    DetectedIssue(
                        targets=["st.caption"],
                        error_types=["claim_error"],
                        evidence=(
                            f"caption says '{caption_label}' but visible ST body is "
                            f"'{actual_presentation}'."
                        ),
                        required_fields_guess=["claim.presentation_type"],
                        confidence=0.95,
                    )
                )

            caption_year_range = extract_year_range(caption_text) if caption_text else None
            body_year_range = body_data.get("time_range")
            if caption_year_range and body_year_range:
                if tuple(body_year_range) != caption_year_range:
                    caption_scope_emitted = True
                    issues.append(
                        DetectedIssue(
                            targets=["st.caption"],
                            error_types=["scope_error"],
                            evidence=(
                                f"caption year range {caption_year_range} disagrees with "
                                f"visible ST range {tuple(body_year_range)}."
                            ),
                            required_fields_guess=["scope.start_year", "scope.end_year"],
                            confidence=0.9,
                        )
                    )

            caption_location = extract_location_phrase(caption_text) if caption_text else None
            if caption_location and summary_location and caption_location != summary_location:
                caption_scope_emitted = True
                issues.append(
                    DetectedIssue(
                        targets=["st.caption"],
                        error_types=["scope_error"],
                        evidence=(
                            f"caption location '{caption_location}' disagrees with summary "
                            f"location '{summary_location}'."
                        ),
                        required_fields_guess=["scope.city", "scope.block"],
                        confidence=0.7,
                    )
                )

            if caption_text and not caption_scope_emitted:
                scope_fields = []
                if caption_location:
                    scope_fields.extend(["scope.city", "scope.block"])
                if caption_year_range:
                    scope_fields.extend(["scope.start_year", "scope.end_year"])
                if scope_fields:
                    issues.append(
                        DetectedIssue(
                            targets=["st.caption"],
                            error_types=["scope_error"],
                            evidence=(
                                "caption exposes explicit scope cues and should be verified "
                                "against visible ST context."
                            ),
                            required_fields_guess=scope_fields,
                            confidence=0.45,
                        )
                    )

            if summary_text and summary_metric_kinds:
                payloads = body_data.get("series", []) + body_data.get("rows", [])
                for mentioned_kind in summary_metric_kinds:
                    mentioned_payloads = [
                        payload
                        for payload in payloads
                        if payload.get("metric_kind") == mentioned_kind
                    ]
                    other_payloads = [
                        payload
                        for payload in payloads
                        if payload.get("metric_kind") != mentioned_kind
                    ]
                    for number in summary_numbers:
                        mentioned_match = any(
                            approximately_matches(number, list(payload.get("support_values", [])))
                            for payload in mentioned_payloads
                        )
                        other_match = any(
                            approximately_matches(number, list(payload.get("support_values", [])))
                            for payload in other_payloads
                        )
                        if other_match and not mentioned_match:
                            issues.append(
                                DetectedIssue(
                                    targets=["st.header"],
                                    error_types=["logic_error"],
                                    evidence=(
                                        f"summary ties value {number:g} to '{mentioned_kind}', "
                                        "but the visible ST value matches a different metric series."
                                    ),
                                    required_fields_guess=["logic.metrics"],
                                    confidence=0.8,
                                )
                            )
                            break

        if summary_year_range and body_support_values:
            body_year_ranges = [
                tuple(unit["body_data"]["time_range"])
                for unit in structured_understanding["body_units"]
                if unit["body_data"].get("time_range")
            ]
            if body_year_ranges:
                global_body_range = (
                    min(start for start, _ in body_year_ranges),
                    max(end for _, end in body_year_ranges),
                )
                if summary_year_range != global_body_range:
                    issues.append(
                        DetectedIssue(
                            targets=["summary"],
                            error_types=["scope_error"],
                            evidence=(
                                f"summary year range {summary_year_range} disagrees with "
                                f"visible ST range {global_body_range}."
                            ),
                            required_fields_guess=["scope.start_year", "scope.end_year"],
                            confidence=0.9,
                        )
                    )

        if summary_numbers:
            unsupported_numbers = [
                number for number in summary_numbers if not approximately_matches(number, body_support_values)
            ]
            if unsupported_numbers and (
                len(unsupported_numbers) >= 2 or len(unsupported_numbers) == len(summary_numbers)
            ):
                issues.append(
                    DetectedIssue(
                        targets=["summary"],
                        error_types=["value_error"],
                        evidence=(
                            "summary contains values not supported by visible ST data: "
                            + ", ".join(f"{number:g}" for number in unsupported_numbers[:3])
                        ),
                        required_fields_guess=[],
                        confidence=0.8,
                    )
                )

        if summary_trend and body_trends:
            comparable_trends = {trend for trend in body_trends if trend != "flat"}
            if comparable_trends and summary_trend not in comparable_trends:
                issues.append(
                    DetectedIssue(
                        targets=["summary"],
                        error_types=["claim_error"],
                        evidence=(
                            f"summary trend '{summary_trend}' disagrees with visible ST trend "
                            f"{sorted(comparable_trends)}."
                        ),
                        required_fields_guess=[],
                        confidence=0.85,
                    )
                )

        title_elements = structured_understanding["targets"]["title"]
        for element in title_elements:
            title_text = str(element.get("text", "")).strip()
            title_metric_kinds = summary_metric_mentions(title_text)
            title_granularity = {
                kind
                for kind in {"month", "year", "area_segment"}
                if kind.replace("_", " ") in title_text.lower() or kind.split("_")[0] in title_text.lower()
            }
            metric_mismatch = bool(title_metric_kinds and body_metric_kinds and title_metric_kinds.isdisjoint(body_metric_kinds))
            granularity_mismatch = bool(title_granularity and body_granularities and title_granularity.isdisjoint(body_granularities))
            if metric_mismatch or granularity_mismatch:
                issues.append(
                    DetectedIssue(
                        targets=["title"],
                        error_types=["claim_error"],
                        evidence=(
                            f"title '{title_text}' is weakly aligned with visible caption/body theme."
                        ),
                        required_fields_guess=["claim.topic"],
                        confidence=0.65,
                    )
                )

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
