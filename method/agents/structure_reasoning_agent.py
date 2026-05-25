from __future__ import annotations

from pathlib import Path
from typing import Any

from .pptx_visible_data_extractor import PPTXVisibleDataExtractor
from .query_tools import SlideAgentInspiredToolPlanner


def center(layout: dict[str, Any]) -> tuple[float, float]:
    return (
        float(layout.get("x", 0.0)) + float(layout.get("width", 0.0)) / 2.0,
        float(layout.get("y", 0.0)) + float(layout.get("height", 0.0)) / 2.0,
    )


class StructureReasoningAgent:
    """Build explicit slide topology around ST bodies, captions, summary and title."""

    def __init__(
        self,
        visible_data_extractor: PPTXVisibleDataExtractor | None = None,
        tool_planner: SlideAgentInspiredToolPlanner | None = None,
    ):
        self.visible_data_extractor = visible_data_extractor or PPTXVisibleDataExtractor()
        self.tool_planner = tool_planner or SlideAgentInspiredToolPlanner()

    def run(self, observed_slide: dict[str, Any], pptx_path: Path) -> dict[str, Any]:
        targets = {
            "title": [],
            "summary": [],
            "st.caption": [],
            "st.body": [],
            "st.header": [],
        }

        for element in observed_slide.get("elements", []):
            role = str(element.get("role", ""))
            if role == "slide-title":
                targets["title"].append(element)
            elif role == "body-text":
                targets["summary"].append(element)
            elif role == "caption":
                targets["st.caption"].append(element)
            elif role in {"chart-bar", "chart-line", "chart-pie", "table"}:
                targets["st.body"].append(element)

        visible_data = self.visible_data_extractor.extract(pptx_path, observed_slide)
        body_units = []
        captions = targets["st.caption"]
        for body_element in targets["st.body"]:
            body_center = center(body_element.get("layout", {}))
            paired_caption = None
            paired_distance = None
            for caption in captions:
                caption_center = center(caption.get("layout", {}))
                distance = abs(body_center[0] - caption_center[0]) + abs(body_center[1] - caption_center[1])
                if paired_distance is None or distance < paired_distance:
                    paired_distance = distance
                    paired_caption = caption

            body_units.append(
                {
                    "body_element": body_element,
                    "body_data": visible_data.get(str(body_element.get("id")), {}),
                    "paired_caption": paired_caption,
                }
            )

        targets["st.header"] = [
            {
                "element_id": str(unit["body_element"].get("id")),
                "anchor_role": unit["body_element"].get("role"),
                "metric_kinds": unit["body_data"].get("metric_kinds", []),
            }
            for unit in body_units
        ]
        summary_text = "\n".join(
            str(element.get("text", "")).strip()
            for element in targets["summary"]
            if str(element.get("text", "")).strip()
        )
        tool_context = self.tool_planner.build_for_units(
            body_units=body_units,
            summary_text=summary_text,
        )
        return {
            "targets": targets,
            "body_units": body_units,
            "query_intents": tool_context["query_intents"],
            "analysis_logic": tool_context["analysis_logic"],
            "aggregation_profiles": tool_context["aggregation_profiles"],
            "verifiable_targets": [name for name, items in targets.items() if items],
        }
