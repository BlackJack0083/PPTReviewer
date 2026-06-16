from __future__ import annotations

from typing import Any


def evaluate_detection(
    detected_issues: list[dict[str, Any]],
    corruption_record: dict[str, Any],
) -> dict[str, Any]:
    predicted = _issue_pairs(detected_issues)
    gold = _gold_detection_pairs(corruption_record)
    tp = predicted & gold
    fp = predicted - gold
    fn = gold - predicted
    precision = _safe_div(len(tp), len(predicted))
    recall = _safe_div(len(tp), len(gold))
    f1 = _safe_div(2 * precision * recall, precision + recall) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": sorted(tp),
        "fp": sorted(fp),
        "fn": sorted(fn),
        "predicted_count": len(predicted),
        "gold_count": len(gold),
    }


class SlideReviewEvaluator:
    """Case-level evaluator for slide issue detection."""

    def evaluate_case(
        self,
        *,
        detected_issues: list[dict[str, Any]],
        corruption_record: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "detection": evaluate_detection(detected_issues, corruption_record),
        }


def _safe_div(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _issue_pairs(detected_issues: list[dict[str, Any]]) -> set[tuple[str, str]]:
    pairs = set()
    for issue in detected_issues:
        target = issue.get("target")
        error_type = issue.get("error_type")
        if target is not None and error_type is not None:
            pairs.add((str(target), str(error_type)))
    return pairs


def _gold_detection_pairs(corruption_record: dict[str, Any]) -> set[tuple[str, str]]:
    pairs = set()
    for operation in corruption_record.get("operations", []):
        target = str(operation.get("target", ""))
        for error_type in operation.get("error_types", []):
            pairs.add((target, str(error_type)))
    return pairs
