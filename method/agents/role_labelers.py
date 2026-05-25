from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from method.slide_parser.role_labeler import ROLE_SET

PRESENTATION_LABEL_RE = re.compile(r"\((bar chart|line chart|pie chart|table)\)\s*$", re.I)
TREND_RE = re.compile(r"\b(increase|increased|decrease|decreased|growth|decline|upward|downward)\b", re.I)


class HeuristicRoleLabeler:
    """Offline role labeler used for tests and smoke runs without a VLM."""

    def label_roles(
        self,
        *,
        image_path: Path,
        observed_slide: dict[str, Any],
    ) -> list[dict[str, str]]:
        del image_path
        elements = list(observed_slide.get("elements", []))
        roles: dict[str, str] = {}

        text_elements = [element for element in elements if element.get("type") == "textBox"]
        non_text_elements = [element for element in elements if element.get("type") != "textBox"]

        for element in non_text_elements:
            shape_kind = str(element.get("_shape_kind") or element.get("type") or "")
            if shape_kind in ROLE_SET:
                roles[str(element["id"])] = shape_kind
            elif element.get("type") == "table":
                roles[str(element["id"])] = "table"
            else:
                roles[str(element["id"])] = "chart-bar"

        caption_ids = []
        summary_ids = []
        for element in text_elements:
            text = str(element.get("text", "")).strip()
            element_id = str(element["id"])
            if PRESENTATION_LABEL_RE.search(text) or "analysis" in text.lower():
                caption_ids.append(element_id)
            elif TREND_RE.search(text) or any(char.isdigit() for char in text):
                summary_ids.append(element_id)

        title_candidates = [element for element in text_elements if str(element["id"]) not in caption_ids + summary_ids]
        title_candidates.sort(key=lambda item: (item.get("layout", {}).get("y", 999.0), len(str(item.get("text", "")))))
        if not title_candidates and text_elements:
            title_candidates = sorted(
                text_elements,
                key=lambda item: (item.get("layout", {}).get("y", 999.0), len(str(item.get("text", "")))),
            )

        title_id = str(title_candidates[0]["id"]) if title_candidates else None

        for element in text_elements:
            element_id = str(element["id"])
            if element_id in roles:
                continue
            if element_id == title_id:
                roles[element_id] = "slide-title"
            elif element_id in caption_ids:
                roles[element_id] = "caption"
            else:
                roles[element_id] = "body-text"

        return [{"id": element_id, "role": role} for element_id, role in sorted(roles.items(), key=lambda item: int(item[0]))]
