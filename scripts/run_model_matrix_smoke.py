#!/usr/bin/env python3
"""Run a small model x mode benchmark matrix without touching the dataset."""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import random
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.pipeline import PPTSummaryJudgeAgent  # noqa: E402
from scripts.run_small_eval import (  # noqa: E402
    now_iso,
    parse_bool_env,
    read_jsonl,
    run_mode_eval,
    stage_cases_in_sandbox,
    to_gt_case,
    to_injected_case,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run model x mode smoke benchmark.")
    parser.add_argument(
        "--dataset-root",
        default="output/benchmark/dataset_20260407",
        help="Benchmark dataset root.",
    )
    parser.add_argument("--split", default="test", help="Split name.")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["Qwen3.5-4B", "Qwen3.5-9B", "Qwen3.5-27B", "Qwen3.5-35B-A3B"],
        help="Model names to evaluate.",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["no_tool", "with_tool", "with_tool_react"],
        default=["no_tool", "with_tool", "with_tool_react"],
        help="Modes to evaluate.",
    )
    parser.add_argument("--gt-samples", type=int, default=10, help="GT sample count.")
    parser.add_argument(
        "--injected-samples",
        type=int,
        default=10,
        help="Injected sample count.",
    )
    parser.add_argument("--seed", type=int, default=20260411, help="Random seed.")
    parser.add_argument("--workers", type=int, default=6, help="Concurrency per run.")
    parser.add_argument(
        "--matrix-workers",
        type=int,
        default=1,
        help="How many model x mode jobs to run in parallel.",
    )
    parser.add_argument("--case-retries", type=int, default=2, help="Retries per case.")
    parser.add_argument(
        "--base-url",
        default=None,
        help="Compatible API base URL. Defaults to DASHSCOPE_BASE_URL.",
    )
    parser.add_argument(
        "--api-key-env",
        default="DASHSCOPE_API_KEY",
        help="API key env var name.",
    )
    parser.add_argument(
        "--sandbox-root",
        default=str(Path(tempfile.gettempdir()) / "agent_model_matrix_smoke"),
        help="Sandbox directory for copied cases.",
    )
    parser.add_argument(
        "--output-root",
        default=str(PROJECT_ROOT / "output" / "eval_smoke"),
        help="Directory for summary artifacts.",
    )
    parser.add_argument(
        "--render-backend",
        choices=["auto", "windows", "libreoffice"],
        default="libreoffice",
        help="Image render backend if needed.",
    )
    parser.add_argument("--render-dpi", type=int, default=180, help="Render dpi.")
    parser.add_argument(
        "--auto-render-images",
        action="store_true",
        help="Auto-render images when missing in sandbox.",
    )
    return parser.parse_args()


def pick_cases(
    dataset_root: Path, split: str, gt_samples: int, injected_samples: int, seed: int
) -> list[dict[str, Any]]:
    samples_rows = read_jsonl(dataset_root / "manifest" / "samples.jsonl")
    injections_rows = read_jsonl(dataset_root / "manifest" / "injections.jsonl")

    split_samples = [r for r in samples_rows if r.get("split") == split]
    split_injections = [
        r
        for r in injections_rows
        if str(r.get("source_yaml", "")).startswith(f"split/{split}/")
    ]
    if not split_samples:
        raise ValueError(f"No samples found for split={split}")
    if not split_injections:
        raise ValueError(f"No injections found for split={split}")

    rng = random.Random(seed)  # noqa: S311 - benchmark sampling only  # nosec B311
    gt_picks = rng.sample(split_samples, k=min(gt_samples, len(split_samples)))
    inj_picks = rng.sample(
        split_injections, k=min(injected_samples, len(split_injections))
    )
    cases = [to_gt_case(dataset_root, row) for row in gt_picks] + [
        to_injected_case(dataset_root, row) for row in inj_picks
    ]
    rng.shuffle(cases)
    return cases


