import json
import re
from typing import Any


def parse_json_object(text: str) -> dict[str, Any]:
    """
    尝试从模型输出中提取第一个 JSON 对象。
    支持以下情况：
    1) 纯 JSON 文本
    2) markdown code block 包裹
    3) 前后带解释文本
    """
    stripped = text.strip()

    # case 1: 直接 JSON
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    # case 2: ```json ... ```
    fenced = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", stripped, flags=re.IGNORECASE)
    for candidate in fenced:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue

    # case 3: 文本中截取首个 {...}
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        candidate = stripped[start : end + 1]
        value = json.loads(candidate)
        if isinstance(value, dict):
            return value

    raise ValueError(f"Cannot parse JSON object from response: {text}")
