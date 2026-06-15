from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from method.utils import Client, parse_json_object

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
DEFAULT_PROMPT_PATH = PROMPT_DIR / "client_simulation_prompt.txt"


class ClientAgent:
    """由 case-local feedback items 驱动的共享 benchmark client。

    Args:
        feedback_items: 当前 case 的私有 feedback items。
        mode: `deterministic` 直接返回 feedback response；`llm` 先确定性匹配
            feedback item，再用 LLM 改写成更自然的客户回复。
        client: 可选的 project-local `.chat(...)` client，主要用于测试。
        model: LLM client 使用的模型名。`mode="llm"` 且未传 `client` 时必填。
        api_key: LLM API key。
        base_url: OpenAI-compatible API base URL。
        timeout_sec: LLM 请求超时时间。
    """

    def __init__(
        self,
        *,
        feedback_items: list[dict[str, Any]],
        mode: Literal["deterministic", "llm"] = "deterministic",
        client: Any | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout_sec: int = 120,
    ):
        if mode not in {"deterministic", "llm"}:
            raise ValueError(f"Unsupported client mode: {mode}")
        self.feedback_items = [_normalize_feedback_item(item) for item in feedback_items]
        self._used_keys: set[str] = set()
        self.mode = mode
        self.prompt = DEFAULT_PROMPT_PATH.read_text(encoding="utf-8")
        self.client = client
        if self.mode == "llm" and self.client is None:
            if not model:
                raise ValueError("ClientAgent mode='llm' requires model when client is not provided.")
            self.client = Client(
                model=model,
                api_key=api_key,
                base_url=base_url,
                timeout_sec=timeout_sec,
            )

    @classmethod
    def from_feedback_episode(
        cls,
        episode: dict[str, Any],
        **kwargs: Any,
    ) -> ClientAgent:
        """从单个 `feedback_episode.json` payload 构造 client。

        Args:
            episode: case-local feedback episode。它只对 simulated client
                可见，不对 reviewing agents 可见。
            **kwargs: 透传给 `ClientAgent(...)`，用于配置 deterministic/llm
                client 模式。

        Returns:
            只响应 injected error points 显式澄清/确认请求的共享 client。
        """
        items = episode.get("feedback_items")
        if not isinstance(items, list):
            raise ValueError(f"feedback_episode must contain feedback_items list: {episode}")
        return cls(feedback_items=items, **kwargs)

    def respond(self, request: dict[str, Any]) -> dict[str, Any]:
        """响应 agent 发出的澄清或确认请求。

        Args:
            request: 请求对象，包含内部路由用的 `request_type`。Data-source
                请求按 `field` 和 `scope_error_type` 匹配；content update 请求
                按 `error_type` 和 `target` 匹配。

        Returns:
            client 回复。agent 可见的澄清和确认请求只返回客户式 `response`。
        """
        request_type = request.get("request_type")
        if not isinstance(request_type, str) or not request_type.strip():
            raise ValueError(f"Client request must include request_type: {request}")

        item, key = self._find_feedback_item(request)
        if item is None or key is None:
            return {"response": "I do not have a confirmed correction for this request."}

        self._used_keys.add(key)
        if self.mode == "deterministic":
            return {"response": item["response"]}
        return self._llm_response(request=request, item=item)

    def _find_feedback_item(
        self,
        request: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        request_type = str(request["request_type"])

        for index, item in enumerate(self.feedback_items):
            if item["request_type"] != request_type:
                continue
            if not _matches_feedback_item(item, request):
                continue
            key = _feedback_key(index, item)
            if key in self._used_keys:
                continue
            return item, key
        return None, None

    def _llm_response(
        self,
        *,
        request: dict[str, Any],
        item: dict[str, Any],
    ) -> dict[str, str]:
        payload = {
            "request": request,
            "matched_feedback": {
                "response": item["response"],
            },
        }
        content = self.client.chat(
            self.prompt,
            json.dumps(payload, ensure_ascii=False, indent=2),
            temperature=0.3,
            max_tokens=512,
            response_format="json_object",
        )
        parsed = parse_json_object(content)
        if set(parsed) != {"response"} or not isinstance(parsed["response"], str):
            raise ValueError(f"Client simulator must return only response: {parsed}")
        response = parsed["response"].strip()
        if not response:
            raise ValueError(f"Client simulator returned empty response: {parsed}")
        return {"response": response}


def _normalize_feedback_item(item: dict[str, Any]) -> dict[str, Any]:
    request_type = _required_text(item, "request_type")
    normalized = {
        "request_type": request_type,
        "response": _required_text(item, "response"),
    }
    if request_type == "data_source_slot_clarification":
        normalized["field"] = _required_text(item, "field")
        normalized["scope_error_type"] = _required_text(item, "scope_error_type")
        normalized["target"] = _optional_text(item, "target")
        return normalized
    if request_type == "content_update_confirmation":
        normalized["error_type"] = _required_text(item, "error_type")
        normalized["target"] = _required_text(item, "target")
        return normalized
    raise ValueError(f"Unsupported feedback request_type: {item}")


def _matches_feedback_item(item: dict[str, Any], request: dict[str, Any]) -> bool:
    request_type = item["request_type"]
    if request_type == "data_source_slot_clarification":
        return (
            item["field"] == request.get("field")
            and item["scope_error_type"] == request.get("scope_error_type")
            and (not item["target"] or item["target"] == request.get("target"))
        )
    if request_type == "content_update_confirmation":
        return (
            item["error_type"] == request.get("error_type")
            and item["target"] == request.get("target")
        )
    return False


def _required_text(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"feedback item must include non-empty {key}: {item}")
    return value.strip()


def _optional_text(item: dict[str, Any], key: str) -> str:
    value = item.get(key, "")
    if value == "":
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"feedback item {key} must be a string when provided: {item}")
    return value.strip()


def _feedback_key(index: int, item: dict[str, Any]) -> str:
    target = item.get("target") or "any"
    field = item.get("field") or "any"
    error_type = item.get("error_type") or "any"
    scope_error_type = item.get("scope_error_type") or "any"
    return (
        f"{index}:{item['request_type']}:error_type={error_type}:"
        f"field={field}:target={target}:scope_error_type={scope_error_type}"
    )
