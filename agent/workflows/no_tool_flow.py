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
        system_prompt = (
            "You are a strict PPT summary verifier. "
            "Given one slide image, decide whether the summary statement is inconsistent "
            "with chart/table evidence on the same slide. "
            "Return JSON only: {\"has_issue\": true|false}."
        )
        user_prompt = (
            "Check this slide image. Focus on the summary text (usually body text). "
            "If trend/range/value/unit in summary conflicts with chart/table, set has_issue=true. "
            "If consistent, set has_issue=false. "
            "Output JSON only."
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
            "no_tool_raw": response,
        }

    return _run
