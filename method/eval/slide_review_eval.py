from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarking.fine_grained.common import read_jsonl, scalar_to_json
from method.agents import (
    ClientAgent,
    ContentValidationAgent,
    DataSourceValidationAgent,
    SlideAnalysisAgent,
    SlideParserAgent,
    SlideReviewInput,
)
from method.eval.metrics import SlideReviewEvaluator
from method.pipeline import SlideReviewWorkflow

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass(frozen=True)
class SlideReviewEvalConfig:
    benchmark_root: Path
    split: str = "test"
    limit: int = 3
    workers: int = 1
    case_timeout_sec: int = 900
    case_retries: int = 2
    retry_base_sleep_sec: float = 8.0
    client_mode: str = "deterministic"
    output_dir: Path = Path("output/slide_review_eval")


async def run_slide_review_eval(config: SlideReviewEvalConfig) -> dict[str, Any]:
    """Run slide review workflow evaluation on injected benchmark cases.

    The workflow-visible input is limited to `slide.pptx`, `slide.png`, and the
    case-local `feedback_episode.json` exposed through `ClientAgent`. Gold
    `corruption.json` is used only by the evaluator after the workflow finishes.

    Args:
        config: Dataset, concurrency, retry, client, and output settings.

    Returns:
        Aggregate evaluation summary. Per-case traces are written to
        `config.output_dir`.
    """
    benchmark_root = config.benchmark_root.resolve()
    records = _load_split_records(benchmark_root, config.split)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    skipped = 0
    runnable: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for record in records:
        if len(runnable) >= config.limit:
            break
        assets = load_case_assets(benchmark_root, record)
        if assets is None:
            skipped += 1
            continue
        runnable.append((record, assets))

    semaphore = asyncio.Semaphore(max(1, config.workers))
    tasks = [
        asyncio.create_task(_run_one_case(record, assets, config, semaphore))
        for record, assets in runnable
    ]
    results = [await task for task in asyncio.as_completed(tasks)]
    successful = [result for result in results if result.get("ok")]
    aggregate_detection_f1 = sum(
        float(result["metrics"]["detection"]["f1"]) for result in successful
    )

    return {
        "benchmark_root": str(benchmark_root),
        "split": config.split,
        "requested_limit": config.limit,
        "workers": max(1, config.workers),
        "written": len(results),
        "succeeded": len(successful),
        "failed": len(results) - len(successful),
        "skipped": skipped,
        "parser": "SlideParserAgent",
        "client_mode": config.client_mode,
        "avg_detection_f1": aggregate_detection_f1 / len(successful)
        if successful
        else 0.0,
        "output_dir": str(config.output_dir.resolve()),
    }


def load_case_assets(benchmark_root: Path, record: dict[str, Any]) -> dict[str, Any] | None:
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


def to_jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return scalar_to_json(value)


