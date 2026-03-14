#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.pipeline import PPTSummaryJudgeAgent  # noqa: E402


def _apply_langsmith_env_aliases() -> bool:
    """
    将 LANGSMITH_* 映射为 LangChain/LangGraph 常用环境变量。
    返回是否启用 tracing。
    """
    enabled = bool(os.getenv("LANGSMITH_TRACING"))
    if not enabled:
        return False

    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    if os.getenv("LANGSMITH_API_KEY"):
        os.environ.setdefault("LANGCHAIN_API_KEY", os.getenv("LANGSMITH_API_KEY", ""))
    if os.getenv("LANGSMITH_ENDPOINT"):
        os.environ.setdefault("LANGCHAIN_ENDPOINT", os.getenv("LANGSMITH_ENDPOINT", ""))
    if os.getenv("LANGSMITH_PROJECT"):
        os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGSMITH_PROJECT", ""))
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PPT summary judge on one image")
    parser.add_argument("--image", required=True, help="Path to slide image (.png/.jpg)")
    parser.add_argument(
        "--mode",
        choices=["no_tool", "with_tool", "with_tool_react"],
        default="with_tool",
        help="Judge mode",
    )
    parser.add_argument(
        "--no-auto-render-image",
        action="store_true",
        help="Disable auto-render from same-name .pptx when image is missing",
    )
    parser.add_argument(
        "--render-dpi",
        type=int,
        default=200,
        help="Render dpi when auto-rendering image",
    )
    parser.add_argument(
        "--render-backend",
        choices=["auto", "windows", "libreoffice"],
        default="auto",
        help="Auto-render backend",
    )
    parser.add_argument(
        "--poppler-path",
        default=None,
        help="Optional poppler bin path for windows backend",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Optional run name for LangSmith tracing",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image_path = Path(args.image).resolve()
    load_dotenv()
    tracing_enabled = _apply_langsmith_env_aliases()

    model = os.getenv("DASHSCOPE_MODEL", "qwen-vl-plus-latest")
    base_url = os.getenv(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise ValueError("Missing API key env: DASHSCOPE_API_KEY")
    enable_thinking = os.getenv("DASHSCOPE_ENABLE_THINKING")

    agent = PPTSummaryJudgeAgent(
        model=model,
        api_key=api_key,
        base_url=base_url,
        enable_thinking=enable_thinking,
    )
    run_name = args.run_name or f"run_single:{image_path.stem}:{args.mode}"
    run_metadata = {
        "entrypoint": "agent/run_single.py",
        "mode": args.mode,
        "image_path": str(image_path),
        "model": model,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    graph_config = (
        {
            "run_name": run_name,
            "tags": ["run_single", "ppt_review", args.mode],
            "metadata": run_metadata,
        }
        if tracing_enabled
        else None
    )

    result = agent.judge(
        image_path,
        mode=args.mode,
        auto_render_image=not args.no_auto_render_image,
        render_dpi=args.render_dpi,
        render_backend=args.render_backend,
        poppler_path=args.poppler_path,
        graph_config=graph_config,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
