#!/usr/bin/env python3
"""Split an existing benchmark dataset into train/val/test partitions."""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SPLIT_ORDER = ("train", "val", "test")
KNOWN_PATH_FIELDS = {
    "sample_dir",
    "gt_yaml",
    "gt_ppt",
    "gt_png",
    "source_yaml",
    "output_yaml",
    "output_ppt",
}


def read_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_ratios(train_ratio: float, val_ratio: float, test_ratio: float) -> dict[str, float]:
    total = train_ratio + val_ratio + test_ratio
    if total <= 0:
        raise ValueError("Split ratios must sum to a positive number.")
    return {
        "train": train_ratio / total,
        "val": val_ratio / total,
        "test": test_ratio / total,
    }


def allocate_counts(size: int, ratios: dict[str, float]) -> dict[str, int]:
    raw = {split: size * ratio for split, ratio in ratios.items()}
    counts = {split: int(value) for split, value in raw.items()}
    remainder = size - sum(counts.values())
    ranked = sorted(
        SPLIT_ORDER,
        key=lambda split: (raw[split] - counts[split], ratios[split]),
        reverse=True,
    )
    for split in ranked[:remainder]:
        counts[split] += 1
    return counts


def assign_splits(
    sample_rows: list[dict[str, Any]],
    seed: int,
) -> dict[str, str]:
    ratios = normalize_ratios(0.6, 0.2, 0.2)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in sample_rows:
        grouped[(row["city_key"], row["template_id"])].append(row)

    rng = random.Random(seed)  # noqa: S311 - deterministic dataset split
    assignments: dict[str, str] = {}
    for group_key, rows in grouped.items():
        shuffled = list(rows)
        rng.shuffle(shuffled)
        counts = allocate_counts(len(shuffled), ratios)
        cursor = 0
        for split in SPLIT_ORDER:
            for row in shuffled[cursor : cursor + counts[split]]:
                assignments[row["sample_id"]] = split
            cursor += counts[split]
        if cursor != len(shuffled):
            raise RuntimeError(f"Split allocation mismatch for group {group_key}")
    return assignments


def replace_prefix(value: str, old_prefix: str, new_prefix: str) -> str:
    if value.startswith(old_prefix):
        return new_prefix + value[len(old_prefix) :]
    return value


def rewrite_record_paths(record: dict[str, Any], old_prefix: str, new_prefix: str) -> dict[str, Any]:
    updated = dict(record)
    for key in KNOWN_PATH_FIELDS:
        value = updated.get(key)
        if isinstance(value, str):
            updated[key] = replace_prefix(value, old_prefix, new_prefix)
    return updated


def sample_prefix(split: str, sample_id: str) -> str:
    return f"split/{split}/s_{sample_id}"


def update_sample_record(row: dict[str, Any], new_split: str) -> dict[str, Any]:
    old_split = row["split"]
    sample_id = row["sample_id"]
    old_prefix = sample_prefix(old_split, sample_id)
    new_prefix = sample_prefix(new_split, sample_id)
    updated = rewrite_record_paths(row, old_prefix, new_prefix)
    updated["split"] = new_split
    return updated


def update_injection_record(row: dict[str, Any], old_split: str, new_split: str) -> dict[str, Any]:
    sample_id = row["sample_id"]
    old_prefix = sample_prefix(old_split, sample_id)
    new_prefix = sample_prefix(new_split, sample_id)
    updated = rewrite_record_paths(row, old_prefix, new_prefix)
    updated["split"] = new_split
    return updated


def remove_eval_dir(sample_dir: Path, apply: bool) -> bool:
    eval_dir = sample_dir / "eval"
    if not eval_dir.exists():
        return False
    if apply:
        shutil.rmtree(eval_dir)
    return True


def relocate_sample_dir(dataset_root: Path, sample_id: str, old_split: str, new_split: str, apply: bool) -> tuple[Path, Path]:
    old_dir = dataset_root / sample_prefix(old_split, sample_id)
    new_dir = dataset_root / sample_prefix(new_split, sample_id)
    if not old_dir.exists():
        raise FileNotFoundError(f"Missing sample directory: {old_dir}")

    if old_dir == new_dir:
        return old_dir, new_dir

    if apply:
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        if new_dir.exists():
            raise FileExistsError(f"Target sample directory already exists: {new_dir}")
        shutil.move(str(old_dir), str(new_dir))
    return old_dir, new_dir


