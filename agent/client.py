import base64
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Literal

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI


def _image_data_url(image_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(image_path.name)
    if not mime_type:
        mime_type = "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _extract_message_text(message: Any) -> str | None:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        text = content.strip()
        return text or None

    if isinstance(content, list):
        texts = [str(item.get("text", "")).strip() for item in content if isinstance(item, dict) and item.get("type") == "text"]
        merged = "\n".join(t for t in texts if t).strip()
        return merged or None
    return None


class Client:
    """OpenAI SDK client."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout_sec: int = 120,
        enable_thinking: bool | None = False,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.enable_thinking = enable_thinking
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_sec,
        )

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: Path | None = None,
        temperature: float = 0.0,
        max_tokens: int = 8192,
        response_format: Literal["json_object"] | None = None,
        max_retries: int = 3,
    ) -> str:
        if image_path is None:
            user_content: list[dict[str, Any]] | str = user_prompt
        else:
            user_content = [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
            ]

        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.enable_thinking is not None:
            request_kwargs["extra_body"] = {"enable_thinking": self.enable_thinking}
        if response_format == "json_object":
            request_kwargs["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        retries = max(0, max_retries)
        for attempt in range(retries + 1):
            try:
                response = self._client.chat.completions.create(**request_kwargs)
            except (APITimeoutError, APIConnectionError, APIError) as exc:
                last_error = exc
                status_code = getattr(exc, "status_code", None)
                retryable = isinstance(exc, (APITimeoutError, APIConnectionError)) or status_code in { 
                    408, 409, 429, 500, 502, 503, 504,}

                if retryable and attempt < retries:
                    time.sleep(0.8 * (attempt + 1))
                    continue

                if isinstance(exc, APIError):
                    body = exc.body if hasattr(exc, "body") else str(exc)
                    raise RuntimeError(f"DashScope APIError {status_code}: {body}") from exc
                raise RuntimeError(f"DashScope request failed: {exc}") from exc

            if not response.choices:
                last_error = RuntimeError(f"No choices in model response: {response}")
                if attempt >= retries:
                    raise last_error
                time.sleep(0.5 * (attempt + 1))
                continue

            text = _extract_message_text(response.choices[0].message)
            if text is not None:
                return text

            last_error = RuntimeError("Model returned empty content.")
            if attempt >= retries:
                raise last_error
            time.sleep(0.8 * (attempt + 1))

        if last_error is not None:
            raise RuntimeError(f"Request failed after retries: {last_error}") from last_error
        raise RuntimeError("Request failed after retries.")
