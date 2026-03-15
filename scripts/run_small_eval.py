#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import random
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from loguru import logger
from tqdm.auto import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.pipeline import AgentResult, PPTSummaryJudgeAgent  # noqa: E402


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_bool_env(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def to_gt_case(dataset_root: Path, sample_row: dict[str, Any]) -> dict[str, Any]:
    gt_yaml = dataset_root / sample_row["gt_yaml"]
    gt_yaml_rel = sample_row["gt_yaml"]
    gt_ppt_rel = sample_row.get("gt_ppt", str(Path(gt_yaml_rel).with_name("slide.pptx")))
    target_image_rel = str(Path(gt_yaml_rel).with_name("slide.png"))
    return {
        "case_id": f"gt-{sample_row['sample_id']}",
        "kind": "gt",
        "sample_id": sample_row["sample_id"],
        "expected_has_issue": False,
        "image_path": str(gt_yaml.with_name("slide.png")),
        "source_yaml": gt_yaml_rel,
        "target_yaml": gt_yaml_rel,
        "target_ppt": gt_ppt_rel,
        "target_image": target_image_rel,
    }


def to_injected_case(dataset_root: Path, inj_row: dict[str, Any]) -> dict[str, Any]:
    output_yaml = dataset_root / inj_row["output_yaml"]
    output_yaml_rel = inj_row["output_yaml"]
    output_ppt_rel = inj_row.get("output_ppt", str(Path(output_yaml_rel).with_name("slide.pptx")))
    target_image_rel = str(Path(output_yaml_rel).with_name("slide.png"))
    return {
        "case_id": f"inj-{inj_row['injection_id']}",
        "kind": "injected",
        "sample_id": inj_row["sample_id"],
        "injection_id": inj_row["injection_id"],
        "expected_has_issue": True,
        "image_path": str(output_yaml.with_name("slide.png")),
        "source_yaml": inj_row["source_yaml"],
        "target_yaml": output_yaml_rel,
        "target_ppt": output_ppt_rel,
        "target_image": target_image_rel,
    }


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    valid = [r for r in rows if r.get("pred_has_issue") is not None]
    if not valid:
        return {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0}

    tp = sum(1 for r in valid if r["expected_has_issue"] and r["pred_has_issue"])
    tn = sum(1 for r in valid if (not r["expected_has_issue"]) and (not r["pred_has_issue"]))
    fp = sum(1 for r in valid if (not r["expected_has_issue"]) and r["pred_has_issue"])
    fn = sum(1 for r in valid if r["expected_has_issue"] and (not r["pred_has_issue"]))

    accuracy = (tp + tn) / len(valid) if valid else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def run_mode_eval(
    agent_factory: Callable[[], PPTSummaryJudgeAgent],
    mode: str,
    cases: list[dict[str, Any]],
    auto_render_images: bool,
    render_dpi: int,
    render_backend: str,
    poppler_path: str | None,
    workers: int,
    case_retries: int,
) -> dict[str, Any]:
    thread_local = threading.local()

    def get_agent() -> PPTSummaryJudgeAgent:
        agent = getattr(thread_local, "agent", None)
        if agent is None:
            agent = agent_factory()
            thread_local.agent = agent
        return agent

    def run_one_sync(idx: int, case: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        retries = max(0, case_retries)
        image_path = Path(case["image_path"])
        last_row: dict[str, Any] | None = None

        for attempt in range(retries + 1):
            row = dict(case)
            row["mode"] = mode
            try:
                agent = get_agent()
                agent_result: AgentResult = agent.judge(  # type: ignore[arg-type]
                    image_path,
                    mode=mode,
                    auto_render_image=auto_render_images,
                    render_dpi=render_dpi,
                    render_backend=render_backend,
                    poppler_path=poppler_path,
                )
                row["pred_has_issue"] = bool(agent_result.has_issue)
                row["ok"] = row["pred_has_issue"] == row["expected_has_issue"]
                row["agent_result"] = asdict(agent_result)
                return idx, row
            except Exception as exc:  # noqa: BLE001
                row["pred_has_issue"] = None
                row["ok"] = False
                row["error"] = str(exc)
                last_row = row
                err_text = row["error"]
                can_retry = (
                    attempt < retries
                    and "Model returned empty content." in err_text
                )
                if not can_retry:
                    return idx, row
                sleep_sec = 0.8 * (attempt + 1)
                logger.warning(
                    f"{mode} {row['case_id']} empty content, retry {attempt + 1}/{retries} "
                    f"after {sleep_sec:.1f}s"
                )
                time.sleep(sleep_sec)

        assert last_row is not None
        return idx, last_row

    indexed_cases = list(enumerate(cases, 1))
    results: list[dict[str, Any] | None] = [None] * len(indexed_cases)

    async def _run_async() -> None:
        semaphore = asyncio.Semaphore(max(1, workers))

        async def run_one_async(idx: int, case: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            async with semaphore:
                return await asyncio.to_thread(run_one_sync, idx, case)

        tasks = [asyncio.create_task(run_one_async(idx, case)) for idx, case in indexed_cases]
        with tqdm(total=len(tasks), desc=mode, unit="case") as bar:
            for fut in asyncio.as_completed(tasks):
                i, row = await fut
                results[i - 1] = row
                if row.get("pred_has_issue") is None:
                    logger.warning(
                        f"[{bar.n + 1}/{len(cases)}] {mode} {row['case_id']} "
                        f"error={row.get('error', '')}"
                    )
                else:
                    logger.info(
                        f"[{bar.n + 1}/{len(cases)}] {mode} {row['case_id']} "
                        f"pred={row['pred_has_issue']} gold={row['expected_has_issue']}"
                    )
                bar.update(1)

    asyncio.run(_run_async())

    finalized_results = [r for r in results if r is not None]
    assert len(finalized_results) == len(cases)

    metrics = compute_metrics(finalized_results)
    return {
        "mode": mode,
        "total_cases": len(cases),
        "valid_cases": sum(1 for r in finalized_results if r.get("pred_has_issue") is not None),
        "error_cases": sum(1 for r in finalized_results if r.get("pred_has_issue") is None),
        "metrics": metrics,
        "results": finalized_results,
    }


def write_sample_eval_records(
    dataset_root: Path,
    split: str,
    run_id: str,
    mode: str,
    model: str,
    rows: list[dict[str, Any]],
    filename: str,
) -> None:
    for row in rows:
        sample_id = row["sample_id"]
        eval_path = dataset_root / "split" / split / f"s_{sample_id}" / "eval" / filename
        record = {
            "run_id": run_id,
            "mode": mode,
            "model": model,
            "kind": row.get("kind"),
            "sample_id": sample_id,
            "target_ppt": row.get("target_ppt", ""),
            "expected_has_issue": row.get("expected_has_issue"),
            "pred_has_issue": row.get("pred_has_issue"),
            "ok": row.get("ok"),
            "error": row.get("error", ""),
            "agent_result": row.get("agent_result"),
        }
        append_jsonl(eval_path, record)


def build_case_manifest_records(
    run_id: str,
    split: str,
    mode: str,
    model: str,
    report_path: Path,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        records.append(
            {
                "run_id": run_id,
                "split": split,
                "mode": mode,
                "model": model,
                "kind": row.get("kind", ""),
                "sample_id": row.get("sample_id", ""),
                "target_ppt": row.get("target_ppt", ""),
                "expected_has_issue": row.get("expected_has_issue"),
                "pred_has_issue": row.get("pred_has_issue"),
                "ok": row.get("ok"),
                "error": row.get("error", ""),
                "report_path": str(report_path),
            }
        )
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Small-scale binary eval for PPT agent")
    parser.add_argument(
        "--dataset-root",
        default="output/benchmark/dataset_v1",
        help="Benchmark dataset root",
    )
    parser.add_argument("--split", default="test_size_b", help="Split name")
    parser.add_argument(
        "--mode",
        choices=["no_tool", "with_tool", "with_tool_react", "both"],
        default="both",
        help="Eval mode",
    )
    parser.add_argument("--gt-samples", type=int, default=50, help="GT sample size")
    parser.add_argument(
        "--injected-samples",
        type=int,
        default=50,
        help="Injected sample size",
    )
    parser.add_argument("--seed", type=int, default=20260310, help="Random seed")
    parser.add_argument(
        "--model",
        default=None,
        help="Vision-capable model name (default: DASHSCOPE_MODEL or qwen-vl-plus-latest)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "DashScope OpenAI-compatible base URL "
            "(default: DASHSCOPE_BASE_URL or official compatible endpoint)"
        ),
    )
    parser.add_argument(
        "--api-key-env",
        default="DASHSCOPE_API_KEY",
        help="API key env var name",
    )
    parser.add_argument(
        "--auto-render-images",
        action="store_true",
        help="If slide.png missing, auto-render from slide.pptx",
    )
    parser.add_argument("--render-dpi", type=int, default=180, help="Render dpi")
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
        "--output-json",
        default=None,
        help="Optional output JSON path; default in output/eval/",
    )
    parser.add_argument(
        "--append-manifest",
        action="store_true",
        help="Append per-case eval records to manifest/eval_runs.jsonl",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Async concurrency per mode",
    )
    parser.add_argument(
        "--case-retries",
        type=int,
        default=2,
        help="Retries per case for empty-content model responses",
    )
    parser.add_argument(
        "--no-write-sample-eval",
        action="store_true",
        help="Disable writing per-sample eval records under split/<split>/s_<id>/eval/",
    )
    parser.add_argument(
        "--sample-eval-filename",
        default=None,
        help="Filename under sample eval dir (default: <run_id>.jsonl)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional log file path (default: output/log/<run_id>_<split>_<mode>.log)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()
    dataset_root = Path(args.dataset_root).resolve()
    manifest_root = dataset_root / "manifest"
    model = args.model or os.getenv("DASHSCOPE_MODEL", "qwen-vl-plus-latest")
    base_url = args.base_url or os.getenv(
        "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    enable_thinking = parse_bool_env(os.getenv("DASHSCOPE_ENABLE_THINKING"), default=False)

    samples_rows = read_jsonl(manifest_root / "samples.jsonl")
    injections_rows = read_jsonl(manifest_root / "injections.jsonl")

    split_samples = [r for r in samples_rows if r.get("split") == args.split]
    split_injections = [
        r
        for r in injections_rows
        if str(r.get("source_yaml", "")).startswith(f"split/{args.split}/")
    ]
    if not split_samples:
        raise ValueError(f"No samples found for split={args.split}")
    if not split_injections:
        raise ValueError(f"No injections found for split={args.split}")

    rng = random.Random(args.seed)  # noqa: S311 - benchmark sampling only
    gt_picks = rng.sample(split_samples, k=min(args.gt_samples, len(split_samples)))
    inj_picks = rng.sample(split_injections, k=min(args.injected_samples, len(split_injections)))

    cases = [to_gt_case(dataset_root, row) for row in gt_picks] + [
        to_injected_case(dataset_root, row) for row in inj_picks
    ]
    rng.shuffle(cases)

    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise ValueError(f"Missing API key env var: {args.api_key_env}")

    def make_agent() -> PPTSummaryJudgeAgent:
        return PPTSummaryJudgeAgent(
            model=model,
            api_key=api_key,
            base_url=base_url,
            enable_thinking=enable_thinking,
        )

    modes = ["no_tool", "with_tool", "with_tool_react"] if args.mode == "both" else [args.mode]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.log_file:
        log_path = Path(args.log_file).resolve()
    else:
        log_path = (PROJECT_ROOT / "output" / "log" / f"{run_id}_{args.split}_{args.mode}.log").resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(log_path),
        level="INFO",
        encoding="utf-8",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )
    logger.info(f"Logging to file: {log_path}")

    run_results: list[dict[str, Any]] = []
    sample_eval_filename = args.sample_eval_filename or f"{run_id}.jsonl"

    for mode in modes:
        logger.info(f"=== Running mode: {mode} ===")
        mode_result = run_mode_eval(
            agent_factory=make_agent,
            mode=mode,
            cases=cases,
            auto_render_images=args.auto_render_images,
            render_dpi=args.render_dpi,
            render_backend=args.render_backend,
            poppler_path=args.poppler_path,
            workers=max(1, args.workers),
            case_retries=max(0, args.case_retries),
        )
        run_results.append(mode_result)
        logger.info(
            f"mode={mode} metrics={mode_result['metrics']} "
            f"valid={mode_result['valid_cases']} error={mode_result['error_cases']}"
        )
        if not args.no_write_sample_eval:
            write_sample_eval_records(
                dataset_root=dataset_root,
                split=args.split,
                run_id=run_id,
                mode=mode,
                model=model,
                rows=mode_result["results"],
                filename=sample_eval_filename,
            )

    created_at = now_iso()

    if args.output_json:
        output_json = Path(args.output_json).resolve()
    else:
        output_json = (PROJECT_ROOT / "output" / "eval" / f"{run_id}.json").resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)

    mode_metrics = [
        {
            "mode": mode_result["mode"],
            "total_cases": mode_result["total_cases"],
            "valid_cases": mode_result["valid_cases"],
            "error_cases": mode_result["error_cases"],
            "metrics": mode_result["metrics"],
        }
        for mode_result in run_results
    ]
    payload = {
        "run_id": run_id,
        "created_at": created_at,
        "dataset_root": str(dataset_root),
        "split": args.split,
        "model": model,
        "mode": args.mode,
        "gt_samples": len(gt_picks),
        "injected_samples": len(inj_picks),
        "workers": max(1, args.workers),
        "sample_eval_filename": sample_eval_filename if not args.no_write_sample_eval else "",
        "mode_metrics": mode_metrics,
    }
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Saved eval report: {output_json}")

    if args.append_manifest:
        case_records: list[dict[str, Any]] = []
        for mode_result in run_results:
            case_records.extend(
                build_case_manifest_records(
                    run_id=run_id,
                    split=args.split,
                    mode=mode_result["mode"],
                    model=model,
                    report_path=output_json,
                    rows=mode_result["results"],
                )
            )
        eval_manifest = manifest_root / "eval_runs.jsonl"
        for record in case_records:
            append_jsonl(eval_manifest, record)
        logger.info(f"Appended eval manifest: {eval_manifest}")


if __name__ == "__main__":
    main()
