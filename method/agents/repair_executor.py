from __future__ import annotations

from pathlib import Path
from typing import Any


class RepairExecutor:
    """Phase 3 stub. It documents future inputs but does not edit PPT yet."""

    def plan(
        self,
        *,
        observed_slide: dict[str, Any],
        repair_state: dict[str, Any],
        source_pptx: Path,
    ) -> dict[str, Any]:
        return {
            "status": "stub",
            "phase": "phase_3",
            "source_pptx": str(source_pptx),
            "planned_targets": list(repair_state.get("targets_to_repair", [])),
            "available_state": {
                "scope": repair_state.get("scope", {}),
                "logic": repair_state.get("logic", {}),
                "claim": repair_state.get("claim", {}),
            },
            "required_inputs": [
                "observed_slide",
                "repair_state",
                "slide.pptx",
                "data query / aggregation tools",
            ],
            "required_outputs": [
                "updated caption/header/body/summary/title",
                "repaired slide.pptx",
                "repair evaluation against GT",
            ],
            "notes": (
                "This stub does not modify PPT content yet. It only fixes the interface "
                "between Phase 2 state collection and future repair execution."
            ),
            "observed_element_count": len(observed_slide.get("elements", [])),
        }

    def run(
        self,
        *,
        observed_slide: dict[str, Any],
        repair_state: dict[str, Any],
        source_pptx: Path,
    ) -> dict[str, Any]:
        return {
            "status": "not_implemented",
            "plan": self.plan(
                observed_slide=observed_slide,
                repair_state=repair_state,
                source_pptx=source_pptx,
            ),
        }
