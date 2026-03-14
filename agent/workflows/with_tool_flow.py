import json
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from agent.json_utils import parse_json_object
from agent.tools_local import ToolEvidence


def build_with_tool_graph(
    client,
    tools,
    template_candidates: list[str],
    table_candidates: list[str],
) -> Any:
    graph = StateGraph(dict)
    graph.add_node(
        "extract_claim",
        _node_extract_claim(client, template_candidates, table_candidates),
    )
    graph.add_node("validate_claim", _node_validate_claim())
    graph.add_node("plan_tools", _node_plan_tools())
    graph.add_node("run_tools", _node_run_tools(tools))
    graph.add_node("judge_with_tool", _node_judge_with_tool(client))
    graph.set_entry_point("extract_claim")
    graph.add_edge("extract_claim", "validate_claim")
    graph.add_edge("validate_claim", "plan_tools")
    graph.add_edge("plan_tools", "run_tools")
    graph.add_edge("run_tools", "judge_with_tool")
    graph.add_edge("judge_with_tool", END)
    return graph.compile()


def evidence_to_dict(evidence: ToolEvidence) -> dict[str, Any]:
    return {
        "template_id": evidence.template_id,
        "function_key": evidence.function_key,
        "city": evidence.city,
        "block": evidence.block,
        "start_year": evidence.start_year,
        "end_year": evidence.end_year,
        "table_name": evidence.table_name,
        "function_args": evidence.function_args,
        "expected_summary_slots": evidence.expected_summary_slots,
        "expected_summary": evidence.expected_summary,
    }


def _with_carried_state(state: dict[str, Any], **updates: Any) -> dict[str, Any]:
    carried_keys = (
        "parsed_claim",
        "claim_raw",
        "tool_plan",
        "evidence",
        "routed_template_meta",
    )
    result = {k: state[k] for k in carried_keys if k in state}
    result.update(updates)
    return result


def _node_extract_claim(client, template_candidates: list[str], table_candidates: list[str]):
    def _run(state: dict[str, Any]) -> dict[str, Any]:
        image_path = Path(state["image_path"])
        system_prompt = (
            "You extract structured claim info from a slide image for tool-based verification. "
            "Return strict JSON only."
        )
        user_prompt = (
            "Read the slide image and extract fields for database verification.\n"
            f"- template_id must be one of: {template_candidates}\n"
            f"- table_name must be one of: {table_candidates}\n"
            "Return JSON with keys:\n"
            "{\n"
            "  \"template_id\": \"...\",\n"
            "  \"table_name\": \"...\",\n"
            "  \"city\": \"...\",\n"
            "  \"block\": \"...\",\n"
            "  \"start_year\": \"YYYY\",\n"
            "  \"end_year\": \"YYYY\",\n"
            "  \"summary_text\": \"exact summary sentence from slide\"\n"
            "}\n"
            "Use best effort. Output JSON only."
        )
        response = client.chat(
            system_prompt,
            user_prompt,
            image_path=image_path,
            response_format="json_object",
        )
        claim = parse_json_object(response)
        return {"parsed_claim": claim, "claim_raw": response}

    return _run


def _node_validate_claim():
    def _run(state: dict[str, Any]) -> dict[str, Any]:
        claim = state["parsed_claim"]
        required_keys = [
            "template_id",
            "table_name",
            "city",
            "block",
            "start_year",
            "end_year",
            "summary_text",
        ]
        missing = [k for k in required_keys if not claim.get(k)]
        if missing:
            raise ValueError(f"Claim extraction missing keys: {missing}; claim={claim}")
        return _with_carried_state(state)

    return _run


def _node_plan_tools():
    def _run(state: dict[str, Any]) -> dict[str, Any]:
        tool_plan = [
            "resolve_plan",
            "query_conclusion_vars",
            "build_expected_summary",
        ]
        return _with_carried_state(state, tool_plan=tool_plan)

    return _run


def _node_run_tools(tools):
    def _run(state: dict[str, Any]) -> dict[str, Any]:
        claim = state["parsed_claim"]
        template_id = str(claim["template_id"])
        city = str(claim["city"])
        block = str(claim["block"])
        start_year = str(claim["start_year"])
        end_year = str(claim["end_year"])
        table_name = str(claim["table_name"])

        plan = tools.resolve_plan(template_id)
        function_key = str(plan["function_key"])
        function_args = dict(plan["function_args"])
        
        conclusion_vars = tools.query_conclusion_vars(
            city=city,
            block=block,
            start_year=start_year,
            end_year=end_year,
            table_name=table_name,
            function_key=function_key,
            function_args=function_args,
        )
        summary_bundle = tools.build_expected_summary(
            template_id=template_id,
            city=city,
            block=block,
            start_year=start_year,
            end_year=end_year,
            conclusion_vars=conclusion_vars,
        )
        expected_summary = str(summary_bundle.get("expected_summary", ""))
        raw_slots = summary_bundle.get("expected_summary_slots", {})
        expected_summary_slots = (
            {str(k): str(v) for k, v in raw_slots.items()}
            if isinstance(raw_slots, dict)
            else {}
        )
        evidence = ToolEvidence(
            template_id=template_id,
            function_key=function_key,
            city=city,
            block=block,
            start_year=start_year,
            end_year=end_year,
            table_name=table_name,
            function_args=function_args,
            conclusion_vars=conclusion_vars,
            expected_summary=expected_summary,
            expected_summary_slots=expected_summary_slots,
        )
        return _with_carried_state(
            state,
            evidence=evidence,
            routed_template_meta=json.dumps(
                {
                    "template_id": str(plan.get("template_id", template_id)),
                    "theme_key": str(plan.get("theme_key", "")),
                    "summary_item": plan.get("summary_item", 0),
                },
                ensure_ascii=False,
            ),
        )

    return _run


def _node_judge_with_tool(client):
    def _run(state: dict[str, Any]) -> dict[str, Any]:
        claim = state["parsed_claim"]
        evidence: ToolEvidence = state["evidence"]
        judge_response = client.chat(
            system_prompt=(
                "You are the final verifier. "
                "Compare the summary text from image with evidence from data tools. "
                "Return strict JSON only: {\"has_issue\": true|false}."
            ),
            user_prompt=(
                "Determine whether the summary is inconsistent with tool evidence.\n"
                f"summary_text_from_image:\n{claim['summary_text']}\n\n"
                f"expected_summary_from_tool:\n{evidence.expected_summary}\n\n"
                f"expected_summary_slots:\n{json.dumps(evidence.expected_summary_slots, ensure_ascii=False)}\n\n"
                "If any key factual mismatch exists (trend/range/value), set has_issue=true.\n"
                "Output JSON only."
            ),
            image_path=None,
            response_format="json_object",
        )
        parsed = parse_json_object(judge_response)
        return _with_carried_state(
            state,
            has_issue=bool(parsed.get("has_issue", False)),
            judge_raw=judge_response,
        )

    return _run
