from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarking.evaluation import ClientSimulator, SlideReviewEvaluator  # noqa: E402
from benchmarking.fine_grained.common import read_jsonl  # noqa: E402
from method.agents import (  # noqa: E402
    HeuristicRoleLabeler,
    SlideParserAgent,
    SlideReviewInput,
)
from method.pipeline import SlideReviewWorkflow  # noqa: E402
from method.slide_parser import OpenAIRoleLabeler  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the slide review workflow on injected benchmark cases."
    )
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=Path("output/slide_review_eval"))
    parser.add_argument(
        "--role-labeler",
        choices=["heuristic", "openai"],
        default="heuristic",
        help="Role labeling backend for Phase 1.1.",
    )
    return parser.parse_args()


def build_role_labeler(kind: str):
    if kind == "heuristic":
        return HeuristicRoleLabeler()
    model = os.getenv("DASHSCOPE_MODEL")
    if not model:
        raise RuntimeError(
            "DASHSCOPE_MODEL is required when --role-labeler=openai."
        )
    return OpenAIRoleLabeler(
        model=model,
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url=os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    )


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


def main() -> None:
    args = parse_args()
    benchmark_root = args.benchmark_root.resolve()
    manifest = read_jsonl(benchmark_root / "manifest" / "corruptions.jsonl")
    records = [record for record in manifest if str(record.get("split")) == args.split]

    workflow = SlideReviewWorkflow(
        slide_parser_agent=SlideParserAgent(build_role_labeler(args.role_labeler)),
    )
    evaluator = SlideReviewEvaluator()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    aggregate_detection_f1 = 0.0
    aggregate_interaction_f1 = 0.0

    for record in records:
        if written >= args.limit:
            break
        assets = load_case_assets(benchmark_root, record)
        if assets is None:
            skipped += 1
            continue

        case_id = f"{record.get('sample_id')}__{record.get('injection_id')}"
        slide_input = SlideReviewInput(
            pptx_path=assets["pptx_path"],
            image_path=assets["image_path"],
        )
        client = ClientSimulator(assets["feedback_episode"])
        result = workflow.run(slide_input, client_simulator=client)
        metrics = evaluator.evaluate_case(
            detected_issues=result.detected_issues,
            interaction_log=result.interaction_log,
            corruption_record=assets["corruption_record"],
            feedback_episode=assets["feedback_episode"],
        )
        aggregate_detection_f1 += float(metrics["detection"]["f1"])
        aggregate_interaction_f1 += float(metrics["interaction"]["f1"])

        payload = {
            "slide_input": {
                "case_id": case_id,
                "pptx_path": str(slide_input.pptx_path),
                "image_path": str(slide_input.image_path),
                "image_origin": assets["image_origin"],
                "role_labeler": args.role_labeler,
                "agent_visible_inputs": ["slide.pptx", "slide.png"],
                "gold_inputs_used_by_agent": [],
            },
            "result": result.to_dict(),
            "metrics": metrics,
            "gold_usage_boundary": {
                "client_simulator": "feedback_episode.json",
                "evaluator": ["corruption.json", "feedback_episode.json"],
            },
        }
        output_path = args.output_dir / f"{case_id}.json"
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written += 1

    summary = {
        "benchmark_root": str(benchmark_root),
        "split": args.split,
        "requested_limit": args.limit,
        "written": written,
        "skipped": skipped,
        "role_labeler": args.role_labeler,
        "avg_detection_f1": aggregate_detection_f1 / written if written else 0.0,
        "avg_interaction_f1": aggregate_interaction_f1 / written if written else 0.0,
        "output_dir": str(args.output_dir.resolve()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
