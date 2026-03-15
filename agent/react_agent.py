from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from agent.image_utils import image_data_url
from agent.json_utils import parse_json_object


class ReactJudgeOutput(BaseModel):
    has_issue: bool


def build_react_agent_graph(
    *,
    model_name: str,
    api_key: str,
    base_url: str,
    tools,
    template_candidates: list[str],
    table_candidates: list[str],
    enable_thinking: bool | None = False,
):
    extra_body = {"enable_thinking": enable_thinking} if enable_thinking is not None else None
    model = ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        timeout=120,
        extra_body=extra_body,
    )
    system_prompt = (
        "You are a strict PPT summary verifier with tool access.\n"
        "Task: determine whether the slide summary has factual issues.\n"
        f"Allowed template_id candidates: {template_candidates}\n"
        f"Allowed table_name candidates: {table_candidates}\n\n"
        "Hard rules:\n"
        "- You MUST use tools before final judgment. Do not decide only by visual impression.\n"
        "- You MUST return final output as strict JSON only: {\"has_issue\": true|false}.\n"
        "- Do not output explanations in the final answer.\n\n"
        "Required extraction fields from image:\n"
        "- template_id, table_name, city, block, start_year, end_year, summary_text.\n"
        "- template_id and table_name must be selected from candidate lists.\n\n"
        "Required tool:\n"
        "1) resolve_plan(template_id) -> get function_key and function_args\n"
        "2) query_conclusion_vars(city, block, start_year, end_year, table_name, function_key, function_args)\n"
        "3) build_expected_summary(template_id, city, block, start_year, end_year, conclusion_vars)\n\n"
        "Judgment criterion:\n"
        "- Compare summary_text from image against tool-derived expected_summary and expected_summary_slots.\n"
        "- If any key factual mismatch exists (value/range/trend/unit/time), return has_issue=true.\n"
        "- Otherwise return has_issue=false."
    )
    return create_agent(
        model=model,
        tools=build_react_tools(tools),
        system_prompt=system_prompt,
        response_format=ReactJudgeOutput,
    )


def build_react_input_messages(image_path: Path) -> dict[str, Any]:
    user_prompt = (
        "Analyze this slide image and determine whether the summary has factual issue.\n"
        "You must use tools for evidence before final judgment.\n"
        "Final output must be JSON: {\"has_issue\": true|false}."
    )
    return {
        "messages": [
            HumanMessage(
                content=[
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url(image_path)}},
                ]
            )
        ]
    }


