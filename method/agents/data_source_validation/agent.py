"""数据源验证 agent。

该 agent 负责 scope 验证闭环：
1. 聚合 summary 和 caption 中的 data-source 描述。
2. 让 ReAct LLM 调用 `data_source_query_tool` 验证最终 slots。
3. 只在 slot 缺失、冲突或无效时向 client 请求确认。
4. 将 client 返回的 patch 合并到 `analysis_state["final_data_source"]`。
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from method.utils import parse_json_object

from .tools import DataSourceQueryTool, build_data_source_query_tool

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
DEFAULT_PROMPT_PATH = PROMPT_DIR / "data_source_validation_react_prompt.txt"


class DataSourceValidationAgent:
    """通过 ReAct 和 client 多轮交互验证、修正 data-source slots。"""

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
        """初始化数据源验证 agent。

        Args:
            model: OpenAI-compatible chat model 名称。未注入 `graph` 时必填。
            api_key: OpenAI-compatible endpoint 的 API key。
            base_url: OpenAI-compatible endpoint 的 base URL。
            timeout_sec: LLM 请求超时时间，单位为秒。
            graph: 可选的预构建 LangChain agent graph，主要用于测试。
            query_tool: 可选的数据库查询工具 runner，主要用于测试。
            prompt_path: ReAct 验证 system prompt 路径。

        异常:
            ValueError: 未注入 `graph` 且未提供 `model`。
        """
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

    def run_final_source(self, data_source: dict[str, Any]) -> dict[str, Any]:
        """验证 slide 级别的最终 data-source slots。

        Args:
            data_source: 包含 connection 和 filters 的 slide 级 data source。

        Returns:
            JSON-compatible 验证结果，包含 `status`、`slot_check_result`，
            以及可选的 `client_request`。
        """
        user_payload = build_validation_payload(data_source)
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
        return _validate_agent_result(parsed)

    def run_with_client(
        self,
        analysis_state: dict[str, Any],
        client: Any,
        max_turns: int = 3,
    ) -> dict[str, Any]:
        """验证 data-source slots，并持续合并 client patch 直到通过或停止。

        Args:
            analysis_state: 当前待验证的 analysis state。
            client: 具备 `respond(request)` 的 client simulator 或人工桥接对象。
            max_turns: 最大澄清轮数。

        Returns:
            包含更新后 `analysis_state`、验证日志和检测问题的字典。
        """
        updated_state = copy.deepcopy(analysis_state)
        validation_log: list[dict[str, Any]] = []
        detected_issues: list[dict[str, Any]] = []

        for turn in range(1, max_turns + 1):
            # final source 始终是 slide 级单一对象。caption 和 summary 只是
            # 证据来源，不是相互独立的执行状态。
            aggregation = aggregate_final_data_source(updated_state)
            updated_state["final_data_source"] = aggregation["final_data_source"]
            if aggregation["conflicts"]:
                # slide 内部描述冲突不需要查数据库；必须由 client 确认真实意图。
                result = _conflict_validation_result(aggregation["conflicts"])
            else:
                result = self.run_final_source(updated_state["final_data_source"])
                _normalize_client_request(result)

            log_entry: dict[str, Any] = {
                "turn": turn,
                "final_data_source": copy.deepcopy(updated_state["final_data_source"]),
                "validation_result": result,
            }
            if result["status"] == "pass":
                updated_state["data_source_validation"] = {
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
                updated_state["data_source_validation"] = {
                    "status": "needs_client",
                    "slot_check_result": result["slot_check_result"],
                }
                break

            detected_issues.append(_issue_from_validation_result(result))
            # data-source feedback 刻意保持窄口径：只能 patch slide 级
            # final_data_source，然后重新进入验证循环。
            apply_state_patch(updated_state, response.get("state_patch", {}))
        else:
            updated_state["data_source_validation"] = {
                "status": "max_turns_exceeded",
            }

        return {
            "analysis_state": updated_state,
            "validation_log": validation_log,
            "detected_issues": detected_issues,
        }


def build_validation_payload(
    data_source: dict[str, Any],
) -> dict[str, Any]:
    """把最终 data-source state 转成 ReAct prompt payload。

    Args:
        data_source: 包含 `connection` 和 `filters` 的 slide 级最终 data source。

    Returns:
        包含 required slots 的 JSON-serializable payload。
    """
    filters = data_source.get("filters") or {}
    slots = {
        "table": (data_source.get("connection") or {}).get("table", ""),
        "city": filters.get("city", ""),
        "block": filters.get("block", ""),
        "start_date": filters.get("start_date", ""),
        "end_date": filters.get("end_date", ""),
    }
    return {
        "table_index": 0,
        "required_slot_types": ["table", "city", "block", "start_date", "end_date"],
        "slots": slots,
    }


def apply_state_patch(state: dict[str, Any], patch: dict[str, Any]) -> None:
    """原地应用 client 返回的 state patch。

    data-source 澄清只允许写入 slide 级 `final_data_source`。
    """
    if not patch:
        return
    unexpected_keys = set(patch) - {"final_data_source"}
    if unexpected_keys:
        raise ValueError(f"Data-source patch only supports final_data_source: {patch}")
    final_patch = patch.get("final_data_source")
    if not isinstance(final_patch, dict):
        raise ValueError(f"final_data_source patch must be an object: {patch}")
    state.setdefault("final_data_source", _empty_data_source())
    _deep_merge(state["final_data_source"], final_patch)


def aggregate_final_data_source(state: dict[str, Any]) -> dict[str, Any]:
    """把 summary 和 caption 的 data source 聚合成一个 slide 级 source。

    Args:
        state: 当前 analysis state。它可能已经包含前几轮 client 修正过的
            `final_data_source`。

    Returns:
        包含 `final_data_source` 和 `conflicts` 的字典。`conflicts` 表示多个
        可见元素对同一个 slot 给出了不同非空值，且尚无 client 确认的最终值。
    """
    final_data_source = _normalize_data_source(state.get("final_data_source"))
    candidates_by_slot: dict[str, list[dict[str, str]]] = {
        "table": [],
        "city": [],
        "block": [],
        "start_date": [],
        "end_date": [],
    }
    for source_name, data_source in _iter_data_source_candidates(state):
        for slot, value in _slots_from_data_source(data_source).items():
            if value:
                candidates_by_slot[slot].append({"source": source_name, "value": value})

    conflicts: list[dict[str, Any]] = []
    for slot, candidates in candidates_by_slot.items():
        if _slot_value(final_data_source, slot):
            continue
        unique_values = _unique_values(candidates)
        if len(unique_values) == 1:
            _set_slot_value(final_data_source, slot, unique_values[0])
        elif len(unique_values) > 1:
            conflicts.append(
                {
                    "slot_type": _request_field_for_slot(slot),
                    "slot": slot,
                    "candidates": candidates,
                }
            )

    return {"final_data_source": final_data_source, "conflicts": conflicts}


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _empty_data_source() -> dict[str, Any]:
    return {
        "connection": {"table": ""},
        "filters": {
            "city": "",
            "block": "",
            "start_date": "",
            "end_date": "",
        },
    }


def _normalize_data_source(value: Any) -> dict[str, Any]:
    normalized = _empty_data_source()
    if not isinstance(value, dict):
        return normalized
    connection = value.get("connection")
    if isinstance(connection, dict) and isinstance(connection.get("table"), str):
        normalized["connection"]["table"] = connection["table"]
    filters = value.get("filters")
    if isinstance(filters, dict):
        for key in ("city", "block", "start_date", "end_date"):
            if isinstance(filters.get(key), str):
                normalized["filters"][key] = filters[key]
    return normalized


def _iter_data_source_candidates(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    summary = state.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("data_source"), dict):
        candidates.append(("summary", summary["data_source"]))
    for table_index, table in enumerate(state.get("tables", [])):
        if not isinstance(table, dict):
            continue
        caption = table.get("caption")
        if isinstance(caption, dict) and isinstance(caption.get("data_source"), dict):
            candidates.append((f"st.caption[{table_index}]", caption["data_source"]))
    return candidates


def _slots_from_data_source(data_source: dict[str, Any]) -> dict[str, str]:
    filters = data_source.get("filters") or {}
    connection = data_source.get("connection") or {}
    return {
        "table": str(connection.get("table", "")),
        "city": str(filters.get("city", "")),
        "block": str(filters.get("block", "")),
        "start_date": str(filters.get("start_date", "")),
        "end_date": str(filters.get("end_date", "")),
    }


def _slot_value(data_source: dict[str, Any], slot: str) -> str:
    if slot == "table":
        return str((data_source.get("connection") or {}).get("table", ""))
    return str((data_source.get("filters") or {}).get(slot, ""))


def _set_slot_value(data_source: dict[str, Any], slot: str, value: str) -> None:
    if slot == "table":
        data_source["connection"]["table"] = value
    else:
        data_source["filters"][slot] = value


def _unique_values(candidates: list[dict[str, str]]) -> list[str]:
    values: list[str] = []
    for candidate in candidates:
        value = candidate["value"]
        if value and value not in values:
            values.append(value)
    return values


def _conflict_validation_result(conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    fields = _merge_fields(
        [],
        [_request_field_for_slot(conflict["slot"]) for conflict in conflicts],
    )
    conflict_slots = {conflict["slot"] for conflict in conflicts}
    slot_check_result = [
        {
            "slot": _conflict_slot_text(conflicts, "table"),
            "slot_type": "table",
            "label": "Error" if "table" in conflict_slots else "Correct",
        },
        {
            "slot": _conflict_slot_text(conflicts, "city"),
            "slot_type": "city",
            "label": "Error" if "city" in conflict_slots else "Correct",
        },
        {
            "slot": _conflict_slot_text(conflicts, "block"),
            "slot_type": "block",
            "label": "Error" if "block" in conflict_slots else "Correct",
        },
        {
            "slot": _conflict_slot_text(conflicts, "start_date")
            or _conflict_slot_text(conflicts, "end_date"),
            "slot_type": "time_range",
            "label": "Error"
            if {"start_date", "end_date"} & conflict_slots
            else "Correct",
        },
    ]
    return {
        "status": "needs_client",
        "table_index": 0,
        "slot_check_result": slot_check_result,
        "client_request": {
            "request_type": "data_source_slot_clarification",
            "table_index": 0,
            "targets": _conflict_targets(conflicts),
            "fields": fields,
            "description": _conflict_description(conflicts),
        },
    }


def _request_field_for_slot(slot: str) -> str:
    if slot in {"start_date", "end_date"}:
        return "time_range"
    return slot


def _conflict_slot_text(conflicts: list[dict[str, Any]], slot: str) -> str:
    values: list[str] = []
    for conflict in conflicts:
        if conflict["slot"] != slot:
            continue
        for candidate in conflict["candidates"]:
            text = f"{candidate['source']}={candidate['value']}"
            if text not in values:
                values.append(text)
    return "; ".join(values)


def _conflict_targets(conflicts: list[dict[str, Any]]) -> list[str]:
    targets: list[str] = []
    for conflict in conflicts:
        for candidate in conflict["candidates"]:
            target = "st.caption" if candidate["source"].startswith("st.caption") else "summary"
            if target not in targets:
                targets.append(target)
    return targets


def _conflict_description(conflicts: list[dict[str, Any]]) -> str:
    parts = []
    for conflict in conflicts:
        values = ", ".join(
            f"{candidate['source']} says {candidate['value']}"
            for candidate in conflict["candidates"]
        )
        parts.append(f"{conflict['slot']} has inconsistent descriptions: {values}.")
    return " ".join(parts)


def _last_message_content(result: dict[str, Any]) -> str:
    messages = result.get("messages", [])
    if not messages:
        raise ValueError(f"ReAct agent returned no messages: {result}")
    content = getattr(messages[-1], "content", None)
    if not isinstance(content, str):
        raise ValueError(f"ReAct final message has no text content: {messages[-1]}")
    return content


def _validate_agent_result(result: dict[str, Any]) -> dict[str, Any]:
    status = result.get("status")
    if status not in {"pass", "needs_client"}:
        raise ValueError(f"Invalid data-source validation status: {result}")
    if result.get("table_index") != 0:
        raise ValueError(f"Data-source validation result table_index must be 0: {result}")
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
