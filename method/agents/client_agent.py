from __future__ import annotations

from typing import Any


class ClientAgent:
    """Shared benchmark client backed by case-local feedback items."""

    def __init__(self, *, feedback_items: list[dict[str, Any]]):
        self.feedback_items = [_normalize_feedback_item(item) for item in feedback_items]
        self._used_keys: set[str] = set()

    @classmethod
    def from_feedback_episode(cls, episode: dict[str, Any]) -> ClientAgent:
        """Build a client from one `feedback_episode.json` payload.

        Args:
            episode: Case-local feedback episode. It is only available to the
                simulated client, not to the reviewing agents.

        Returns:
            A shared client that answers explicit clarification/confirmation
            requests for injected error points only.
        """
        items = episode.get("feedback_items")
        if not isinstance(items, list):
            raise ValueError(f"feedback_episode must contain feedback_items list: {episode}")
        return cls(feedback_items=items)

    def respond(self, request: dict[str, Any]) -> dict[str, Any]:
        """Answer a clarification or confirmation request from an agent.

        Args:
            request: Request object with `request_type`, and optional
                `table_index`, `fields`, and `targets`.

        Returns:
            A compact response. `matched=false` means this request did not hit
            an injected error point in the feedback episode.
        """
        request_type = request.get("request_type")
        if not isinstance(request_type, str) or not request_type.strip():
            raise ValueError(f"Client request must include request_type: {request}")

        item, key = self._find_feedback_item(request)
        if item is None or key is None:
            return {
                "matched": False,
                "feedback_key": None,
                "state_patch": {},
            }

        self._used_keys.add(key)
        response: dict[str, Any] = {
            "matched": True,
            "feedback_key": key,
            "state_patch": item.get("state_patch", {}),
        }
        if "decision" in item:
            response["decision"] = item["decision"]
        return response

    def _find_feedback_item(
        self,
        request: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        request_type = str(request["request_type"])
        request_fields = _normalize_fields(request.get("fields", []))
        request_targets = _normalize_strings(request.get("targets", []))
        request_table_index = request.get("table_index")

        for index, item in enumerate(self.feedback_items):
            if item["request_type"] != request_type:
                continue
            if not _table_index_matches(item, request_table_index):
                continue
            if not item["fields"].issubset(request_fields):
                continue
            if item["targets"] and request_targets and not item["targets"].issubset(
                request_targets
            ):
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
    normalized["fields"] = _normalize_fields(item.get("fields", []))
    normalized["targets"] = _normalize_strings(item.get("targets", []))
    return normalized


def _normalize_fields(value: Any) -> set[str]:
    fields = _normalize_strings(value)
    if "start_date" in fields or "end_date" in fields:
        fields.add("time_range")
    return fields


def _normalize_strings(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if not isinstance(value, list):
        raise ValueError(f"Expected string list, got {value}")
    return {str(item).strip() for item in value if str(item).strip()}


def _table_index_matches(item: dict[str, Any], request_table_index: Any) -> bool:
    item_table_index = item.get("table_index")
    if item_table_index is None or request_table_index is None:
        return True
    return item_table_index == request_table_index


def _feedback_key(index: int, item: dict[str, Any]) -> str:
    table_index = item.get("table_index", "any")
    fields = ",".join(sorted(item["fields"]))
    targets = ",".join(sorted(item["targets"])) or "any"
    return f"{index}:{item['request_type']}:table={table_index}:fields={fields}:targets={targets}"