async def _run_one_case(
    record: dict[str, Any],
    assets: dict[str, Any],
    config: SlideReviewEvalConfig,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    case_id = f"{record.get('sample_id')}__{record.get('injection_id')}"
    slide_input = SlideReviewInput(
        pptx_path=assets["pptx_path"],
        image_path=assets["image_path"],
    )
    payload: dict[str, Any]
    async with semaphore:
        for attempt in range(max(0, config.case_retries) + 1):
            try:
                payload = await _attempt_case(
                    case_id=case_id,
                    slide_input=slide_input,
                    assets=assets,
                    config=config,
                    attempt=attempt + 1,
                )
                break
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                payload = _error_payload(case_id, slide_input, config, attempt + 1, error_text)
                if attempt >= max(0, config.case_retries) or not _is_retryable_error(
                    error_text
                ):
                    break
                sleep_sec = config.retry_base_sleep_sec * (2**attempt)
                _print_event(
                    {
                        "event": "case_retry",
                        "case_id": case_id,
                        "attempt": attempt + 1,
                        "sleep_sec": sleep_sec,
                        "error": error_text.splitlines()[0],
                    }
                )
                await asyncio.sleep(sleep_sec)

    output_path = config.output_dir / f"{case_id}.json"
    output_path.write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _print_event(
        {
            "event": "case_done",
            "case_id": case_id,
            "ok": bool(payload.get("ok")),
            "attempt": payload.get("attempt"),
        }
    )
    return payload


async def _attempt_case(
    *,
    case_id: str,
    slide_input: SlideReviewInput,
    assets: dict[str, Any],
    config: SlideReviewEvalConfig,
    attempt: int,
) -> dict[str, Any]:
    workflow = SlideReviewWorkflow(
        slide_parser_agent=_build_slide_parser(),
        slide_analysis_agent=_build_slide_analysis_agent(),
        data_source_validation_agent=_build_data_source_validation_agent(),
        content_validation_agent=_build_content_validation_agent(),
    )
    result = await asyncio.wait_for(
        workflow.arun(
            slide_input,
            client_agent=_build_client_agent(
                assets["feedback_episode"],
                config.client_mode,
            ),
        ),
        timeout=config.case_timeout_sec,
    )
    metrics = SlideReviewEvaluator().evaluate_case(
        detected_issues=result.detected_issues,
        corruption_record=assets["corruption_record"],
    )
    result_dict = result.to_dict()
    return {
        "case_id": case_id,
        "ok": True,
        "attempt": attempt,
        "slide_input": {
            "pptx_path": str(slide_input.pptx_path),
            "image_path": str(slide_input.image_path),
            "image_origin": assets["image_origin"],
            "parser": "SlideParserAgent",
            "client_mode": config.client_mode,
            "agent_visible_inputs": ["slide.pptx", "slide.png"],
            "gold_inputs_used_by_agent": [],
        },
        "stage_summary": _stage_summary(result_dict),
        "result": result_dict,
        "metrics": metrics,
        "gold_usage_boundary": _gold_usage_boundary(),
    }


def _stage_summary(result_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "observed_elements": len(result_dict["observed_slide"].get("elements", [])),
        "tables": len(result_dict["analysis_state"].get("tables", [])),
        "data_source_tool_calls": sum(
            len(item.get("tool_log", []))
            for item in result_dict["data_source_validation_log"]
        ),
        "content_tool_calls": len(result_dict["content_validation_log"]),
        "detected_issues": len(result_dict["detected_issues"]),
        "table_records": len(result_dict["table_records"]),
        "has_repaired_yaml": bool(result_dict["repaired_artifacts"].get("yaml_path")),
    }


def _error_payload(
    case_id: str,
    slide_input: SlideReviewInput,
    config: SlideReviewEvalConfig,
    attempt: int,
    error_text: str,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "ok": False,
        "attempt": attempt,
        "error": error_text,
        "slide_input": {
            "pptx_path": str(slide_input.pptx_path),
            "image_path": str(slide_input.image_path),
            "client_mode": config.client_mode,
        },
        "gold_usage_boundary": _gold_usage_boundary(),
    }


def _load_split_records(benchmark_root: Path, split: str) -> list[dict[str, Any]]:
    manifest = read_jsonl(benchmark_root / "manifest" / "corruptions.jsonl")
    return [record for record in manifest if str(record.get("split")) == split]


def _build_slide_parser() -> SlideParserAgent:
    return SlideParserAgent(**_agent_config("PARSER", "SlideParserAgent"))


def _build_slide_analysis_agent() -> SlideAnalysisAgent:
    return SlideAnalysisAgent(**_agent_config("ANALYSIS", "SlideAnalysisAgent"))


def _build_data_source_validation_agent() -> DataSourceValidationAgent:
    return DataSourceValidationAgent(
        **_agent_config("DATA_SOURCE", "DataSourceValidationAgent")
    )


def _build_content_validation_agent() -> ContentValidationAgent:
    return ContentValidationAgent(**_agent_config("CONTENT", "ContentValidationAgent"))


def _build_client_agent(episode: dict[str, object], mode: str) -> ClientAgent:
    if mode == "deterministic":
        return ClientAgent.from_feedback_episode(episode)
    return ClientAgent.from_feedback_episode(
        episode,
        mode="llm",
        **_agent_config("CLIENT", "ClientAgent"),
    )


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


def _gold_usage_boundary() -> dict[str, list[str]]:
    return {
        "client_agent": ["feedback_episode.json"],
        "evaluator": ["corruption.json"],
    }


def _print_event(payload: dict[str, Any]) -> None:
    print(json.dumps(to_jsonable(payload), ensure_ascii=False), flush=True)
