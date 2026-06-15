from __future__ import annotations

import copy
import hashlib
import itertools
import random
from pathlib import Path
from typing import Any

from engine.data_files import (
    data_elements,
    read_dataframe_csv,
    resolve_element_data_path,
)

from .common import (
    load_ground_truth_blocks,
    load_yaml,
    mutate_number,
    parse_number,
    scalar_to_json,
)
from .scope import (
    ScopeIssueSpec,
    applicable_scope_issue,
    apply_scope_issues,
    extract_scope_carriers,
    render_text_from_binding,
)

SUPPORTED_FAMILIES = {"scope", "value", "claim"}
CITY_NAMES = ("Beijing", "Guangzhou", "Shenzhen")
PRESENTATION_LABELS = ("Bar chart", "Line chart", "Pie chart", "Table")
CLAIM_REPLACEMENTS = {
    "an increase": "a decrease",
    "a decrease": "an increase",
    "buyer-favorable": "seller-favorable",
    "seller-favorable": "buyer-favorable",
    "increase": "decrease",
    "decrease": "increase",
    "increased": "decreased",
    "decreased": "increased",
    "upward": "downward",
    "downward": "upward",
}


def mutation_signature(operations: list[dict[str, Any]]) -> tuple[str, ...]:
    """Return the case-level atomic mutation signature.

    Args:
        operations: Corruption operations generated for one injected sample.

    Returns:
        Sorted unique mutation types, so multi-slot edits for one logical error
        count as one case type.
    """
    return tuple(sorted({str(operation["mutation_type"]) for operation in operations}))


