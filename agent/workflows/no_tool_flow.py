from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from agent.json_utils import parse_json_object


def build_no_tool_graph(client) -> Any:
    graph = StateGraph(dict)
    graph.add_node("no_tool_judge", _node_no_tool_judge(client))
    graph.set_entry_point("no_tool_judge")
    graph.add_edge("no_tool_judge", END)
    return graph.compile()


def _node_no_tool_judge(client):
    def _run(state: dict[str, Any]) -> dict[str, Any]:
        image_path = Path(state["image_path"])
        editable_shapes = state.get("editable_shapes", [])
        system_prompt = (
            "You are a strict PPT summary corrector without tool access. "
            "Given one slide image plus editable textbox metadata, decide whether the summary statement "
            "is inconsistent with chart/table evidence on the same slide. Return strict JSON only."
        )
        user_prompt = (
            "Check this slide image. Focus on the summary text (usually body text).\n"
            f"Editable textboxes:\n{editable_shapes}\n\n"
            "Output JSON with this schema:\n"
            "- If the slide is already correct: {\"has_issue\": false}\n"
            "- If the slide needs correction: "
            "{\"has_issue\": true, \"shape_id\": \"...\", \"updated_summary\": \"...\"}\n\n"
            "Rules:\n"
            "- shape_id must be chosen from the editable textboxes above.\n"
            "- Prefer correcting the summary/body-text textbox rather than title/caption unless the evidence clearly shows otherwise.\n"
            "- updated_summary must be the corrected final summary text.\n"
            "- Do not output any explanation outside JSON."
        )
        response = client.chat(
            system_prompt,
            user_prompt,
            image_path=image_path,
            response_format="json_object",
        )
        parsed = parse_json_object(response)
        return {
            "has_issue": bool(parsed.get("has_issue", False)),
            "shape_id": str(parsed.get("shape_id", "")).strip() or None,
            "updated_summary": str(parsed.get("updated_summary", "")).strip() or None,
            "no_tool_raw": response,
        }

    return _run
