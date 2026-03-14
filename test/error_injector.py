#!/usr/bin/env python3
"""
Summary 槽位错误注入工具（v3）

特性：
1. 基于 summary_binding.summary_slots_truth 做结构化注入
2. 按槽位和值自动匹配注入策略（数值/区间/趋势/文本）
3. 支持一次注入随机数量槽位（min_slots ~ max_slots）
4. 支持 benchmark 目录结构，自动产出 inject_meta.json + injections.jsonl
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
    r"(?P<left>[-+]?\d[\d,]*(?:\.\d+)?)\s*(?:-|~|–|—|to)\s*(?P<right>[-+]?\d[\d,]*(?:\.\d+)?)",
    flags=re.IGNORECASE,
)

TREND_FLIPS = {
    "an increase": "a decrease",
    "a decrease": "an increase",
    "increased": "decreased",
    "decreased": "increased",
    "increase": "decrease",
    "decrease": "increase",
    "upward": "downward",
    "downward": "upward",
    "growth": "decline",
    "decline": "growth",
    "rose": "fell",
    "fell": "rose",
    "rise": "fall",
    "fall": "rise",
}
TREND_KEYS_ORDERED = sorted(TREND_FLIPS.keys(), key=len, reverse=True)

UNIT_MUTATIONS = [
    ("yuan/m²", "yuan"),
    ("m²", "m"),
    ("㎡", "m"),
    ("units", "households"),
    ("unit", "household"),
    ("%", "‰"),
    ("M", "K"),
    ("K", "M"),
]


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


def has_number(text: str) -> bool:
    return bool(NUMBER_RE.search(text))


def has_range(text: str) -> bool:
    return bool(RANGE_RE.search(text))


def slot_looks_trend(slot_name: str, value: str) -> bool:
    slot_lower = slot_name.lower()
    if any(x in slot_lower for x in ("trend", "direction", "trajectory", "absorption")):
        return True
    value_lower = value.lower()
    return any(k in value_lower for k in TREND_FLIPS)


def count_decimals(token: str) -> int:
    if "." not in token:
        return 0
    return len(token.split(".", 1)[1])


def parse_num(token: str) -> float | None:
    cleaned = token.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def format_like(value: float, sample: str) -> str:
    decimals = count_decimals(sample)
    use_comma = "," in sample
    if decimals == 0:
        n = int(round(value))
        return f"{n:,}" if use_comma else str(n)
    fmt = f"{{:.{decimals}f}}".format(value)
    if not use_comma:
        return fmt
    whole, dot, frac = fmt.partition(".")
    whole_fmt = f"{int(whole):,}"
    return f"{whole_fmt}{dot}{frac}" if dot else whole_fmt


def mutate_numeric_token(token: str, rng: random.Random) -> str:
    original = parse_num(token)
    if original is None:
        return token

    magnitude = max(abs(original), 1.0)
    for _ in range(8):
        mode = rng.choice(("scale", "offset", "random"))
        if mode == "scale":
            factor = rng.choice((0.25, 0.5, 1.5, 2.0, 3.0, 5.0))
            candidate = original * factor
        elif mode == "offset":
            delta = rng.uniform(magnitude * 0.3, magnitude * 2.0)
            candidate = original + rng.choice((-1, 1)) * delta
        else:
            low = -magnitude * 2.0
            high = magnitude * 4.0
            candidate = rng.uniform(low, high)

        if abs(candidate - original) < 1e-9:
            continue
        if abs(original) > 0 and abs(candidate - original) / abs(original) < 0.15:
            continue
        return format_like(candidate, token)

    fallback = original + magnitude + 7.0
    return format_like(fallback, token)


def numeric_random_value(text: str, rng: random.Random) -> str:
    changed = False

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        token = match.group(0)
        new_token = mutate_numeric_token(token, rng)
        if new_token != token:
            changed = True
        return new_token

    output = NUMBER_RE.sub(repl, text)
    return output if changed else text


def range_shift(text: str, rng: random.Random) -> str:
    match = RANGE_RE.search(text)
    if not match:
        return text

    left_token = match.group("left")
    right_token = match.group("right")
    left = parse_num(left_token)
    right = parse_num(right_token)
    if left is None or right is None:
        return text

    lo = min(left, right)
    hi = max(left, right)
    width = max(hi - lo, 1.0)
    shift = rng.uniform(width * 0.5, width * 2.5) * rng.choice((-1, 1))
    new_left = lo + shift
    new_right = hi + shift

    left_new_token = format_like(new_left, left_token)
    right_new_token = format_like(new_right, right_token)
    replacement = f"{left_new_token}-{right_new_token}"
    return f"{text[:match.start()]}{replacement}{text[match.end():]}"


def range_reverse(text: str, _rng: random.Random) -> str:
    match = RANGE_RE.search(text)
    if not match:
        return text
    left_token = match.group("left")
    right_token = match.group("right")
    replacement = f"{right_token}-{left_token}"
    return f"{text[:match.start()]}{replacement}{text[match.end():]}"


def match_case(source: str, target: str) -> str:
    if source.isupper():
        return target.upper()
    if source[:1].isupper():
        return target.capitalize()
    return target


def trend_flip(text: str, _rng: random.Random) -> str:
    output = text
    replaced = False
    for key in TREND_KEYS_ORDERED:
        value = TREND_FLIPS[key]
        pattern = re.compile(rf"\b{re.escape(key)}\b", flags=re.IGNORECASE)

        def repl(match: re.Match[str], replacement: str = value) -> str:
            nonlocal replaced
            replaced = True
            return match_case(match.group(0), replacement)

        output = pattern.sub(repl, output)
    return output if replaced else text


def unit_confusion(text: str, rng: random.Random) -> str:
    candidates = [(old, new) for old, new in UNIT_MUTATIONS if old in text]
    if candidates:
        old, new = rng.choice(candidates)
        return text.replace(old, new, 1)
    trimmed = re.sub(r"(m²|㎡|yuan/m²|units?|%)", "", text, count=1, flags=re.IGNORECASE)
    trimmed = re.sub(r"\s{2,}", " ", trimmed).strip()
    return trimmed if trimmed else text


def text_shuffle(text: str, rng: random.Random) -> str:
    words = text.split()
    if len(words) >= 2:
        i, j = rng.sample(range(len(words)), 2)
        words[i], words[j] = words[j], words[i]
        return " ".join(words)
    if text:
        suffix = rng.choice([" X", " Prime", " Alt"])
        return text + suffix
    return text


ERROR_MUTATORS = {
    "numeric_random_value": numeric_random_value,
    "range_shift": range_shift,
    "range_reverse": range_reverse,
    "trend_flip": trend_flip,
    "unit_confusion": unit_confusion,
    "text_shuffle": text_shuffle,
}


def applicable_errors(slot_name: str, value: str) -> list[str]:
    options: list[str] = []
    if has_range(value):
        options.extend(["range_shift", "range_reverse"])
    if has_number(value):
        options.extend(["numeric_random_value"])
    if slot_looks_trend(slot_name, value):
        options.append("trend_flip")
    if not options:
        options.append("text_shuffle")
    # 去重并保持顺序
    seen = set()
    ordered = []
    for name in options:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def mutate_slot_value(
    slot_name: str,
    truth_value: str,
    rng: random.Random,
    allowed_errors: list[str] | None,
) -> MutationResult | None:
    candidates = applicable_errors(slot_name, truth_value)
    if allowed_errors:
        filtered = [c for c in candidates if c in allowed_errors]
        if filtered:
            candidates = filtered
        else:
            fallback = [c for c in allowed_errors if c in ERROR_MUTATORS]
            if fallback:
                candidates = fallback

    tried: set[str] = set()
    while len(tried) < len(candidates):
        error_type = rng.choice([c for c in candidates if c not in tried])
        tried.add(error_type)
        mutator = ERROR_MUTATORS[error_type]
        injected = mutator(truth_value, rng)
        if injected and injected != truth_value:
            return MutationResult(
                slot_name=slot_name,
                truth_value=truth_value,
                injected_value=injected,
                error_type=error_type,
            )
    return None


def load_truth_slots(yaml_path: Path) -> dict[str, str]:
    data = SummaryInjector.load_yaml(yaml_path)
    summary_binding = data.get("summary_binding", {})
    truth_slots = summary_binding.get("summary_slots_truth", {})
    if not isinstance(truth_slots, dict):
        return {}
    return {str(k): str(v) for k, v in truth_slots.items()}


def build_injection_dir_name(mutations: list[MutationResult], seed: int) -> str:
    if len(mutations) == 1:
        item = mutations[0]
        return f"{sanitize_name(item.error_type)}-{seed}"
    unique_errors = {m.error_type for m in mutations}
    error_tag = "mixed" if len(unique_errors) > 1 else sanitize_name(mutations[0].error_type)
    return f"{error_tag}-{seed}"


def pick_k_slots(
    truth_slots: dict[str, str], min_slots: int, max_slots: int, rng: random.Random
) -> list[tuple[str, str]]:
    items = list(truth_slots.items())
    if not items:
        return []

    upper = min(max_slots, len(items))
    lower = min(min_slots, upper)
    if lower <= 0:
        lower = 1
    k = rng.randint(lower, upper)
    return rng.sample(items, k)


def inject_one_variant(
    source_yaml: Path,
    output_dir: Path,
    variant_seed: int,
    allowed_errors: list[str] | None,
    min_slots: int,
    max_slots: int,
    generate_ppt: bool,
) -> tuple[Path, Path | None, list[MutationResult]] | None:
    truth_slots = load_truth_slots(source_yaml)
    if not truth_slots:
        return None

    rng = random.Random(variant_seed)  # noqa: S311 - benchmark 样本注入仅需可复现伪随机
    selected_slots = pick_k_slots(truth_slots, min_slots=min_slots, max_slots=max_slots, rng=rng)
    if not selected_slots:
        return None

    mutations: list[MutationResult] = []
    overrides: dict[str, str] = {}
    for slot_name, truth_value in selected_slots:
        mutation = mutate_slot_value(
            slot_name=slot_name,
            truth_value=truth_value,
            rng=rng,
            allowed_errors=allowed_errors,
        )
        if mutation is None:
            continue
        mutations.append(mutation)
        overrides[mutation.slot_name] = mutation.injected_value

    if not overrides:
        return None

    variant_name = build_injection_dir_name(mutations, variant_seed)
    variant_dir = output_dir / variant_name
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
    # .../dataset_v1/split/test/s_xxx/gt/slide.yaml
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
        path = manifest_dir / name
        path.touch(exist_ok=True)


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

    meta_path = target_yaml.parent / "inject_meta.json"
    write_json(meta_path, record)


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
    allowed_errors: list[str] | None,
    generate_ppt: bool,
    seed_gen: random.Random,
) -> int:
    produced = 0
    if is_benchmark_gt_yaml(yaml_path):
        sample_dir = yaml_path.parents[1]
        out_dir = sample_dir / "injected"
    else:
        out_dir = output_root / sanitize_name(yaml_path.stem)
    out_dir.mkdir(parents=True, exist_ok=True)

    for _ in range(variants_per_yaml):
        variant_seed = seed_gen.randint(1, 10**9)
        result = inject_one_variant(
            source_yaml=yaml_path,
            output_dir=out_dir,
            variant_seed=variant_seed,
            allowed_errors=allowed_errors,
            min_slots=min_slots,
            max_slots=max_slots,
            generate_ppt=generate_ppt,
        )
        if result is None:
            continue

        target_yaml, target_ppt, mutations = result
        produced += 1
        print(f"  ✓ {yaml_path.name} -> {target_yaml.parent.name}")

        if is_benchmark_gt_yaml(yaml_path):
            dataset_root = find_dataset_root_from_yaml(yaml_path)
            if dataset_root:
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
    parser = argparse.ArgumentParser(description="Summary 槽位错误注入工具（v3）")
    parser.add_argument(
        "--benchmark-root",
        default="output/benchmark/dataset_v1",
        help="benchmark 数据集根目录（含 split/ 与 manifest/）",
    )
    parser.add_argument(
        "--split",
        default="test",
        help="要处理的 split 名称（benchmark 模式）",
    )
    parser.add_argument(
        "--source",
        nargs="+",
        default=None,
        help="直接指定 YAML 文件或 glob（指定后会覆盖 benchmark 扫描）",
    )
    parser.add_argument(
        "--output-dir",
        default="output/benchmark/_injected_misc",
        help="非 benchmark YAML 的输出目录",
    )
    parser.add_argument(
        "--variants-per-yaml",
        type=int,
        default=3,
        help="每个 YAML 生成多少个随机注入版本",
    )
    parser.add_argument(
        "--min-slots",
        type=int,
        default=1,
        help="单次注入最少修改槽位数",
    )
    parser.add_argument(
        "--max-slots",
        type=int,
        default=3,
        help="单次注入最多修改槽位数",
    )
    parser.add_argument(
        "--errors",
        nargs="+",
        choices=sorted(ERROR_MUTATORS.keys()),
        default=None,
        help="限制可用错误类型（默认按槽位自动选择）",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260306,
        help="随机种子（保证可复现）",
    )
    parser.add_argument(
        "--generate-ppt",
        action="store_true",
        help="注入后是否重建 PPT",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed_gen = random.Random(args.seed)  # noqa: S311 - benchmark 样本注入仅需可复现伪随机

    if args.min_slots <= 0 or args.max_slots <= 0:
        raise ValueError("min_slots / max_slots 必须为正整数")
    if args.min_slots > args.max_slots:
        raise ValueError("min_slots 不能大于 max_slots")
    if args.variants_per_yaml <= 0:
        raise ValueError("variants_per_yaml 必须大于 0")

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
        print(f"  槽位: {list(truth_slots.keys())}")
        produced = inject_for_yaml(
            yaml_path=yaml_file,
            output_root=output_root,
            variants_per_yaml=args.variants_per_yaml,
            min_slots=args.min_slots,
            max_slots=args.max_slots,
            allowed_errors=args.errors,
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
