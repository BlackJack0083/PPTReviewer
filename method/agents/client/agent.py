from __future__ import annotations

from typing import Any


class ClientAgent:
    """由 case-local feedback items 驱动的共享 benchmark client。"""

    def __init__(self, *, feedback_items: list[dict[str, Any]]):
        self.feedback_items = [_normalize_feedback_item(item) for item in feedback_items]
        self._used_keys: set[str] = set()

    @classmethod
    def from_feedback_episode(cls, episode: dict[str, Any]) -> ClientAgent:
        """从单个 `feedback_episode.json` payload 构造 client。

        Args:
            episode: case-local feedback episode。它只对 simulated client
                可见，不对 reviewing agents 可见。

        Returns:
            只响应 injected error points 显式澄清/确认请求的共享 client。
        """
        items = episode.get("feedback_items")
        if not isinstance(items, list):
            raise ValueError(f"feedback_episode must contain feedback_items list: {episode}")
        return cls(feedback_items=items)

    def respond(self, request: dict[str, Any]) -> dict[str, Any]:
        """响应 agent 发出的澄清或确认请求。

        Args:
            request: 请求对象，包含内部路由用的 `request_type`，以及用于
                匹配 feedback item 的 `field` 和 `target`。

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
        return {"response": item["response"]}

    def _find_feedback_item(
        self,
        request: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        request_type = str(request["request_type"])
        request_field = _normalize_string(request.get("field"))
        request_target = _normalize_string(request.get("target"))
        request_scope_error_type = _normalize_string(request.get("scope_error_type"))

        for index, item in enumerate(self.feedback_items):
            if item["request_type"] != request_type:
                continue
            if item["field"] != request_field:
                continue
            if item["target"] != request_target:
                continue
            if item["scope_error_type"] != request_scope_error_type:
                continue
            key = _feedback_key(index, item)
            if key in self._used_keys:
                continue
            return item, key
        return None, None


def _normalize_feedback_item(item: dict[str, Any]) -> dict[str, Any]:
    request_type = item.get("request_type")
    if not isinstance(request_type, str) or not request_type.strip():
        raise ValueError(f"feedback item must include request_type: {item}")
    normalized = dict(item)
    normalized["request_type"] = request_type.strip()
    normalized["field"] = _normalize_string(item.get("field"))
    normalized["target"] = _normalize_string(item.get("target"))
    normalized["scope_error_type"] = _normalize_string(item.get("scope_error_type"))
    response = item.get("response")
    if not isinstance(response, str) or not response.strip():
        raise ValueError(f"feedback item must include non-empty response: {item}")
    normalized["response"] = response.strip()
    return normalized


def _normalize_string(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"Expected string, got {value}")
    return value.strip()


def _feedback_key(index: int, item: dict[str, Any]) -> str:
    target = item["target"] or "any"
    scope_error_type = item["scope_error_type"] or "any"
    return (
        f"{index}:{item['request_type']}:field={item['field']}:"
        f"target={target}:scope_error_type={scope_error_type}"
    )
