from __future__ import annotations

import json
from typing import Any


def parse_json_object(text: str) -> dict[str, Any]:
    """解析模型返回的 JSON object。

    Args:
        text: 由 `response_format="json_object"` 约束的模型响应文本。

    Returns:
        解析后的 JSON object。

    Raises:
        json.JSONDecodeError: 响应不是合法 JSON 时抛出。
        ValueError: JSON 顶层不是 object 时抛出。
    """
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object, got {type(value).__name__}.")
    return value
