from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .client import Client
from .image_utils import ensure_image_exists
from .json_utils import parse_json_object
from .react_agent import (
    build_react_agent_graph,
    build_react_input_messages,
    coerce_structured_response_dict,
    extract_called_tools,
    extract_react_claim_and_evidence,
    extract_final_ai_message_text,
    extract_react_output_json,
)
from .tools_local import LocalDataTools
from .workflows.no_tool_flow import build_no_tool_graph
from .workflows.with_tool_flow import build_with_tool_graph, evidence_to_dict

Mode = Literal["no_tool", "with_tool", "with_tool_react"]


@dataclass
class AgentResult:
    has_issue: bool
    mode: Mode
    claim: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    tool_calls: list[str] = field(default_factory=list)
    final: dict[str, Any] = field(default_factory=dict)
    debug: dict[str, Any] = field(default_factory=dict)


class PPTSummaryJudgeAgent:
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        template_candidates: list[str] | None = None,
        table_candidates: list[str] | None = None,
        enable_thinking: bool | None = False,
        react_recursion_limit: int = 10,
    ):
        self.client = Client(
            model=model,
            api_key=api_key,
            base_url=base_url,
            enable_thinking=enable_thinking,
        )
        self.model = model
        self.api_key = self.client.api_key
        self.base_url = base_url
        self.react_recursion_limit = max(1, int(react_recursion_limit))
        self.tools = LocalDataTools()
        self.template_candidates = (
            template_candidates if template_candidates else self.tools.list_template_ids()
        )
        self.table_candidates = (
            table_candidates if table_candidates else self.tools.list_table_names()
        )
        self._no_tool_graph = build_no_tool_graph(self.client)
        self._with_tool_graph = build_with_tool_graph(
            client=self.client,
            tools=self.tools,
            template_candidates=self.template_candidates,
            table_candidates=self.table_candidates,
        )
        self._with_tool_react_graph = build_react_agent_graph(
            model_name=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            tools=self.tools,
            template_candidates=self.template_candidates,
            table_candidates=self.table_candidates,
            enable_thinking=enable_thinking,
        )

    def judge(
        self,
        image_path: str | Path,
        mode: Mode,
        *,
        auto_render_image: bool = True,
        render_dpi: int = 200,
        render_backend: str = "auto",
        poppler_path: str | None = None,
        graph_config: dict[str, Any] | None = None,
        include_debug: bool = False,
    ) -> AgentResult:
        resolved_image_path = ensure_image_exists(
            Path(image_path),
            auto_render_image=auto_render_image,
            render_dpi=render_dpi,
            render_backend=render_backend,
            poppler_path=poppler_path,
        )

        if mode == "no_tool":
            state = self._no_tool_graph.invoke(
                {"image_path": resolved_image_path, "mode": "no_tool"},
                config=graph_config,
            )
            no_tool_raw = state.get("no_tool_raw", "")
            parsed_json: dict[str, Any] | None = None
            try:
                parsed_json = parse_json_object(no_tool_raw) if no_tool_raw else None
            except Exception:  # noqa: BLE001 - fallback to boolean-only output
                parsed_json = None
            final_json = parsed_json or {"has_issue": bool(state.get("has_issue", False))}

            final_data: dict[str, Any] = {"json": final_json}
            if include_debug or parsed_json is None:
                final_data["text"] = no_tool_raw

            return AgentResult(
                has_issue=bool(state.get("has_issue", False)),
                mode="no_tool",
                final=final_data,
                debug={},
            )

        if mode == "with_tool":
            state = self._with_tool_graph.invoke(
                {"image_path": resolved_image_path, "mode": "with_tool"},
                config=graph_config,
            )
            evidence = state.get("evidence")
            judge_raw = state.get("judge_raw", "")
            parsed_json: dict[str, Any] | None = None
            try:
                parsed_json = parse_json_object(judge_raw) if judge_raw else None
            except Exception:  # noqa: BLE001 - fallback to boolean-only output
                parsed_json = None
            final_json = parsed_json or {"has_issue": bool(state.get("has_issue", False))}

            final_data: dict[str, Any] = {"json": final_json}
            if include_debug or parsed_json is None:
                final_data["text"] = judge_raw

            debug_data: dict[str, Any] = {}
            if include_debug:
                routed_template_meta: dict[str, Any] | None = None
                routed_template_meta_raw = state.get("routed_template_meta", "")
                if isinstance(routed_template_meta_raw, str) and routed_template_meta_raw:
                    try:
                        routed_template_meta = parse_json_object(routed_template_meta_raw)
                    except Exception:  # noqa: BLE001 - debug best effort
                        routed_template_meta = None
                debug_data = {
                    "claim_raw": state.get("claim_raw", ""),
                    "tool_defs": self.tools.available_tools(),
                    "routed_template_meta": routed_template_meta,
                }

            return AgentResult(
                has_issue=bool(state.get("has_issue", False)),
                mode="with_tool",
                claim=state.get("parsed_claim"),
                evidence=evidence_to_dict(evidence) if evidence else None,
                tool_calls=list(state.get("tool_plan", [])),
                final=final_data,
                debug=debug_data,
            )

        if mode == "with_tool_react":
            react_graph_config = dict(graph_config or {})
            react_graph_config.setdefault("recursion_limit", self.react_recursion_limit)
            state = self._with_tool_react_graph.invoke(
                build_react_input_messages(resolved_image_path),
                config=react_graph_config,
            )
            parsed = extract_react_output_json(state)
            final_text = extract_final_ai_message_text(state)
            structured = state.get("structured_response")
            allowed_tool_names = {
                tool_def["name"] for tool_def in self.tools.available_tools()
            }
            called_tools = [
                name
                for name in extract_called_tools(state)
                if name in allowed_tool_names
            ]
            react_claim, react_evidence = extract_react_claim_and_evidence(state)
            structured_json = (
                coerce_structured_response_dict(structured)
                if structured is not None
                else {}
            )
            final_json = structured_json if structured_json else parsed
            final_data: dict[str, Any] = {"json": final_json}
            if include_debug:
                final_data["text"] = final_text

            debug_data: dict[str, Any] = {}
            if include_debug:
                debug_data = {
                    "tool_defs": self.tools.available_tools(),
                    "message_count": len(state.get("messages", [])),
                }
            return AgentResult(
                has_issue=bool(parsed.get("has_issue", False)),
                mode="with_tool_react",
                claim=react_claim,
                evidence=react_evidence,
                tool_calls=called_tools,
                final=final_data,
                debug=debug_data,
            )

        raise ValueError(f"Unknown mode: {mode}")
