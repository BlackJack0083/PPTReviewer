from __future__ import annotations

import copy
from typing import Any, Literal, TypedDict

from jinja2 import Template

from core import resource_manager

ScopeField = Literal["city", "block", "time_range"]
ScopeErrorType = Literal["missing", "error", "unmatch", "conflict"]

FIELD_SLOTS = {
    "city": ("Geo_City_Name",),
    "block": ("Geo_Block_Name",),
    "time_range": ("Temporal_Start_Year", "Temporal_End_Year"),
}


class ScopeIssueSpec(TypedDict):
    field: ScopeField
    scope_error_type: ScopeErrorType


class ScopeCarrier(TypedDict):
    source: str
    target: str
    element_id: str
    element: dict[str, Any]
    fields: dict[str, dict[str, Any]]


def extract_scope_carriers(yaml_data: dict[str, Any]) -> list[ScopeCarrier]:
    """Extract text sources that explicitly carry data-source scope slots.

    Args:
        yaml_data: GT or injected slide YAML with `text_binding` metadata.

    Returns:
        Source carriers keyed by `summary` / `caption[i]`; each carrier only
        includes fields actually expressed by that text element.
    """
    carriers: list[ScopeCarrier] = []
    caption_index = 0
    elements = yaml_data.get("template_slide", {}).get("elements", [])
    for element in elements:
        if not isinstance(element, dict) or element.get("type") != "textBox":
            continue
        binding = element.get("text_binding")
        if not isinstance(binding, dict):
            continue
        kind = binding.get("kind")
        if kind == "summary":
            source = "summary"
            target = "summary"
        elif kind == "caption":
            source = f"caption[{caption_index}]"
            target = "st.caption"
            caption_index += 1
        else:
            continue

        fields = {}
        slots = binding.get("slots", {})
        if not isinstance(slots, dict):
            continue
        for field, slot_names in FIELD_SLOTS.items():
            if all(_has_slot(slots, name) for name in slot_names):
                fields[field] = {
                    "slots": list(slot_names),
                    "value": _field_value(slots, field),
                }
        if fields:
            carriers.append(
                {
                    "source": source,
                    "target": target,
                    "element_id": str(element.get("id", "")),
                    "element": element,
                    "fields": fields,
                }
            )
    return carriers


def applicable_scope_issue(
    carriers: list[ScopeCarrier],
    issue: ScopeIssueSpec,
) -> bool:
    """Return whether a scope issue can be constructed on this slide."""
    carrier_count = len(_carriers_for_field(carriers, issue["field"]))
    if issue["scope_error_type"] == "conflict":
        return carrier_count >= 2
    return carrier_count >= 1


