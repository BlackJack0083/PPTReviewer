import json
import re
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
    normalize_template_id=None,
) -> Any:
    graph = StateGraph(dict)
    graph.add_node(
        "extract_claim",
        _node_extract_claim(client, template_candidates, table_candidates),
    )
    graph.add_node(
        "validate_claim",
        _node_validate_claim(
            template_candidates,
            table_candidates,
            normalize_template_id,
        ),
    )
    graph.add_node("run_tools", _node_run_tools(tools))
    graph.add_node("judge_with_tool", _node_judge_with_tool(client))
    graph.add_node("plan_text_edit", _node_plan_text_edit(client))
    graph.add_node("apply_text_edit", _node_apply_text_edit(tools))
    graph.set_entry_point("extract_claim")
    graph.add_edge("extract_claim", "validate_claim")
    graph.add_edge("validate_claim", "run_tools")
    graph.add_edge("run_tools", "judge_with_tool")
    graph.add_conditional_edges(
        "judge_with_tool",
        _route_after_judge,
        {
            "plan_text_edit": "plan_text_edit",
            "end": END,
        },
    )
    graph.add_edge("plan_text_edit", "apply_text_edit")
    graph.add_edge("apply_text_edit", END)
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
        "tool_calls",
        "evidence",
        "routed_template_meta",
        "editable_shapes",
        "run_id",
        "yaml_path",
        "has_issue",
        "shape_id",
        "updated_summary",
        "judge_raw",
        "edit_plan_raw",
        "execution_success",
        "edit_attempted",
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
            "- template_id must be copied exactly from candidate list (prefer human-readable alias names when provided).\n"
            "- do not invent a new template_id or table_name outside candidates.\n"
            "- block must be pure block name only, never prepend city.\n"
            
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
            
            "Example A:\n"
            "Input text: \"**Shenzhen** **Baolong Technology Park** ...\"\n"
            "Output:\n"
            "{\"template_id\":\"New-House Supply_Transaction Area Analysis Line Chart\","
            "\"table_name\":\"Shenzhen_new_house\","
            "\"city\":\"Shenzhen\","
            "\"block\":\"Baolong Technology Park\","
            "\"start_year\":\"2020\","
            "\"end_year\":\"2024\","
            "\"summary_text\":\"The region experienced ...\"}\n"
            
            "Example B:\n"
            "Input text: \"**2020**-**2024** **Beijing** **Mapo** Area and Total Price Cross Statistics\"\n"
            "Output:\n"
            "{\"template_id\":\"New-House Cross-Structure Analysis Table\","
            "\"table_name\":\"Beijing_new_house\","
            "\"city\":\"Beijing\","
            "\"block\":\"Mapo\","
            "\"start_year\":\"2020\","
            "\"end_year\":\"2024\","
            "\"summary_text\":\"From 2020 to 2024, ...\"}\n"
            
            "If uncertain, choose the nearest candidate from the lists and still output valid JSON only."
        )
        response = client.chat(
            system_prompt,
            user_prompt,
            image_path=image_path,
            response_format="json_object",
        )
        claim = parse_json_object(response)
        return _with_carried_state(
            state,
            parsed_claim=claim,
            claim_raw=response,
        )

    return _run


def _node_validate_claim(
    template_candidates: list[str],
    table_candidates: list[str],
    normalize_template_id=None,
):
    template_set = set(template_candidates)
    table_set = set(table_candidates)
    year_pattern = re.compile(r"^\d{4}$")

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

        template_id = str(claim["template_id"]).strip()
        canonical_template_id = (
            normalize_template_id(template_id)
            if callable(normalize_template_id)
            else template_id
        )
        table_name = str(claim["table_name"]).strip()
        start_year = str(claim["start_year"]).strip()
        end_year = str(claim["end_year"]).strip()
        if template_id not in template_set:
            raise ValueError(f"Claim extraction invalid template_id: {template_id}")
        if table_name not in table_set:
            raise ValueError(f"Claim extraction invalid table_name: {table_name}")
        if not year_pattern.fullmatch(start_year) or not year_pattern.fullmatch(end_year):
            raise ValueError(
                f"Claim extraction invalid year format: start={start_year}, end={end_year}"
            )
        if int(start_year) > int(end_year):
            raise ValueError(
                f"Claim extraction invalid year range: start={start_year}, end={end_year}"
            )
        claim["template_id"] = canonical_template_id
        return _with_carried_state(state)

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
            tool_calls=[
                "resolve_plan",
                "query_conclusion_vars",
                "build_expected_summary",
            ],
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
                "You are the final grounded judge. "
                "Compare the summary text from image with evidence from data tools, "
                "and decide only whether the input slide has a factual issue. "
                "Return strict JSON only."
            ),
            user_prompt=(
                "Determine whether the summary is inconsistent with tool evidence.\n"
                f"summary_text_from_image:\n{claim['summary_text']}\n\n"
                f"expected_summary_from_tool:\n{evidence.expected_summary}\n\n"
                f"expected_summary_slots:\n{json.dumps(evidence.expected_summary_slots, ensure_ascii=False)}\n\n"
                "Output JSON with this schema:\n"
                "{\"has_issue\": true|false}\n\n"
                "Rules:\n"
                "- If any key factual mismatch exists, set has_issue=true.\n"
                "- Otherwise set has_issue=false."
            ),
            image_path=None,
            response_format="json_object",
        )
        parsed = parse_json_object(judge_response)
        return _with_carried_state(
            state,
            has_issue=bool(parsed.get("has_issue", False)),
            shape_id=None,
            updated_summary=None,
            judge_raw=judge_response,
            execution_success=None,
            edit_attempted=False,
        )

    return _run


