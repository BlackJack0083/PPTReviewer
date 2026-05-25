from __future__ import annotations

from typing import Any

from method.slide_parser import RoleLabeler, parse_observed_slide

from .types import SlideReviewInput


class SlideParserAgent:
    """Phase 1.1 wrapper around method.slide_parser."""

    def __init__(self, role_labeler: RoleLabeler):
        self.role_labeler = role_labeler

    def run(self, slide_input: SlideReviewInput) -> dict[str, Any]:
        parsed = parse_observed_slide(
            pptx_path=slide_input.pptx_path,
            image_path=slide_input.image_path,
            role_labeler=self.role_labeler,
        )
        return {
            "observed_slide": parsed.observed_slide,
            "role_assignments": parsed.role_assignments,
        }
