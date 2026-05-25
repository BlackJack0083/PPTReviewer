from __future__ import annotations

import json
import re
from typing import Any


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    fenced = re.findall(
        r"```(?:json)?\s*(\{[\s\S]*?\})\s*```",
        stripped,
        flags=re.IGNORECASE,
    )
    for candidate in fenced:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        value = json.loads(stripped[start : end + 1])
        if isinstance(value, dict):
            return value

    raise ValueError(f"Cannot parse JSON object from response: {text}")