def _route_after_judge(state: dict[str, Any]) -> str:
    return "plan_text_edit" if state.get("has_issue", False) else "end"


def _node_plan_text_edit(client):
    def _run(state: dict[str, Any]) -> dict[str, Any]:
        evidence: ToolEvidence = state["evidence"]
        editable_shapes = state.get("editable_shapes", [])
        plan_response = client.chat(
            system_prompt=(
                "You are the grounded text edit planner. "
                "The slide has already been judged incorrect. "
                "Choose the correct textbox and produce the corrected final summary text. "
                "Return strict JSON only."
            ),
            user_prompt=(
                "The input slide is already confirmed to have a factual issue.\n"
                "Use the tool evidence below to plan exactly one textbox edit.\n\n"
                f"expected_summary_from_tool:\n{evidence.expected_summary}\n\n"
                f"expected_summary_slots:\n{json.dumps(evidence.expected_summary_slots, ensure_ascii=False)}\n\n"
                f"editable_textboxes:\n{json.dumps(editable_shapes, ensure_ascii=False)}\n\n"
                "Output JSON with this schema:\n"
                "{\"shape_id\": \"...\", \"updated_summary\": \"...\"}\n\n"
                "Rules:\n"
                "- shape_id must be chosen from editable_textboxes.\n"
                "- Prefer correcting the summary/body-text textbox rather than title/caption unless evidence clearly shows otherwise.\n"
                "- updated_summary must be the corrected final text to write into that textbox.\n"
                "- Do not return has_issue here; the issue has already been confirmed."
            ),
            image_path=None,
            response_format="json_object",
        )
        parsed = parse_json_object(plan_response)
        return _with_carried_state(
            state,
            shape_id=str(parsed.get("shape_id", "")).strip() or None,
            updated_summary=str(parsed.get("updated_summary", "")).strip() or None,
            edit_plan_raw=plan_response,
        )

    return _run


def _node_apply_text_edit(tools):
    def _run(state: dict[str, Any]) -> dict[str, Any]:
        if not state.get("has_issue", False):
            return _with_carried_state(
                state,
                execution_success=None,
                edit_attempted=False,
            )

        shape_id = str(state.get("shape_id", "")).strip()
        updated_summary = str(state.get("updated_summary", "")).strip()
        editable_shapes = state.get("editable_shapes", [])
        editable_shape_ids = {
            str(item.get("shape_id", "")).strip()
            for item in editable_shapes
            if isinstance(item, dict)
        }

        if not shape_id or not updated_summary or shape_id not in editable_shape_ids:
            return _with_carried_state(
                state,
                execution_success=False,
                edit_attempted=False,
            )

        edit_attempted = False
        try:
            edit_attempted = True
            apply_kwargs = {
                "shape_id": shape_id,
                "new_text": updated_summary,
                "yaml_path": state["yaml_path"],
            }
            if state.get("run_id"):
                apply_kwargs["run_id"] = state["run_id"]
            execution_success = tools.apply_textbox_edit(
                **apply_kwargs,
            )
        except Exception:  # noqa: BLE001 - execution failure should not erase model prediction
            execution_success = False

        tool_calls = list(state.get("tool_calls", []))
        if edit_attempted:
            tool_calls.append("apply_textbox_edit")

        return _with_carried_state(
            state,
            execution_success=bool(execution_success),
            edit_attempted=edit_attempted,
            tool_calls=tool_calls,
        )

    return _run
