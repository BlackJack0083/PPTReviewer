from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from method.tools import DataSourceQueryTool, build_data_source_query_tool
from method.utils import parse_json_object

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
DEFAULT_PROMPT_PATH = PROMPT_DIR / "data_source_validation_react_prompt.txt"


class DataSourceValidationAgent:
    """ReAct agent that validates and repairs data-source slots through client turns."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout_sec: int = 120,
        graph: Any | None = None,
        query_tool: DataSourceQueryTool | None = None,
        prompt_path: Path = DEFAULT_PROMPT_PATH,
    ) -> None:
        self.prompt = prompt_path.read_text(encoding="utf-8")
        if graph is not None:
            self.graph = graph
            return

        if model is None:
            raise ValueError("DataSourceValidationAgent requires model when graph is not provided.")

        llm = ChatOpenAI(
            model=model,
            api_key=api_key or os.getenv("DASHSCOPE_API_KEY"),
            base_url=base_url,
            timeout=timeout_sec,
            temperature=0,
        )
        self.graph = create_agent(
            model=llm,
            tools=[build_data_source_query_tool(query_tool)],
            system_prompt=self.prompt,
        )

    def run_table(self, table_index: int, table_state: dict[str, Any]) -> dict[str, Any]:
        """Validate one table's data-source slots.

        Args:
            table_index: Index of this table in `analysis_state["tables"]`.
            table_state: One table item from analysis state.

        Returns:
            JSON-compatible validation result with `status`, `slot_check_result`,
            and optional `client_request`.
        """
        user_payload = build_validation_payload(table_index, table_state)
        result = self.graph.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=json.dumps(
                            user_payload,
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                ]
            }
        )
        parsed = parse_json_object(_last_message_content(result))
        return _validate_agent_result(parsed, table_index)

    def run_with_client(
        self,
        analysis_state: dict[str, Any],
        client: Any,
        max_turns: int = 3,
    ) -> dict[str, Any]:
        """Validate data-source slots and apply client state patches until pass.

        Args:
            analysis_state: Current analysis state to validate.
            client: Client simulator or human bridge with `respond(request)`.
            max_turns: Maximum clarification turns per table.

        Returns:
            Updated analysis state and validation log.
        """
        updated_state = copy.deepcopy(analysis_state)
        validation_log: list[dict[str, Any]] = []
        detected_issues: list[dict[str, Any]] = []

        for table_index, table_state in enumerate(updated_state.get("tables", [])):
            for turn in range(1, max_turns + 1):
                result = self.run_table(table_index, table_state)
                _normalize_client_request(result)
                log_entry: dict[str, Any] = {
                    "table_index": table_index,
                    "turn": turn,
                    "validation_result": result,
                }
                if result["status"] == "pass":
                    table_state["data_source_validation"] = {
                        "status": "pass",
                        "slot_check_result": result["slot_check_result"],
                    }
                    validation_log.append(log_entry)
                    break

                request = result.get("client_request")
                if request is None:
                    raise ValueError(f"needs_client result missing client_request: {result}")
                response = client.respond(request)
                log_entry["client_response"] = response
                validation_log.append(log_entry)
                if not response or not response.get("matched"):
                    table_state["data_source_validation"] = {
                        "status": "needs_client",
                        "slot_check_result": result["slot_check_result"],
                    }
                    break

                detected_issues.append(_issue_from_validation_result(result))
                apply_state_patch(updated_state, response.get("state_patch", {}))
                table_state = updated_state["tables"][table_index]
            else:
                table_state["data_source_validation"] = {
                    "status": "max_turns_exceeded",
                }

        return {
            "analysis_state": updated_state,
            "validation_log": validation_log,
            "detected_issues": detected_issues,
        }


def build_validation_payload(
    table_index: int,
    table_state: dict[str, Any],
) -> dict[str, Any]:
    data_source = table_state.get("data_source") or {}
    filters = data_source.get("filters") or {}
    slots = {
        "table": (data_source.get("connection") or {}).get("table", ""),
        "city": filters.get("city", ""),
        "block": filters.get("block", ""),
        "start_date": filters.get("start_date", ""),
        "end_date": filters.get("end_date", ""),
    }
    return {
        "table_index": table_index,
        "caption": table_state.get("caption", ""),
        "required_slot_types": ["table", "city", "block", "start_date", "end_date"],
        "slots": slots,
    }


def apply_state_patch(state: dict[str, Any], patch: dict[str, Any]) -> None:
    """Apply a client-provided state patch in place.

    The patch format follows the table-indexed structure used by the client
    simulator:
    `{"tables": [{"index": 0, "data_source": {...}}]}`.
    """
    for table_patch in patch.get("tables", []):
        index = table_patch.get("index")
        if not isinstance(index, int):
            continue
        tables = state.get("tables", [])
        if index < 0 or index >= len(tables):
            continue
        payload = {key: value for key, value in table_patch.items() if key != "index"}
        _deep_merge(tables[index], payload)


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _last_message_content(result: dict[str, Any]) -> str:
    messages = result.get("messages", [])
    if not messages:
        raise ValueError(f"ReAct agent returned no messages: {result}")
    content = getattr(messages[-1], "content", None)
    if not isinstance(content, str):
        raise ValueError(f"ReAct final message has no text content: {messages[-1]}")
    return content


def _validate_agent_result(result: dict[str, Any], table_index: int) -> dict[str, Any]:
    status = result.get("status")
    if status not in {"pass", "needs_client"}:
        raise ValueError(f"Invalid data-source validation status: {result}")
    if result.get("table_index") != table_index:
        raise ValueError(f"Data-source validation result table_index mismatch: {result}")
    slot_results = result.get("slot_check_result")
    if not isinstance(slot_results, list):
        raise ValueError(f"slot_check_result must be a list: {result}")
    for item in slot_results:
        if not isinstance(item, dict):
            raise ValueError(f"slot_check_result items must be objects: {result}")
        if item.get("label") not in {"Missing", "Error", "Unmatch", "Correct"}:
            raise ValueError(f"Invalid slot label in validation result: {result}")
    if status == "needs_client" and not isinstance(result.get("client_request"), dict):
        raise ValueError(f"needs_client result must include client_request: {result}")
    if status == "pass":
        result["client_request"] = None
    return result


def _normalize_client_request(result: dict[str, Any]) -> None:
    if result["status"] != "needs_client":
        return
    request = result["client_request"]
    fields = _normalize_request_fields(request.get("fields", []))
    labels = {
        str(item.get("label", ""))
        for item in result.get("slot_check_result", [])
        if isinstance(item, dict)
    }
    if labels & {"Error", "Unmatch"}:
        fields = _merge_fields(fields, ["city", "block", "time_range"])
    request["fields"] = fields
    request.setdefault("targets", ["st.caption"])


def _issue_from_validation_result(result: dict[str, Any]) -> dict[str, Any]:
    request = result["client_request"]
    fields = _normalize_request_fields(request.get("fields", []))
    labels = [
        f"{item.get('slot_type')}={item.get('label')}"
        for item in result.get("slot_check_result", [])
        if isinstance(item, dict) and item.get("label") != "Correct"
    ]
    return {
        "targets": list(request.get("targets", ["st.caption"])),
        "error_types": ["scope_error"],
        "evidence": "; ".join(labels),
        "required_fields_guess": fields,
        "confidence": 0.85,
    }


def _normalize_request_fields(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError(f"client_request.fields must be a list: {value}")
    normalized: list[str] = []
    for field in value:
        name = str(field).strip()
        if name in {"start_date", "end_date"}:
            name = "time_range"
        if name and name not in normalized:
            normalized.append(name)
    return normalized


def _merge_fields(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for field in right:
        if field not in merged:
            merged.append(field)
    return merged