def apply_scope_issues(
    yaml_data: dict[str, Any],
    issues: list[ScopeIssueSpec],
    *,
    replacement_values: dict[ScopeField, dict[str, str]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply scope issue specs by editing text-binding slots and rerendering text.

    Args:
        yaml_data: GT slide YAML.
        issues: Desired scope issues. Each field may appear at most once.
        replacement_values: Replacement slot values for `error`, `unmatch`,
            and `conflict` issues, keyed by scope field.

    Returns:
        `(mutated_yaml, operations)` where operations record slot-level edits.

    Raises:
        ValueError: A requested issue is not constructible for the slide.
    """
    _validate_issue_set(issues)
    mutated = copy.deepcopy(yaml_data)
    carriers = extract_scope_carriers(mutated)
    operations: list[dict[str, Any]] = []
    for issue in issues:
        if not applicable_scope_issue(carriers, issue):
            raise ValueError(f"Scope issue is not applicable: {issue}")
        operations.extend(
            _apply_one_issue(
                carriers,
                issue,
                replacement_values=(replacement_values or {}).get(issue["field"], {}),
            )
        )

    for carrier in carriers:
        carrier["element"]["text"] = render_text_from_binding(carrier["element"])
    return mutated, operations


def render_text_from_binding(element: dict[str, Any]) -> str:
    """Render a text element from its current `text_binding` slot values."""
    binding = element.get("text_binding")
    if not isinstance(binding, dict):
        raise ValueError(f"text_binding missing: {element}")
    render = binding["render"]
    slots = binding["slots"]
    context = {
        name: slot["value"]
        for name, slot in slots.items()
        if name != "Chart_View_Label"
    }
    if binding["kind"] == "summary":
        template = resource_manager.get_summary_template(
            render["theme_key"],
            render["function_key"],
            render["variant_idx"],
        )
        return Template(template).render(**context)
    if binding["kind"] == "caption":
        template = resource_manager.get_caption_template(
            render["theme_key"],
            render["function_key"],
        )
        caption = Template(template).render(**context)
        return f"{caption} ({slots['Chart_View_Label']['value']})"
    raise ValueError(f"Unsupported text_binding kind: {binding['kind']}")


def resolve_scope_issues(
    yaml_data: dict[str, Any],
    *,
    valid_values: dict[ScopeField, set[str]] | None = None,
    unmatched_fields: set[ScopeField] | None = None,
) -> list[ScopeIssueSpec]:
    """Resolve candidate-level scope issues from text bindings.

    Args:
        yaml_data: Slide YAML to inspect.
        valid_values: Optional allowed values for city/block. If provided,
            values outside the set are classified as `error`.
        unmatched_fields: Optional DB-level unmatch evidence supplied by caller.

    Returns:
        One primary issue per field, using conflict > missing > error > unmatch.
    """
    carriers = extract_scope_carriers(yaml_data)
    issues: list[ScopeIssueSpec] = []
    for field in ("city", "block", "time_range"):
        field_values = [
            carrier["fields"][field]["value"]
            for carrier in carriers
            if field in carrier["fields"]
        ]
        if not field_values:
            continue
        non_empty = [value for value in field_values if _value_present(value)]
        if len({_value_key(value) for value in non_empty}) > 1:
            issues.append({"field": field, "scope_error_type": "conflict"})
            continue
        if not non_empty:
            issues.append({"field": field, "scope_error_type": "missing"})
            continue
        value = non_empty[0]
        if _invalid_value(field, value, valid_values or {}):
            issues.append({"field": field, "scope_error_type": "error"})
            continue
        if field in (unmatched_fields or set()):
            issues.append({"field": field, "scope_error_type": "unmatch"})
    return issues


def _validate_issue_set(issues: list[ScopeIssueSpec]) -> None:
    fields = [issue["field"] for issue in issues]
    if len(fields) != len(set(fields)):
        raise ValueError(f"Scope issues must use distinct fields: {issues}")


def _apply_one_issue(
    carriers: list[ScopeCarrier],
    issue: ScopeIssueSpec,
    *,
    replacement_values: dict[str, str],
) -> list[dict[str, Any]]:
    field = issue["field"]
    target_carriers = _carriers_for_field(carriers, field)
    if issue["scope_error_type"] == "conflict":
        target_carriers = target_carriers[:1]
        values = _required_replacement_values(issue, replacement_values)
    elif issue["scope_error_type"] == "missing":
        values = dict.fromkeys(FIELD_SLOTS[field], "")
    elif issue["scope_error_type"] in {"error", "unmatch"}:
        values = _required_replacement_values(issue, replacement_values)
    else:
        raise ValueError(f"Unsupported scope_error_type: {issue['scope_error_type']}")

    operations = []
    for carrier in target_carriers:
        slots = carrier["element"]["text_binding"]["slots"]
        for slot_name in FIELD_SLOTS[field]:
            before = str(slots[slot_name]["value"])
            after = str(values[slot_name])
            slots[slot_name]["value"] = after
            if before == after:
                continue
            operations.append(
                {
                    "kind": "text_slot_edit",
                    "target": carrier["target"],
                    "source": carrier["source"],
                    "element_id": carrier["element_id"],
                    "field": field,
                    "slot": slot_name,
                    "before": before,
                    "after": after,
                }
            )
        carrier["fields"][field]["value"] = _field_value(slots, field)
    return operations


def _required_replacement_values(
    issue: ScopeIssueSpec,
    values: dict[str, str],
) -> dict[str, str]:
    if not values:
        raise ValueError(f"{issue['scope_error_type']} issue requires replacement values: {issue}")
    missing_slots = [slot for slot in FIELD_SLOTS[issue["field"]] if slot not in values]
    if missing_slots:
        raise ValueError(f"Replacement values missing slots {missing_slots}: {issue}")
    return values


def _carriers_for_field(
    carriers: list[ScopeCarrier],
    field: ScopeField,
) -> list[ScopeCarrier]:
    return [carrier for carrier in carriers if field in carrier["fields"]]


def _has_slot(slots: dict[str, Any], name: str) -> bool:
    slot = slots.get(name)
    return isinstance(slot, dict) and slot.get("category") == "scope"


def _field_value(slots: dict[str, Any], field: ScopeField) -> Any:
    if field == "time_range":
        return {
            "start_year": str(slots["Temporal_Start_Year"]["value"]),
            "end_year": str(slots["Temporal_End_Year"]["value"]),
        }
    slot_name = FIELD_SLOTS[field][0]
    return str(slots[slot_name]["value"])


def _value_present(value: Any) -> bool:
    if isinstance(value, dict):
        return all(str(item).strip() for item in value.values())
    return bool(str(value).strip())


def _value_key(value: Any) -> str:
    if isinstance(value, dict):
        return "|".join(f"{key}={value[key]}" for key in sorted(value))
    return str(value)


def _invalid_value(
    field: ScopeField,
    value: Any,
    valid_values: dict[ScopeField, set[str]],
) -> bool:
    if field == "time_range":
        if not isinstance(value, dict):
            return True
        start = str(value.get("start_year", ""))
        end = str(value.get("end_year", ""))
        return not (start.isdigit() and end.isdigit()) or int(start) > int(end)
    allowed = valid_values.get(field)
    return allowed is not None and str(value) not in allowed
