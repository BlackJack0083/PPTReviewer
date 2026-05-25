from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from method.utils import Client, parse_json_object

ROLE_SET = {
    "slide-title",
    "body-text",
    "caption",
    "chart-bar",
    "chart-line",
    "chart-pie",
    "table",
}


class RoleLabeler(Protocol):
    """Assign semantic roles to parser-provided PPTX elements."""

    def label_roles(
        self,
        *,
        image_path: Path,
        observed_slide: dict[str, Any],
    ) -> list[dict[str, str]]:
        ...


class OpenAIRoleLabeler:
    """VLM role labeler over deterministic PPTX elements."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout_sec: int = 120,
        enable_thinking: bool | None = False,
    ):
        self.client = Client(
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_sec=timeout_sec,
            enable_thinking=enable_thinking,
        )

    def label_roles(
        self,
        *,
        image_path: Path,
        observed_slide: dict[str, Any],
    ) -> list[dict[str, str]]:
        prompt = build_role_labeling_prompt(observed_slide)
        content = self.client.chat(
            ROLE_LABELING_SYSTEM_PROMPT,
            prompt,
            image_path=image_path,
            response_format="json_object",
        )
        parsed = parse_json_object(content)
        roles = parsed.get("roles")
        if not isinstance(roles, list):
            raise ValueError(f"VLM role response must contain roles list: {content}")
        return validate_role_assignments(observed_slide, roles)


def build_role_labeling_prompt(observed_slide: dict[str, Any]) -> str:
    elements = []
    for element in observed_slide.get("elements", []):
        prompt_element = {
            "id": str(element.get("id")),
            "type": element.get("type"),
            "layout": element.get("layout"),
        }
        if element.get("type") == "textBox":
            prompt_element["text"] = element.get("text", "")
        else:
            prompt_element["shape_kind"] = element.get("_shape_kind") or element.get("type")
        elements.append(prompt_element)

    payload = {
        "slide_size": observed_slide.get("slide_size"),
        "elements": elements,
        "allowed_roles": sorted(ROLE_SET),
    }
    return (
        "The slide image is provided together with PPTX-extracted editable elements.\n"
        "Do not detect new elements. Assign one role to every provided element id.\n"
        "Return strict JSON only with this schema:\n"
        '{"roles":[{"id":"1","role":"slide-title"}]}\n\n'
        f"Input elements:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


ROLE_LABELING_SYSTEM_PROMPT = (
    "You are a slide role annotator. Given a rendered slide image and a list of "
    "PPTX-extracted elements, assign exactly one semantic role to each element. "
    "Use only the provided element ids and the allowed role set. Return JSON only."
)


def validate_role_assignments(
    observed_slide: dict[str, Any],
    roles: list[Any],
) -> list[dict[str, str]]:
    expected_ids = {str(element.get("id")) for element in observed_slide.get("elements", [])}
    assignments: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in roles:
        if not isinstance(item, dict):
            raise ValueError(f"Role assignment must be an object: {item}")
        element_id = str(item.get("id", "")).strip()
        role = str(item.get("role", "")).strip()
        if element_id not in expected_ids:
            raise ValueError(f"Unknown element id in role assignment: {element_id}")
        if element_id in seen:
            raise ValueError(f"Duplicate role assignment for element id: {element_id}")
        if role not in ROLE_SET:
            raise ValueError(f"Unsupported role '{role}' for element id {element_id}")
        assignments.append({"id": element_id, "role": role})
        seen.add(element_id)

    missing = expected_ids - seen
    if missing:
        raise ValueError(f"Missing role assignments for element ids: {sorted(missing)}")
    return assignments


def apply_role_assignments(
    observed_slide: dict[str, Any],
    roles: list[dict[str, str]],
) -> dict[str, Any]:
    role_by_id = {item["id"]: item["role"] for item in roles}
    elements = []
    for element in observed_slide.get("elements", []):
        clean_element = {
            key: value for key, value in element.items() if not str(key).startswith("_")
        }
        clean_element["role"] = role_by_id[str(element.get("id"))]
        elements.append(clean_element)
    return {
        "slide_size": observed_slide.get("slide_size", {}),
        "elements": elements,
    }