def build_react_tools(tools):
    @tool
    def resolve_plan(template_id: str) -> dict[str, Any]:
        """
        Resolve template routing and default function plan from template_id.

        Input:
        - template_id: must be one candidate template id.

        Returns:
        - template_id
        - theme_key
        - summary_item
        - function_key
        - function_args
        """
        return tools.resolve_plan(template_id)

    @tool
    def query_conclusion_vars(
        city: str,
        block: str,
        start_year: str,
        end_year: str,
        table_name: str,
        function_key: str,
        function_args: dict[str, Any],
    ) -> dict[str, str]:
        """
        Core DB/statistics tool. Use when all query fields are ready.

        Required inputs:
        - city, block, start_year, end_year, table_name
        - function_key
        - function_args (dict)

        Returns:
        - conclusion variable dict for rendering expected summary.

        Call this before render_expected_summary / extract_expected_summary_slots.
        """
        return tools.query_conclusion_vars(
            city=city,
            block=block,
            start_year=start_year,
            end_year=end_year,
            table_name=table_name,
            function_key=function_key,
            function_args=function_args,
        )

    @tool
    def build_expected_summary(
        template_id: str,
        city: str,
        block: str,
        start_year: str,
        end_year: str,
        conclusion_vars: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Build expected summary material from template + conclusion variables.

        Inputs:
        - template_id
        - city, block, start_year, end_year
        - conclusion_vars (dict)

        Returns:
        - expected_summary
        - expected_summary_slots
        """
        return tools.build_expected_summary(
            template_id=template_id,
            city=city,
            block=block,
            start_year=start_year,
            end_year=end_year,
            conclusion_vars={str(k): str(v) for k, v in conclusion_vars.items()},
        )

    return [
        resolve_plan,
        query_conclusion_vars,
        build_expected_summary,
    ]


def extract_final_ai_message_text(state: dict[str, Any]) -> str:
    for msg in reversed(state.get("messages", [])):
        if getattr(msg, "type", "") != "ai":
            continue
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            text = content.strip()
            if text:
                return text
            continue
        if not isinstance(content, list):
            continue
        texts = [
            str(item.get("text"))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
        ]
        if texts:
            return "\n".join(texts).strip()
    return ""


def coerce_structured_response_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, str):
        try:
            value = parse_json_object(value)
        except Exception:  # noqa: BLE001 - best effort parser
            return {}
    if isinstance(value, dict):
        return value
    return {}


def extract_react_output_json(state: dict[str, Any]) -> dict[str, Any]:
    structured_json = coerce_structured_response_dict(state.get("structured_response"))
    if structured_json:
        return structured_json
    final_text = extract_final_ai_message_text(state)
    if final_text:
        return parse_json_object(final_text)
    raise ValueError("React agent returned no structured_response and empty final AI text.")


def extract_called_tools(state: dict[str, Any]) -> list[str]:
    """Extract actual tool-call sequence from AI messages in react state."""
    trace = _build_tool_trace(state.get("messages", []))
    return [item["name"] for item in trace]


def extract_react_claim_and_evidence(
    state: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Best-effort extraction of claim/evidence from react tool-call trace.

    Claim mainly comes from query_conclusion_vars arguments.
    Evidence comes from resolve_plan + build_expected_summary outputs.
    """
    trace = _build_tool_trace(state.get("messages", []))

    def _last(tool_name: str) -> dict[str, Any]:
        for item in reversed(trace):
            if item.get("name") == tool_name:
                return item
        return {}

    plan = _last("resolve_plan")
    query = _last("query_conclusion_vars")
    summary = _last("build_expected_summary")

    plan_args = plan.get("args", {})
    plan_result = plan.get("result", {})
    query_args = query.get("args", {})
    summary_result = summary.get("result", {})

    template_id = (
        plan_result.get("template_id")
        or plan_args.get("template_id")
        or query_args.get("template_id")
    )
    function_args = _to_dict(query_args.get("function_args")) or _to_dict(
        plan_result.get("function_args")
    )

    claim = None
    if query_args:
        claim_data = {
            "template_id": template_id,
            "table_name": query_args.get("table_name"),
            "city": query_args.get("city"),
            "block": query_args.get("block"),
            "start_year": query_args.get("start_year"),
            "end_year": query_args.get("end_year"),
        }
        claim = {k: v for k, v in claim_data.items() if v is not None} or None

    evidence = None
    if plan_result or query_args or summary_result:
        evidence_data = {
            "template_id": template_id,
            "function_key": plan_result.get("function_key") or query_args.get("function_key"),
            "city": query_args.get("city"),
            "block": query_args.get("block"),
            "start_year": query_args.get("start_year"),
            "end_year": query_args.get("end_year"),
            "table_name": query_args.get("table_name"),
            "function_args": function_args,
            "expected_summary_slots": _to_dict(summary_result.get("expected_summary_slots")),
            "expected_summary": summary_result.get("expected_summary", ""),
        }
        evidence = {k: v for k, v in evidence_data.items() if v is not None} or None

    return claim, evidence


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return parse_json_object(value)
        except Exception:  # noqa: BLE001 - best effort parser
            return {}
    return {}


def _build_tool_trace(messages: list[Any]) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    call_by_id: dict[str, dict[str, Any]] = {}
    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None)
        if not isinstance(tool_calls, list):
            continue
        for call in tool_calls:
            if isinstance(call, dict):
                call_id = call.get("id")
                name = call.get("name")
                args = call.get("args")
            else:
                call_id = getattr(call, "id", None)
                name = getattr(call, "name", None)
                args = getattr(call, "args", None)
            if not isinstance(name, str) or not name:
                continue
            item = {"name": name, "args": _to_dict(args), "result": {}}
            trace.append(item)
            if isinstance(call_id, str) and call_id:
                call_by_id[call_id] = item

    for msg in messages:
        if getattr(msg, "type", "") != "tool":
            continue
        call_id = getattr(msg, "tool_call_id", None)
        if isinstance(call_id, str) and call_id in call_by_id:
            call_by_id[call_id]["result"] = _to_dict(getattr(msg, "content", None))
    return trace