def update_sample_meta(sample_dir: Path, record: dict[str, Any], apply: bool) -> bool:
    meta_path = sample_dir / "meta.json"
    if not meta_path.exists():
        return False
    if apply:
        write_json(meta_path, record)
    return True


def update_injected_meta_files(
    sample_dir: Path,
    old_split: str,
    new_split: str,
    sample_id: str,
    apply: bool,
) -> int:
    injected_root = sample_dir / "injected"
    if not injected_root.exists():
        return 0

    updated_count = 0
    for meta_path in injected_root.glob("*/inject_meta.json"):
        data = read_json(meta_path)
        updated = update_injection_record(data, old_split=old_split, new_split=new_split)
        if apply:
            write_json(meta_path, updated)
        updated_count += 1
    return updated_count


def print_summary(
    sample_rows: list[dict[str, Any]],
    assignments: dict[str, str],
    injection_rows: list[dict[str, Any]],
) -> None:
    split_counts = Counter(assignments.values())
    print("Planned sample split counts:")
    for split in SPLIT_ORDER:
        print(f"  {split}: {split_counts.get(split, 0)}")

    template_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in sample_rows:
        template_counts[row["template_id"]][assignments[row["sample_id"]]] += 1
    print("\nPer-template split snapshot:")
    for template_id in sorted(template_counts):
        counts = template_counts[template_id]
        print(
            f"  {template_id}: "
            f"train={counts.get('train', 0)} "
            f"val={counts.get('val', 0)} "
            f"test={counts.get('test', 0)}"
        )

    if injection_rows:
        inj_counts = Counter(assignments[row["sample_id"]] for row in injection_rows if row["sample_id"] in assignments)
        print("\nPlanned injection split counts:")
        for split in SPLIT_ORDER:
            print(f"  {split}: {inj_counts.get(split, 0)}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split benchmark dataset into train/val/test.")
    parser.add_argument(
        "--dataset-root",
        required=True,
        help="Benchmark dataset root, e.g. output/benchmark/dataset_20260407",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260410,
        help="Random seed for deterministic stratified split.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes in place. Without this flag the script only prints the plan.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    dataset_root = Path(args.dataset_root).resolve()
    samples_manifest = dataset_root / "manifest" / "samples.jsonl"
    injections_manifest = dataset_root / "manifest" / "injections.jsonl"

    sample_rows = read_jsonl(samples_manifest)
    if not sample_rows:
        raise ValueError(f"No sample rows found in {samples_manifest}")

    assignments = assign_splits(sample_rows, seed=args.seed)
    injection_rows = read_jsonl(injections_manifest)
    print_summary(sample_rows, assignments, injection_rows)

    if not args.apply:
        print("\nDry run only. Re-run with --apply to modify the dataset in place.")
        return

    updated_samples: list[dict[str, Any]] = []
    updated_injections: list[dict[str, Any]] = []
    eval_removed = 0
    inject_meta_updated = 0

    sample_rows_by_id = {row["sample_id"]: row for row in sample_rows}
    for row in sample_rows:
        sample_id = row["sample_id"]
        old_split = row["split"]
        new_split = assignments[sample_id]
        _, new_sample_dir = relocate_sample_dir(
            dataset_root=dataset_root,
            sample_id=sample_id,
            old_split=old_split,
            new_split=new_split,
            apply=True,
        )

        if remove_eval_dir(new_sample_dir, apply=True):
            eval_removed += 1

        updated_row = update_sample_record(row, new_split=new_split)
        updated_samples.append(updated_row)
        update_sample_meta(new_sample_dir, updated_row, apply=True)
        inject_meta_updated += update_injected_meta_files(
            sample_dir=new_sample_dir,
            old_split=old_split,
            new_split=new_split,
            sample_id=sample_id,
            apply=True,
        )

    for row in injection_rows:
        sample_id = row["sample_id"]
        sample_row = sample_rows_by_id.get(sample_id)
        if sample_row is None:
            updated_injections.append(row)
            continue
        updated_injections.append(
            update_injection_record(
                row,
                old_split=sample_row["split"],
                new_split=assignments[sample_id],
            )
        )

    write_jsonl(samples_manifest, updated_samples)
    write_jsonl(injections_manifest, updated_injections)

    print("\nApplied changes:")
    print(f"  samples updated: {len(updated_samples)}")
    print(f"  injections updated: {len(updated_injections)}")
    print(f"  eval directories removed: {eval_removed}")
    print(f"  inject_meta files updated: {inject_meta_updated}")


if __name__ == "__main__":
    main()
