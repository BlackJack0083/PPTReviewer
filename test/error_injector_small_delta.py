#!/usr/bin/env python3
"""
轻微数值扰动注入器（独立脚本）

目标：
1) 只做 numeric 小幅偏移（例如 +5/-5, +20/-20）
2) 不混入 trend/range/unit/text 等其他错误类型
3) 兼容 benchmark 目录结构，写入 injected/* 与 injections.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine import SummaryInjector  # noqa: E402

NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
RANGE_RE = re.compile(
    r"[-+]?\d[\d,]*(?:\.\d+)?\s*(?:-|~|–|—|to)\s*[-+]?\d[\d,]*(?:\.\d+)?",
    flags=re.IGNORECASE,
)


@dataclass
class MutationResult:
    slot_name: str
    truth_value: str
    injected_value: str
    error_type: str


def sanitize_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_num(token: str) -> float | None:
    cleaned = token.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def count_decimals(token: str) -> int:
    if "." not in token:
        return 0
    return len(token.split(".", 1)[1])


def format_like(value: float, sample: str) -> str:
    decimals = count_decimals(sample)
    use_comma = "," in sample
    if decimals == 0:
        n = int(round(value))
        return f"{n:,}" if use_comma else str(n)
    text = f"{value:.{decimals}f}"
    if not use_comma:
        return text
    whole, dot, frac = text.partition(".")
    whole_fmt = f"{int(whole):,}"
    return f"{whole_fmt}{dot}{frac}" if dot else whole_fmt


def mutate_one_numeric_token(token: str, rng: random.Random, deltas: list[float]) -> str:
    value = parse_num(token)
    if value is None:
        return token

    # 小值使用较小扰动，避免 +20 这类在小数值上过于激进。
    abs_value = abs(value)
    allowed = [d for d in deltas if d > 0]
    if not allowed:
        allowed = [5.0]
    if abs_value < 20:
        allowed = [d for d in allowed if d <= 5] or [min(allowed)]

    delta = float(rng.choice(allowed))
    sign = rng.choice((-1.0, 1.0))
    candidate = value + sign * delta

    # 非负值尽量保持非负（计数/面积/金额通常不应出现负值）
    if value >= 0 and candidate < 0:
        candidate = value + delta

    if abs(candidate - value) < 1e-12:
        candidate = value + delta

    return format_like(candidate, token)


def numeric_small_delta(text: str, rng: random.Random, deltas: list[float]) -> str:
    matches = list(NUMBER_RE.finditer(text))
    if not matches:
        return text

    # 每个槽位只改一个数字，控制“轻微错误”强度
    target_idx = rng.randrange(len(matches))
    out_parts: list[str] = []
    last = 0
    for idx, m in enumerate(matches):
        out_parts.append(text[last : m.start()])
        token = m.group(0)
        if idx == target_idx:
            out_parts.append(mutate_one_numeric_token(token, rng, deltas))
        else:
            out_parts.append(token)
        last = m.end()
    out_parts.append(text[last:])
    return "".join(out_parts)


def load_truth_slots(yaml_path: Path) -> dict[str, str]:
    data = SummaryInjector.load_yaml(yaml_path)
    summary_binding = data.get("summary_binding", {})
    truth_slots = summary_binding.get("summary_slots_truth", {})
    if not isinstance(truth_slots, dict):
        return {}
    return {str(k): str(v) for k, v in truth_slots.items()}


def pick_k_slots(
    truth_slots: dict[str, str], min_slots: int, max_slots: int, rng: random.Random
) -> list[tuple[str, str]]:
    numeric_items = [(k, v) for k, v in truth_slots.items() if is_small_delta_target_value(v)]
    if not numeric_items:
        return []
    upper = min(max_slots, len(numeric_items))
    lower = min(min_slots, upper)
    if lower <= 0:
        lower = 1
    k = rng.randint(lower, upper)
    return rng.sample(numeric_items, k)


def build_injection_dir_name(seed: int) -> str:
    return f"numeric_random_value-{seed}"


def is_small_delta_target_value(value: str) -> bool:
    """
    仅选择“单一整数数字”槽位，避免区间/小数导致扰动尺度失控。
    """
    text = str(value)
    if RANGE_RE.search(text):
        return False
    matches = list(NUMBER_RE.finditer(text))
    if len(matches) != 1:
        return False
    token = matches[0].group(0)
    return "." not in token


def inject_one_variant(
    source_yaml: Path,
    output_dir: Path,
    variant_seed: int,
    min_slots: int,
    max_slots: int,
    deltas: list[float],
    generate_ppt: bool,
) -> tuple[Path, Path | None, list[MutationResult]] | None:
    truth_slots = load_truth_slots(source_yaml)
    if not truth_slots:
        return None

    rng = random.Random(variant_seed)  # noqa: S311 - benchmark 注入需可复现
    selected_slots = pick_k_slots(truth_slots, min_slots=min_slots, max_slots=max_slots, rng=rng)
    if not selected_slots:
        return None

    mutations: list[MutationResult] = []
    overrides: dict[str, str] = {}
    for slot_name, truth_value in selected_slots:
        injected = numeric_small_delta(truth_value, rng, deltas)
        if not injected or injected == truth_value:
            continue
        mutations.append(
            MutationResult(
                slot_name=slot_name,
                truth_value=truth_value,
                injected_value=injected,
                error_type="numeric_random_value",
            )
        )
        overrides[slot_name] = injected

    if not overrides:
        return None

    variant_dir = output_dir / build_injection_dir_name(variant_seed)
    variant_dir.mkdir(parents=True, exist_ok=True)
    target_yaml = variant_dir / "slide.yaml"
    target_ppt = variant_dir / "slide.pptx" if generate_ppt else None

    if generate_ppt:
        SummaryInjector.inject_summary_and_rebuild_ppt(
            yaml_path=source_yaml,
            slot_overrides=overrides,
            output_yaml_path=target_yaml,
            output_ppt_path=target_ppt,
        )
    else:
        SummaryInjector.inject_summary_slots(
            yaml_path=source_yaml,
            slot_overrides=overrides,
            output_yaml_path=target_yaml,
        )
    return target_yaml, target_ppt, mutations


def is_benchmark_gt_yaml(yaml_path: Path) -> bool:
    parts = yaml_path.parts
    return len(parts) >= 5 and parts[-1] == "slide.yaml" and parts[-2] == "gt"


def find_dataset_root_from_yaml(yaml_path: Path) -> Path | None:
    parents = yaml_path.parents
    if len(parents) < 5:
        return None
    split_marker = parents[3]
    if split_marker.name != "split":
        return None
    return parents[4]


def ensure_manifest_files(dataset_root: Path) -> None:
    manifest_dir = dataset_root / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    for name in ("samples.jsonl", "injections.jsonl", "eval_runs.jsonl"):
        (manifest_dir / name).touch(exist_ok=True)


def record_injection_manifest(
    dataset_root: Path,
    source_yaml: Path,
    target_yaml: Path,
    target_ppt: Path | None,
    variant_seed: int,
    mutations: list[MutationResult],
) -> None:
    ensure_manifest_files(dataset_root)
    sample_id = source_yaml.parents[1].name.removeprefix("s_")
    record = {
        "injection_id": f"{sample_id}-{target_yaml.parent.name}",
        "sample_id": sample_id,
        "source_yaml": str(source_yaml.relative_to(dataset_root)),
        "output_yaml": str(target_yaml.relative_to(dataset_root)),
        "output_ppt": (
            str(target_ppt.relative_to(dataset_root))
            if target_ppt is not None and target_ppt.exists()
            else None
        ),
        "seed": variant_seed,
        "slot_count": len(mutations),
        "mutations": [
            {
                "slot_name": m.slot_name,
                "error_type": m.error_type,
                "truth_value": m.truth_value,
                "injected_value": m.injected_value,
            }
            for m in mutations
        ],
        "created_at": now_iso(),
    }
    append_jsonl(dataset_root / "manifest" / "injections.jsonl", record)
    write_json(target_yaml.parent / "inject_meta.json", record)


def resolve_yaml_files(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        path = Path(pattern)
        if any(token in pattern for token in ("*", "?", "[")):
            files.extend(Path(p) for p in glob.glob(pattern))
        elif path.exists() and path.is_file():
            files.append(path)
    return sorted({p.resolve() for p in files})


def discover_benchmark_gt_yamls(dataset_root: Path, split: str) -> list[Path]:
    sample_root = dataset_root / "split" / split
    if not sample_root.exists():
        return []
    return sorted(p.resolve() for p in sample_root.glob("s_*/gt/slide.yaml"))


def inject_for_yaml(
    yaml_path: Path,
    output_root: Path,
    variants_per_yaml: int,
    min_slots: int,
    max_slots: int,
    deltas: list[float],
    generate_ppt: bool,
    seed_gen: random.Random,
) -> int:
    produced = 0
    if is_benchmark_gt_yaml(yaml_path):
        out_dir = yaml_path.parents[1] / "injected"
    else:
        out_dir = output_root / sanitize_name(yaml_path.stem)
    out_dir.mkdir(parents=True, exist_ok=True)

    for _ in range(variants_per_yaml):
        variant_seed = seed_gen.randint(1, 10**9)
        result = inject_one_variant(
            source_yaml=yaml_path,
            output_dir=out_dir,
            variant_seed=variant_seed,
            min_slots=min_slots,
            max_slots=max_slots,
            deltas=deltas,
            generate_ppt=generate_ppt,
        )
        if result is None:
            continue

        target_yaml, target_ppt, mutations = result
        produced += 1
        print(f"  ✓ {yaml_path.name} -> {target_yaml.parent.name}")

        if is_benchmark_gt_yaml(yaml_path):
            dataset_root = find_dataset_root_from_yaml(yaml_path)
            if dataset_root is not None:
                record_injection_manifest(
                    dataset_root=dataset_root,
                    source_yaml=yaml_path,
                    target_yaml=target_yaml,
                    target_ppt=target_ppt,
                    variant_seed=variant_seed,
                    mutations=mutations,
                )
    return produced


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="轻微数值扰动注入器")
    parser.add_argument(
        "--benchmark-root",
        default="output/benchmark/dataset_v1",
        help="benchmark 数据集根目录（含 split/ 与 manifest/）",
    )
    parser.add_argument("--split", default="test", help="要处理的 split 名称")
    parser.add_argument(
        "--source",
        nargs="+",
        default=None,
        help="直接指定 YAML 文件或 glob（指定后覆盖 benchmark 扫描）",
    )
    parser.add_argument(
        "--output-dir",
        default="output/benchmark/_injected_small_delta",
        help="非 benchmark YAML 的输出目录",
    )
    parser.add_argument("--variants-per-yaml", type=int, default=3, help="每个 YAML 生成多少个版本")
    parser.add_argument("--min-slots", type=int, default=1, help="单次注入最少改多少个槽位")
    parser.add_argument("--max-slots", type=int, default=1, help="单次注入最多改多少个槽位")
    parser.add_argument(
        "--deltas",
        nargs="+",
        type=float,
        default=[5, 20],
        help="可选扰动幅度集合（例如 5 20）",
    )
    parser.add_argument("--seed", type=int, default=20260317, help="随机种子")
    parser.add_argument("--generate-ppt", action="store_true", help="注入后是否重建 PPT")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.min_slots <= 0 or args.max_slots <= 0:
        raise ValueError("min_slots / max_slots 必须为正整数")
    if args.min_slots > args.max_slots:
        raise ValueError("min_slots 不能大于 max_slots")
    if args.variants_per_yaml <= 0:
        raise ValueError("variants_per_yaml 必须大于 0")
    if not args.deltas or any(d <= 0 for d in args.deltas):
        raise ValueError("deltas 必须为正数列表")

    seed_gen = random.Random(args.seed)  # noqa: S311 - benchmark 注入需可复现
    if args.source:
        yaml_files = resolve_yaml_files(args.source)
    else:
        yaml_files = discover_benchmark_gt_yamls(Path(args.benchmark_root), args.split)

    if not yaml_files:
        print("未找到可处理的 YAML 文件")
        return

    print(f"找到 {len(yaml_files)} 个 YAML 文件")
    total_produced = 0
    output_root = Path(args.output_dir)
    for yaml_file in yaml_files:
        truth_slots = load_truth_slots(yaml_file)
        if not truth_slots:
            print(f"- 跳过 {yaml_file.name}: 缺少 summary_binding.summary_slots_truth")
            continue
        print(f"\n处理: {yaml_file}")
        produced = inject_for_yaml(
            yaml_path=yaml_file,
            output_root=output_root,
            variants_per_yaml=args.variants_per_yaml,
            min_slots=args.min_slots,
            max_slots=args.max_slots,
            deltas=[float(x) for x in args.deltas],
            generate_ppt=args.generate_ppt,
            seed_gen=seed_gen,
        )
        total_produced += produced
        if produced == 0:
            print("  - 未生成可用注入样本")

    print("\n注入完成")
    print(f"总共生成: {total_produced} 个注入样本")


if __name__ == "__main__":
    main()
