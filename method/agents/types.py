from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def merge_patch(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_patch(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_fields(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for field_name in right:
        if field_name not in merged:
            merged.append(field_name)
    return merged


@dataclass
class SlideReviewInput:
    """Input visible to the slide review workflow for one injected case."""

    case_id: str
    pptx_path: Path
    image_path: Path


@dataclass
class DetectedIssue:
    targets: list[str]
    error_types: list[str]
    evidence: str
    required_fields_guess: list[str] = field(default_factory=list)
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "targets": list(self.targets),
            "error_types": list(self.error_types),
            "evidence": self.evidence,
            "required_fields_guess": list(self.required_fields_guess),
        }
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        return payload


@dataclass
class RepairState:
    scope: dict[str, Any] = field(default_factory=dict)
    logic: dict[str, Any] = field(default_factory=dict)
    claim: dict[str, Any] = field(default_factory=dict)
    targets_to_repair: list[str] = field(default_factory=list)

    def merge(self, state_patch: dict[str, Any], targets: list[str]) -> None:
        if "scope" in state_patch and isinstance(state_patch["scope"], dict):
            self.scope = merge_patch(self.scope, state_patch["scope"])
        if "logic" in state_patch and isinstance(state_patch["logic"], dict):
            self.logic = merge_patch(self.logic, state_patch["logic"])
        if "claim" in state_patch and isinstance(state_patch["claim"], dict):
            self.claim = merge_patch(self.claim, state_patch["claim"])
        self.targets_to_repair = merge_fields(self.targets_to_repair, targets)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "logic": self.logic,
            "claim": self.claim,
            "targets_to_repair": self.targets_to_repair,
        }


@dataclass
class SlideReviewResult:
    observed_slide: dict[str, Any]
    structured_understanding: dict[str, Any]
    detected_issues: list[dict[str, Any]]
    interaction_log: list[dict[str, Any]]
    repair_state: dict[str, Any]
    repair_plan: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_slide": self.observed_slide,
            "structured_understanding": self.structured_understanding,
            "detected_issues": self.detected_issues,
            "interaction_log": self.interaction_log,
            "repair_state": self.repair_state,
            "repair_plan": self.repair_plan,
        }