def build_corruption(
    dataset_root: Path,
    sample_row: dict[str, Any],
    family: str,
    seed: int,
    *,
    max_slots_per_sample: int = 1,
    disallow_signatures: set[tuple[str, ...]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    """Build one injected YAML payload for the agreed error schema.

    Args:
        dataset_root: Benchmark dataset root.
        sample_row: Manifest row pointing to a GT slide YAML.
        family: One of `scope`, `value`, or `claim`.
        seed: Random seed for deterministic corruption selection.
        max_slots_per_sample: Maximum number of atomic scope fields to combine.
            Value and claim mutations currently generate one atomic issue per case.
        disallow_signatures: Case signatures that should not be regenerated for
            the same sample/family.

    Returns:
        `(mutated_yaml, corruption_metadata, artifact_id)`, or `None` if the
        requested family is not constructible for this sample.

    Raises:
        ValueError: `family` is outside the new schema.
    """
    if family not in SUPPORTED_FAMILIES:
        raise ValueError(f"Unsupported error family: {family}")

    source_yaml = dataset_root / sample_row["gt_yaml"]
    if not source_yaml.exists():
        return None

    base_data = load_yaml(source_yaml)
    rng = random.Random(seed)  # noqa: S311
    blocked = disallow_signatures or set()
    builders = {
        "scope": mutate_scope,
        "value": mutate_value,
        "claim": mutate_claim,
    }

    for _ in range(24):
        data = copy.deepcopy(base_data)
        data["_source_yaml_path"] = str(source_yaml)
        result = builders[family](
            data,
            rng,
            max_slots_per_sample=max_slots_per_sample,
            disallow_signatures=blocked,
        )
        if result is None:
            continue
        mutated, operations = result
        signature = mutation_signature(operations)
        if signature in blocked:
            continue

        sample_id = str(sample_row["sample_id"])
        raw_id = f"{sample_id}|{family}|{seed}|{signature}"
        artifact_id = f"{sample_id}-{family}-{hashlib.md5(raw_id.encode()).hexdigest()[:8]}"  # noqa: S324
        corruption = {
            "operations": operations,
            "expected_repair_yaml": sample_row["gt_yaml"],
        }
        return mutated, corruption, artifact_id
    return None


def build_recipe_corruption(
    dataset_root: Path,
    sample_row: dict[str, Any],
    recipe: dict[str, Any],
    seed: int,
    *,
    disallow_signatures: set[tuple[str, ...]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    """Build one injected YAML payload from a multi-family recipe.

    Args:
        dataset_root: Benchmark dataset root.
        sample_row: Manifest row pointing to a GT slide YAML.
        recipe: Error recipe with an ordered `recipe` step list.
        seed: Random seed for deterministic corruption selection.
        disallow_signatures: Case signatures that should not be regenerated for
            the same sample/recipe.

    Returns:
        `(mutated_yaml, corruption_metadata, artifact_id)`, or `None` if every
        required step cannot be applied to this sample.
    """
    source_yaml = dataset_root / sample_row["gt_yaml"]
    if not source_yaml.exists():
        return None

    steps = recipe_steps(recipe)
    rng = random.Random(seed)  # noqa: S311
    blocked = disallow_signatures or set()
    builders = {
        "scope": mutate_scope,
        "value": mutate_value,
        "claim": mutate_claim,
    }

    for _ in range(24):
        data = copy.deepcopy(load_yaml(source_yaml))
        data["_source_yaml_path"] = str(source_yaml)
        operations: list[dict[str, Any]] = []
        local_blocked: set[tuple[str, ...]] = set()
        failed = False
        for step in steps:
            family = step["family"]
            num_errors = step["num_errors"]
            for _attempt_index in range(num_errors):
                result = builders[family](
                    data,
                    rng,
                    max_slots_per_sample=num_errors if family == "scope" else 1,
                    disallow_signatures=blocked | local_blocked,
                )
                if result is None:
                    failed = True
                    break
                data, step_operations = result
                operations.extend(step_operations)
                step_signature = mutation_signature(step_operations)
                local_blocked.add(step_signature)
                if family == "scope":
                    break
            if failed:
                break
        if failed:
            continue

        signature = mutation_signature(operations)
        if signature in blocked:
            continue

        label = recipe_label(recipe)
        sample_id = str(sample_row["sample_id"])
        raw_id = f"{sample_id}|{label}|{seed}|{signature}"
        artifact_id = f"{sample_id}-{label}-{hashlib.md5(raw_id.encode()).hexdigest()[:8]}"  # noqa: S324
        corruption = {
            "recipe": steps,
            "operations": operations,
            "expected_repair_yaml": sample_row["gt_yaml"],
        }
        return data, corruption, artifact_id
    return None


def recipe_steps(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    """Return validated ordered recipe steps."""
    raw_steps = recipe.get("recipe")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError(f"Recipe must include a non-empty recipe list: {recipe}")

    steps: list[dict[str, Any]] = []
    for step in raw_steps:
        if not isinstance(step, dict):
            raise ValueError(f"Recipe step must be an object: {recipe}")
        family = step.get("family")
        num_errors = step.get("num_errors")
        if family not in SUPPORTED_FAMILIES:
            raise ValueError(f"Unsupported recipe family: {step}")
        if not isinstance(num_errors, int) or num_errors <= 0:
            raise ValueError(f"Recipe step num_errors must be positive: {step}")
        steps.append({"family": family, "num_errors": num_errors})
    return steps


def recipe_label(recipe: dict[str, Any]) -> str:
    """Return a stable name derived from the recipe list."""
    return "-".join(
        f"{step['family']}{step['num_errors']}" for step in recipe_steps(recipe)
    )


def mutate_scope(
    data: dict[str, Any],
    rng: random.Random,
    *,
    max_slots_per_sample: int = 1,
    disallow_signatures: set[tuple[str, ...]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Construct scope slot errors from declared text bindings."""
    carriers = extract_scope_carriers(data)
    issue_candidates = [
        issue
        for issue in _scope_issue_candidates(data)
        if applicable_scope_issue(carriers, issue)
    ]
    issues = _choose_scope_issue_bundle(
        issue_candidates,
        max_slots_per_sample=max_slots_per_sample,
        rng=rng,
        disallow_signatures=disallow_signatures or set(),
    )
    if not issues:
        return None

    replacement_values = {
        issue["field"]: values
        for issue in issues
        if (values := _scope_replacement_values(data, issue, rng))
    }
    mutated, operations = apply_scope_issues(
        data,
        issues,
        replacement_values=replacement_values,
    )
    mutation_by_field = {
        issue["field"]: f"scope_{issue['field']}_{issue['scope_error_type']}"
        for issue in issues
    }
    scope_type_by_field = {
        issue["field"]: issue["scope_error_type"]
        for issue in issues
    }
    for operation in operations:
        field = operation["field"]
        operation["mutation_type"] = mutation_by_field[field]
        operation["scope_error_type"] = scope_type_by_field[field]
        operation["semantic_slot"] = operation["slot"]
        operation["error_types"] = ["scope_error"]
    return mutated, operations


def mutate_value(
    data: dict[str, Any],
    rng: random.Random,
    *,
    max_slots_per_sample: int = 1,
    disallow_signatures: set[tuple[str, ...]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Construct one value error in the body data or summary text."""
    del max_slots_per_sample
    candidates = []
    blocked = disallow_signatures or set()
    if ("value_table_cell",) not in blocked:
        candidates.append(_mutate_table_cell)
    if ("value_summary_slot",) not in blocked:
        candidates.append(_mutate_summary_value_slot)
    rng.shuffle(candidates)
    for candidate in candidates:
        result = candidate(data, rng)
        if result is not None:
            return result
    return None


def mutate_claim(
    data: dict[str, Any],
    rng: random.Random,
    *,
    max_slots_per_sample: int = 1,
    disallow_signatures: set[tuple[str, ...]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Construct one claim error in caption or summary text."""
    del max_slots_per_sample
    candidates = []
    blocked = disallow_signatures or set()
    if ("claim_caption_presentation",) not in blocked:
        candidates.append(_mutate_caption_presentation)
    if ("claim_summary_slot",) not in blocked:
        candidates.append(_mutate_summary_claim_slot)
    rng.shuffle(candidates)
    for candidate in candidates:
        result = candidate(data, rng)
        if result is not None:
            return result
    return None


def _scope_issue_candidates(data: dict[str, Any]) -> list[ScopeIssueSpec]:
    carriers = extract_scope_carriers(data)
    candidates: list[ScopeIssueSpec] = []
    for field in ("city", "block", "time_range"):
        if not any(field in carrier["fields"] for carrier in carriers):
            continue
        for scope_error_type in ("missing", "error", "conflict"):
            candidates.append({"field": field, "scope_error_type": scope_error_type})
        if field in {"city", "block"} and any(
            field in carrier["fields"]
            and "city" in carrier["fields"]
            and "block" in carrier["fields"]
            for carrier in carriers
        ):
            candidates.append({"field": field, "scope_error_type": "unmatch"})
    return candidates


def _choose_scope_issue_bundle(
    candidates: list[ScopeIssueSpec],
    *,
    max_slots_per_sample: int,
    rng: random.Random,
    disallow_signatures: set[tuple[str, ...]],
) -> list[ScopeIssueSpec] | None:
    upper = min(max(1, max_slots_per_sample), len(candidates))
    for size in range(upper, 0, -1):
        bundles = []
        for combo in itertools.combinations(candidates, size):
            fields = [issue["field"] for issue in combo]
            if len(set(fields)) != len(fields):
                continue
            signature = tuple(
                sorted(
                    f"scope_{issue['field']}_{issue['scope_error_type']}"
                    for issue in combo
                )
            )
            if signature in disallow_signatures:
                continue
            bundles.append(combo)
        if bundles:
            return list(rng.choice(bundles))
    return None


def _scope_replacement_values(
    data: dict[str, Any],
    issue: ScopeIssueSpec,
    rng: random.Random,
) -> dict[str, str]:
    field = issue["field"]
    scope_error_type = issue["scope_error_type"]
    if scope_error_type == "missing":
        return {}

    filters = data["query_filters"]
    city = str(filters["city"]).strip()
    block = str(filters["block"]).strip()
    if scope_error_type == "error":
        return _scope_error_values(field, filters, rng)
    if field == "city":
        return {"Geo_City_Name": _donor_city(city, rng)}
    if field == "block":
        if scope_error_type == "unmatch":
            return {"Geo_Block_Name": _donor_block_from_other_city(city, rng)}
        return {"Geo_Block_Name": _donor_block(city, block, rng)}
    if field == "time_range":
        return _conflicting_time_range(filters, rng)
    return {}


def _scope_error_values(
    field: str,
    filters: dict[str, Any],
    rng: random.Random,
) -> dict[str, str]:
    if field == "city":
        return {"Geo_City_Name": _typo(str(filters["city"]), rng)}
    if field == "block":
        return {"Geo_Block_Name": _typo(str(filters["block"]), rng)}
    if field == "time_range":
        return _invalid_time_range(filters, rng)
    return {}


def _typo(value: str, rng: random.Random) -> str:
    text = value.strip()
    if len(text) <= 2:
        return f"{text}x"
    candidates = [
        text[:index] + text[index + 1 :]
        for index, char in enumerate(text)
        if char.isalpha()
    ]
    candidates.extend(
        text[:index] + text[index + 1] + text[index] + text[index + 2 :]
        for index in range(len(text) - 1)
        if text[index].isalpha() and text[index + 1].isalpha()
    )
    candidates = [candidate for candidate in candidates if candidate and candidate != text]
    if not candidates:
        return f"{text}x"
    return rng.choice(candidates)


def _donor_city(current_city: str, rng: random.Random) -> str:
    candidates = [city for city in CITY_NAMES if city != current_city]
    if not candidates:
        raise ValueError(f"No donor city for {current_city}")
    return rng.choice(candidates)


def _donor_block(city: str, current_block: str, rng: random.Random) -> str:
    candidates = [block for block in load_ground_truth_blocks(city) if block != current_block]
    if not candidates:
        raise ValueError(f"No donor block for {city}/{current_block}")
    return rng.choice(candidates)


def _donor_block_from_other_city(current_city: str, rng: random.Random) -> str:
    donor_city = _donor_city(current_city, rng)
    candidates = list(load_ground_truth_blocks(donor_city))
    if not candidates:
        raise ValueError(f"No donor blocks for {donor_city}")
    return rng.choice(candidates)


def _invalid_time_range(
    filters: dict[str, Any],
    rng: random.Random,
) -> dict[str, str]:
    end_year = int(str(filters["end_date"])[:4])
    invalid_start = rng.randint(end_year + 1, end_year + 3)
    return {
        "Temporal_Start_Year": str(invalid_start),
        "Temporal_End_Year": str(end_year),
    }


def _conflicting_time_range(
    filters: dict[str, Any],
    rng: random.Random,
) -> dict[str, str]:
    start_year = int(str(filters["start_date"])[:4])
    end_year = int(str(filters["end_date"])[:4])
    span = max(0, end_year - start_year)
    shifted_start = max(2000, start_year + rng.choice([-2, -1, 1, 2]))
    shifted_end = shifted_start + span
    if shifted_start == start_year and shifted_end == end_year:
        shifted_start += 1
        shifted_end += 1
    return {
        "Temporal_Start_Year": str(shifted_start),
        "Temporal_End_Year": str(shifted_end),
    }


def _mutate_table_cell(
    data: dict[str, Any],
    rng: random.Random,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    source_yaml = Path(str(data["_source_yaml_path"]))
    candidates = []
    elements = data_elements(data)
    for element_index, element in enumerate(elements):
        csv_path = resolve_element_data_path(source_yaml, element)
        if "_dataframe_override" in element:
            df = element["_dataframe_override"]
        else:
            if not csv_path.exists():
                continue
            df = read_dataframe_csv(csv_path)
        for row_pos in range(df.shape[0]):
            for col_pos, column in enumerate(df.columns):
                if parse_number(df.iat[row_pos, col_pos]) is not None:
                    candidates.append((element_index, row_pos, col_pos, column, df))
    if not candidates:
        return None

    element_index, row_pos, col_pos, column, source_df = rng.choice(candidates)
    element = elements[element_index]
    df = source_df.copy()
    before = df.iat[row_pos, col_pos]
    after = mutate_number(before, rng)
    if str(after) == str(before):
        return None
    df.iat[row_pos, col_pos] = after
    element["_dataframe_override"] = df
    operation = {
        "kind": "data_cell_edit",
        "target": "st.body",
        "element_id": str(element["id"]),
        "role": element.get("role"),
        "cell": {
            "row_index": row_pos,
            "row_label": scalar_to_json(df.index[row_pos]),
            "column_index": col_pos,
            "column": scalar_to_json(column),
        },
        "before": scalar_to_json(before),
        "after": scalar_to_json(after),
        "mutation_type": "value_table_cell",
        "error_types": ["value_error"],
    }
    return data, [operation]


def _mutate_summary_value_slot(
    data: dict[str, Any],
    rng: random.Random,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    summary = _text_binding_element(data, "summary")
    if summary is None:
        return None
    slots = summary["text_binding"]["slots"]
    candidates = [
        (name, slot)
        for name, slot in slots.items()
        if slot.get("category") == "value" and parse_number(slot.get("value")) is not None
    ]
    if not candidates:
        return None

    slot_name, slot = rng.choice(candidates)
    before = str(slot["value"])
    after = str(mutate_number(before, rng))
    if before == after:
        return None
    slot["value"] = after
    summary["text"] = render_text_from_binding(summary)
    return data, [
        {
            "kind": "text_slot_edit",
            "target": "summary",
            "element_id": str(summary["id"]),
            "slot": slot_name,
            "before": before,
            "after": after,
            "mutation_type": "value_summary_slot",
            "error_types": ["value_error"],
        }
    ]


def _mutate_caption_presentation(
    data: dict[str, Any],
    rng: random.Random,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    captions = [
        element
        for element in _text_elements(data)
        if _binding_kind(element) == "caption"
        and "Chart_View_Label" in element["text_binding"]["slots"]
    ]
    if not captions:
        return None

    caption = rng.choice(captions)
    slot = caption["text_binding"]["slots"]["Chart_View_Label"]
    before = str(slot["value"])
    candidates = [label for label in PRESENTATION_LABELS if label != before]
    if not candidates:
        return None
    after = rng.choice(candidates)
    slot["value"] = after
    caption["text"] = render_text_from_binding(caption)
    return data, [
        {
            "kind": "text_slot_edit",
            "target": "st.caption",
            "element_id": str(caption["id"]),
            "slot": "Chart_View_Label",
            "before": before,
            "after": after,
            "mutation_type": "claim_caption_presentation",
            "error_types": ["claim_error"],
        }
    ]


def _mutate_summary_claim_slot(
    data: dict[str, Any],
    rng: random.Random,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    summary = _text_binding_element(data, "summary")
    if summary is None:
        return None
    slots = summary["text_binding"]["slots"]
    candidates = [
        (name, slot)
        for name, slot in slots.items()
        if slot.get("category") == "claim"
    ]
    rng.shuffle(candidates)
    for slot_name, slot in candidates:
        before = str(slot["value"])
        after = _mutate_claim_value(before, rng)
        if after is None or after == before:
            continue
        slot["value"] = after
        summary["text"] = render_text_from_binding(summary)
        return data, [
            {
                "kind": "text_slot_edit",
                "target": "summary",
                "element_id": str(summary["id"]),
                "slot": slot_name,
                "before": before,
                "after": after,
                "mutation_type": "claim_summary_slot",
                "error_types": ["claim_error"],
            }
        ]
    return None


def _mutate_claim_value(value: str, rng: random.Random) -> str | None:
    text = value.strip()
    lower = text.lower()
    candidates = []
    matched_spans: list[tuple[int, int]] = []
    for before in sorted(CLAIM_REPLACEMENTS, key=len, reverse=True):
        replacement = CLAIM_REPLACEMENTS[before]
        start = lower.find(before)
        if start < 0:
            continue
        end = start + len(before)
        if any(start < span_end and end > span_start for span_start, span_end in matched_spans):
            continue
        matched_spans.append((start, end))
        source = text[start : start + len(before)]
        candidates.append(
            text[:start]
            + _match_case(source, replacement)
            + text[end:]
        )
    candidates = [candidate for candidate in candidates if candidate != text]
    if candidates:
        return rng.choice(candidates)
    return None


def _match_case(source: str, target: str) -> str:
    if source.isupper():
        return target.upper()
    if source[:1].isupper():
        return target.capitalize()
    return target


def _text_binding_element(data: dict[str, Any], kind: str) -> dict[str, Any] | None:
    for element in _text_elements(data):
        if _binding_kind(element) == kind:
            return element
    return None


def _binding_kind(element: dict[str, Any]) -> str | None:
    binding = element.get("text_binding")
    if not isinstance(binding, dict):
        return None
    return str(binding.get("kind"))


def _text_elements(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        element
        for element in data.get("template_slide", {}).get("elements", [])
        if isinstance(element, dict) and element.get("type") == "textBox"
    ]