def make_agent_factory(model: str, api_key: str, base_url: str, enable_thinking: bool):
    def _factory() -> PPTSummaryJudgeAgent:
        return PPTSummaryJudgeAgent(
            model=model,
            api_key=api_key,
            base_url=base_url,
            enable_thinking=enable_thinking,
        )

    return _factory


def main() -> None:
    args = parse_args()
    dataset_root = Path(args.dataset_root).resolve()
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    sandbox_root = Path(args.sandbox_root).resolve()

    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise ValueError(f"Missing API key env var: {args.api_key_env}")
    base_url = args.base_url or os.getenv(
        "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    enable_thinking = parse_bool_env(
        os.getenv("DASHSCOPE_ENABLE_THINKING"), default=False
    )

    run_id = datetime.now(UTC).strftime("matrix_%Y%m%dT%H%M%SZ")
    cases = pick_cases(
        dataset_root=dataset_root,
        split=args.split,
        gt_samples=args.gt_samples,
        injected_samples=args.injected_samples,
        seed=args.seed,
    )
    staged_cases = stage_cases_in_sandbox(
        dataset_root=dataset_root,
        cases=cases,
        sandbox_root=sandbox_root,
        run_id=run_id,
    )

    matrix_rows: list[dict[str, Any]] = []
    detailed_runs: list[dict[str, Any]] = []

    jobs = [(model, mode) for model in args.models for mode in args.modes]

    def run_job(job: tuple[str, str]) -> dict[str, Any]:
        model, mode = job
        agent_factory = make_agent_factory(model, api_key, base_url, enable_thinking)
        result = run_mode_eval(
            agent_factory=agent_factory,
            dataset_root=dataset_root,
            run_id=f"{run_id}-{model}",
            mode=mode,
            cases=staged_cases,
            auto_render_images=args.auto_render_images,
            render_dpi=args.render_dpi,
            render_backend=args.render_backend,
            poppler_path=None,
            workers=max(1, args.workers),
            case_retries=max(0, args.case_retries),
        )
        return {
            "model": model,
            "mode": mode,
            "result": result,
        }

    with cf.ThreadPoolExecutor(max_workers=max(1, args.matrix_workers)) as executor:
        futures = [executor.submit(run_job, job) for job in jobs]
        for future in cf.as_completed(futures):
            item = future.result()
            result = item["result"]
            metrics = result["metrics"]
            matrix_rows.append(
                {
                    "model": item["model"],
                    "mode": item["mode"],
                    "total_cases": result["total_cases"],
                    "valid_cases": result["valid_cases"],
                    "error_cases": result["error_cases"],
                    **metrics,
                }
            )
            detailed_runs.append(item)

    order = {(model, mode): idx for idx, (model, mode) in enumerate(jobs)}
    matrix_rows.sort(key=lambda row: order[(row["model"], row["mode"])])
    detailed_runs.sort(key=lambda item: order[(item["model"], item["mode"])])

    summary = {
        "run_id": run_id,
        "created_at": now_iso(),
        "dataset_root": str(dataset_root),
        "split": args.split,
        "gt_samples": args.gt_samples,
        "injected_samples": args.injected_samples,
        "workers": max(1, args.workers),
        "matrix_workers": max(1, args.matrix_workers),
        "models": args.models,
        "modes": args.modes,
        "sandbox_root": str(sandbox_root / run_id),
        "matrix": matrix_rows,
    }

    summary_path = output_root / f"{run_id}_summary.json"
    detail_path = output_root / f"{run_id}_detailed.json"
    csv_path = output_root / f"{run_id}_matrix.csv"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    detail_path.write_text(
        json.dumps(
            {
                **summary,
                "cases": staged_cases,
                "detailed_runs": detailed_runs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    header = [
        "model",
        "mode",
        "total_cases",
        "valid_cases",
        "error_cases",
        "accuracy",
        "precision",
        "recall",
        "f1",
        "shape_selection_accuracy",
        "final_success_rate",
    ]
    lines = [",".join(header)]
    for row in matrix_rows:
        lines.append(",".join(str(row.get(col, "")) for col in header))
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
