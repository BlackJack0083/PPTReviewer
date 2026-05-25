from __future__ import annotations

from typing import Any


def _safe_div(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _issue_pairs(detected_issues: list[dict[str, Any]]) -> set[tuple[str, str]]:
    pairs = set()
    for issue in detected_issues:
        for target in issue.get("targets", []):
            for error_type in issue.get("error_types", []):
                pairs.add((str(target), str(error_type)))
    return pairs


def _gold_detection_pairs(corruption_record: dict[str, Any]) -> set[tuple[str, str]]:
    pairs = set()
    for operation in corruption_record.get("operations", []):
        target = str(operation.get("target", ""))
        for error_type in operation.get("error_types", []):
            pairs.add((target, str(error_type)))
    return pairs


def _feedback_key(item: dict[str, Any]) -> str:
    error_types = ",".join(sorted(str(value) for value in item.get("error_types", [])))
    targets = ",".join(sorted(str(value) for value in item.get("targets", [])))
    required_fields = ",".join(sorted(str(value) for value in item.get("required_fields", [])))
    return f"errors={error_types}|targets={targets}|fields={required_fields}"


class FeedbackMatcher:
    """Match one interaction request to one feedback benchmark item."""

    def match(
        self,
        request: dict[str, Any],
        feedback_items: list[dict[str, Any]],
        consumed_keys: set[str] | None = None,
    ) -> dict[str, Any] | None:
        consumed = consumed_keys or set()
        request_targets = set(str(value) for value in request.get("targets", []))
        request_errors = set(str(value) for value in request.get("error_types", []))
        request_fields = set(str(value) for value in request.get("required_fields", []))

        for item in feedback_items:
            key = _feedback_key(item)
            if key in consumed:
                continue
            item_targets = set(str(value) for value in item.get("targets", []))
            item_errors = set(str(value) for value in item.get("error_types", []))
            item_fields = set(str(value) for value in item.get("required_fields", []))
            if item_targets != request_targets or item_errors != request_errors:
                continue
            if item_fields:
                if not request_fields.issuperset(item_fields):
                    continue
            elif request_fields:
                continue
            return item
        return None


class ClientSimulator:
    """Evaluator-only simulated client backed by feedback_episode.json."""

    def __init__(self, feedback_episode: dict[str, Any], matcher: FeedbackMatcher | None = None):
        self.feedback_episode = feedback_episode
        self.matcher = matcher or FeedbackMatcher()
        self.matched_feedback_keys: set[str] = set()

    def respond(self, request: dict[str, Any]) -> dict[str, Any]:
        matched_item = self.matcher.match(
            request,
            self.feedback_episode.get("feedback_items", []),
            self.matched_feedback_keys,
        )
        if matched_item is None:
            return {"matched": False, "state_patch": {}, "feedback_key": None}
        key = _feedback_key(matched_item)
        self.matched_feedback_keys.add(key)
        return {
            "matched": True,
            "state_patch": matched_item.get("state_patch", {}),
            "feedback_key": key,
        }


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


def evaluate_interaction(
    interaction_log: list[dict[str, Any]],
    feedback_episode: dict[str, Any],
) -> dict[str, Any]:
    gold_keys = {_feedback_key(item) for item in feedback_episode.get("feedback_items", [])}
    predicted_keys = {
        str(entry.get("matched_feedback_key"))
        for entry in interaction_log
        if entry.get("matched_feedback_key")
    }
    tp = predicted_keys & gold_keys
    fp = predicted_keys - gold_keys
    fn = gold_keys - predicted_keys
    precision = _safe_div(len(tp), len(predicted_keys))
    recall = _safe_div(len(tp), len(gold_keys))
    f1 = _safe_div(2 * precision * recall, precision + recall) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "matched_feedback_items": len(tp),
        "gold_feedback_items": len(gold_keys),
        "matched_keys": sorted(tp),
        "missing_keys": sorted(fn),
        "spurious_keys": sorted(fp),
    }


class SlideReviewEvaluator:
    """Case-level evaluator for Phase 1 and Phase 2."""

    def evaluate_case(
        self,
        *,
        detected_issues: list[dict[str, Any]],
        interaction_log: list[dict[str, Any]],
        corruption_record: dict[str, Any],
        feedback_episode: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "detection": evaluate_detection(detected_issues, corruption_record),
            "interaction": evaluate_interaction(interaction_log, feedback_episode),
        }
