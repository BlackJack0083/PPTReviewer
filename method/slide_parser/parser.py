from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .pptx_elements import extract_pptx_elements
from .role_labeler import RoleLabeler, apply_role_assignments, validate_role_assignments


@dataclass
class ParsedSlide:
    """Phase 1.1 parser output."""

    observed_slide: dict[str, Any]
    role_assignments: list[dict[str, str]]


def parse_observed_slide(
    *,
    pptx_path: Path,
    image_path: Path,
    role_labeler: RoleLabeler,
    slide_idx: int = 0,
) -> ParsedSlide:
    """Parse a PPTX and use a VLM labeler to attach element roles."""
    raw_observed_slide = extract_pptx_elements(pptx_path=pptx_path, slide_idx=slide_idx)

    roles = role_labeler.label_roles(
        image_path=image_path,
        observed_slide=raw_observed_slide,
    )
    validated_roles = validate_role_assignments(raw_observed_slide, roles)
    observed_slide = apply_role_assignments(raw_observed_slide, validated_roles)
    return ParsedSlide(
        observed_slide=observed_slide,
        role_assignments=validated_roles,
    )
