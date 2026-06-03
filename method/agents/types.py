from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def merge_fields(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for field_name in right:
        if field_name not in merged:
            merged.append(field_name)
    return merged


@dataclass
class SlideReviewInput:
    """单个 injected case 中 slide review workflow 可见的输入。"""

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
class SlideReviewResult:
    observed_slide: dict[str, Any]
    ppt_representation: dict[str, Any]
    analysis_state: dict[str, Any]
    detected_issues: list[dict[str, Any]]
    data_source_validation_log: list[dict[str, Any]] = field(default_factory=list)
    content_validation_log: list[dict[str, Any]] = field(default_factory=list)
    table_records: list[dict[str, Any]] = field(default_factory=list)
    update_log: list[dict[str, Any]] = field(default_factory=list)
    repaired_artifacts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_slide": self.observed_slide,
            "ppt_representation": self.ppt_representation,
            "analysis_state": self.analysis_state,
            "data_source_validation_log": self.data_source_validation_log,
            "content_validation_log": self.content_validation_log,
            "table_records": self.table_records,
            "detected_issues": self.detected_issues,
            "update_log": self.update_log,
            "repaired_artifacts": self.repaired_artifacts,
        }
