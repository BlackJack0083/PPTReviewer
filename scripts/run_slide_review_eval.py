from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarking.evaluation import SlideReviewEvaluator  # noqa: E402
from benchmarking.fine_grained.common import read_jsonl, scalar_to_json  # noqa: E402
from method.agents import (  # noqa: E402
    ClientAgent,
    ContentValidationAgent,
    DataSourceValidationAgent,
    SlideAnalysisAgent,
    SlideParserAgent,
    SlideReviewInput,
)  # noqa: E402
from method.pipeline import SlideReviewWorkflow  # noqa: E402

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def to_jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return scalar_to_json(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the slide review workflow on injected benchmark cases."
    )
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--case-timeout-sec", type=int, default=900)
    parser.add_argument("--case-retries", type=int, default=2)
    parser.add_argument("--retry-base-sleep-sec", type=float, default=8.0)
    parser.add_argument(
        "--client-mode",
        choices=("deterministic", "llm"),
        default="deterministic",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output/slide_review_eval"))
    return parser.parse_args()


def _agent_config(prefix: str, agent_name: str) -> dict[str, str | None]:
    model = os.getenv(f"{prefix}_DASHSCOPE_MODEL") or os.getenv("DASHSCOPE_MODEL")
    if not model:
        raise RuntimeError(
            f"{prefix}_DASHSCOPE_MODEL or DASHSCOPE_MODEL is required for {agent_name}."
        )
    return {
        "model": model,
        "api_key": os.getenv(f"{prefix}_DASHSCOPE_API_KEY") or os.getenv("DASHSCOPE_API_KEY"),
        "base_url": os.getenv(f"{prefix}_DASHSCOPE_BASE_URL")
        or os.getenv("DASHSCOPE_BASE_URL")
        or DEFAULT_BASE_URL,
    }


def build_slide_parser():
    return SlideParserAgent(**_agent_config("PARSER", "SlideParserAgent"))


def build_slide_analysis_agent():
    return SlideAnalysisAgent(**_agent_config("ANALYSIS", "SlideAnalysisAgent"))


def build_data_source_validation_agent():
    return DataSourceValidationAgent(
        **_agent_config("DATA_SOURCE", "DataSourceValidationAgent")
    )


def build_content_validation_agent():
    return ContentValidationAgent(**_agent_config("CONTENT", "ContentValidationAgent"))


def build_client_agent(episode: dict[str, object], mode: str) -> ClientAgent:
    if mode == "deterministic":
        return ClientAgent.from_feedback_episode(episode)
    return ClientAgent.from_feedback_episode(
        episode,
        mode="llm",
        **_agent_config("CLIENT", "ClientAgent"),
    )


def _is_retryable_error(error_text: str) -> bool:
    markers = (
        "429",
        "Too many requests",
        "timeout",
        "timed out",
        "Model returned empty content",
        "no structured_response",
        "temporarily unavailable",
    )
    return any(marker.lower() in error_text.lower() for marker in markers)


def load_case_assets(benchmark_root: Path, record: dict) -> dict | None:
    output_yaml = benchmark_root / str(record.get("output_yaml", ""))
    case_dir = output_yaml.parent
    output_ppt = case_dir / "slide.pptx"
    output_png = case_dir / "slide.png"
    corruption_path = case_dir / "corruption.json"
    feedback_path = case_dir / "feedback_episode.json"
    if not output_ppt.exists() or not output_png.exists():
        return None
    if not corruption_path.exists() or not feedback_path.exists():
        return None
    return {
        "case_dir": case_dir,
        "pptx_path": output_ppt,
        "image_path": output_png,
        "image_origin": "dataset",
        "corruption_record": json.loads(corruption_path.read_text(encoding="utf-8")),
        "feedback_episode": json.loads(feedback_path.read_text(encoding="utf-8")),
    }


async def main() -> None:
    args = parse_args()
    benchmark_root = args.benchmark_root.resolve()
    manifest = read_jsonl(benchmark_root / "manifest" / "corruptions.jsonl")
    records = [record for record in manifest if str(record.get("split")) == args.split]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    skipped = 0
    runnable: list[tuple[dict, dict]] = []
    for record in records:
        if len(runnable) >= args.limit:
            break
        assets = load_case_assets(benchmark_root, record)
        if assets is None:
            skipped += 1
            continue
        runnable.append((record, assets))

    semaphore = asyncio.Semaphore(max(1, args.workers))

    async def run_one(record: dict, assets: dict) -> dict:
        case_id = f"{record.get('sample_id')}__{record.get('injection_id')}"
        slide_input = SlideReviewInput(
            pptx_path=assets["pptx_path"],
            image_path=assets["image_path"],
        )
        payload: dict
        async with semaphore:
            for attempt in range(max(0, args.case_retries) + 1):
                try:
                    workflow = SlideReviewWorkflow(
                        slide_parser_agent=build_slide_parser(),
                        slide_analysis_agent=build_slide_analysis_agent(),
                        data_source_validation_agent=build_data_source_validation_agent(),
                        content_validation_agent=build_content_validation_agent(),
                    )
                    result = await asyncio.wait_for(
                        workflow.arun(
                            slide_input,
                            client_agent=build_client_agent(
                                assets["feedback_episode"],
                                args.client_mode,
                            ),
                        ),
                        timeout=args.case_timeout_sec,
                    )
                    metrics = SlideReviewEvaluator().evaluate_case(
                        detected_issues=result.detected_issues,
                        corruption_record=assets["corruption_record"],
                    )
                    result_dict = result.to_dict()
                    payload = {
                        "case_id": case_id,
                        "ok": True,
                        "attempt": attempt + 1,
                        "slide_input": {
                            "pptx_path": str(slide_input.pptx_path),
                            "image_path": str(slide_input.image_path),
                            "image_origin": assets["image_origin"],
                            "parser": "SlideParserAgent",
                            "client_mode": args.client_mode,
                            "agent_visible_inputs": ["slide.pptx", "slide.png"],
                            "gold_inputs_used_by_agent": [],
                        },
                        "stage_summary": {
                            "observed_elements": len(
                                result_dict["observed_slide"].get("elements", [])
                            ),
                            "tables": len(result_dict["analysis_state"].get("tables", [])),
                            "data_source_tool_calls": sum(
                                len(item.get("tool_log", []))
                                for item in result_dict["data_source_validation_log"]
                            ),
                            "content_tool_calls": len(
                                result_dict["content_validation_log"]
                            ),
                            "detected_issues": len(result_dict["detected_issues"]),
                            "table_records": len(result_dict["table_records"]),
                            "has_repaired_yaml": bool(
                                result_dict["repaired_artifacts"].get("yaml_path")
                            ),
                        },
                        "result": result_dict,
                        "metrics": metrics,
                        "gold_usage_boundary": {
                            "client_agent": ["feedback_episode.json"],
                            "evaluator": ["corruption.json"],
                        },
                    }
                    break
                except Exception as exc:  # noqa: BLE001
                    error_text = str(exc)
                    payload = {
                        "case_id": case_id,
                        "ok": False,
                        "attempt": attempt + 1,
                        "error": error_text,
                        "slide_input": {
                            "pptx_path": str(slide_input.pptx_path),
                            "image_path": str(slide_input.image_path),
                            "client_mode": args.client_mode,
                        },
                        "gold_usage_boundary": {
                            "client_agent": ["feedback_episode.json"],
                            "evaluator": ["corruption.json"],
                        },
                    }
                    if attempt >= max(0, args.case_retries) or not _is_retryable_error(
                        error_text
                    ):
                        break
                    sleep_sec = args.retry_base_sleep_sec * (2**attempt)
                    print(
                        json.dumps(
                            {
                                "event": "case_retry",
                                "case_id": case_id,
                                "attempt": attempt + 1,
                                "sleep_sec": sleep_sec,
                                "error": error_text.splitlines()[0],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    await asyncio.sleep(sleep_sec)
        output_path = args.output_dir / f"{case_id}.json"
        output_path.write_text(
            json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "event": "case_done",
                    "case_id": case_id,
                    "ok": bool(payload.get("ok")),
                    "attempt": payload.get("attempt"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return payload

    tasks = [asyncio.create_task(run_one(record, assets)) for record, assets in runnable]
    results = [await task for task in asyncio.as_completed(tasks)]
    successful = [result for result in results if result.get("ok")]
    aggregate_detection_f1 = sum(
        float(result["metrics"]["detection"]["f1"]) for result in successful
    )

    summary = {
        "benchmark_root": str(benchmark_root),
        "split": args.split,
        "requested_limit": args.limit,
        "workers": max(1, args.workers),
        "written": len(results),
        "succeeded": len(successful),
        "failed": len(results) - len(successful),
        "skipped": skipped,
        "parser": "SlideParserAgent",
        "client_mode": args.client_mode,
        "avg_detection_f1": aggregate_detection_f1 / len(successful)
        if successful
        else 0.0,
        "output_dir": str(args.output_dir.resolve()),
    }
    print(json.dumps(to_jsonable(summary), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
