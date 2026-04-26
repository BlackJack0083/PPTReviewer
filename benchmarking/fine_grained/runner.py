from __future__ import annotations

import argparse
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from core import resource_manager
from engine.yaml_importer import rebuild_ppt_from_yaml
from utils.pptx_image_utils import convert_pptx_first_page_to_png

from .common import (
    DEFAULT_FAMILIES,
    SCHEMA_VERSION,
    append_jsonl,
    load_yaml,
    now_iso,
    read_jsonl,
    rel,
    save_yaml,
    write_json,
)
from .mutations import build_corruption


def load_sample_rows(dataset_root: Path, splits: list[str]) -> list[dict[str, Any]]:
    """读取指定 split 的 GT 样本记录；manifest 缺失时回退为扫描文件。"""
    manifest_rows = read_jsonl(dataset_root / "manifest" / "samples.jsonl")
    rows = []
    for row in manifest_rows:
        if row.get("split") not in splits:
            continue
        gt_yaml = dataset_root / row.get("gt_yaml", "")
        if gt_yaml.exists():
            rows.append(row)
    if rows:
        return rows

    for split in splits:
        for gt_yaml in sorted((dataset_root / "split" / split).glob("s_*/gt/slide.yaml")):
            sample_dir = gt_yaml.parents[1]
            rows.append(
                {
                    "sample_id": sample_dir.name.removeprefix("s_"),
                    "split": split,
                    "sample_dir": rel(sample_dir, dataset_root),
                    "gt_yaml": rel(gt_yaml, dataset_root),
                    "gt_ppt": rel(gt_yaml.with_suffix(".pptx"), dataset_root),
                    "template_id": load_yaml(gt_yaml).get("meta", {}).get("template_id", ""),
                }
            )
    return rows


def prioritized_rows(rows: list[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    """对样本排序，先保证每个模板被尝试一次，再补充随机样本。"""
    by_template: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_template[str(row.get("template_id", ""))].append(row)
    for group in by_template.values():
        rng.shuffle(group)

    first_pass = [group[0] for _, group in sorted(by_template.items()) if group]
    rest = [row for group in by_template.values() for row in group[1:]]
    rng.shuffle(rest)
    return first_pass + rest


def write_corruption_outputs(
    dataset_root: Path,
    sample_row: dict[str, Any],
    yaml_data: dict[str, Any],
    corruption: dict[str, Any],
    render_png: bool,
    skip_ppt: bool,
) -> dict[str, Any]:
    """写入 injected YAML/PPT/PNG 产物，并返回对应 manifest 记录。"""
    sample_dir = dataset_root / sample_row["sample_dir"]
    out_dir = sample_dir / "injected" / corruption["corruption_id"]
    output_yaml = out_dir / "slide.yaml"
    output_ppt = out_dir / "slide.pptx"
    output_png = out_dir / "slide.png"
    corruption_json = out_dir / "corruption.json"

    save_yaml(output_yaml, yaml_data)
    if not skip_ppt:
        rebuild_ppt_from_yaml(str(output_yaml), str(output_ppt))
        if render_png:
            convert_pptx_first_page_to_png(output_ppt, output_png)

    record = {
        **corruption,
        "split": sample_row.get("split"),
        "template_id": sample_row.get("template_id"),
        "layout_type": sample_row.get("layout_type"),
        "city_key": sample_row.get("city_key"),
        "source_yaml": sample_row["gt_yaml"],
        "source_ppt": sample_row.get("gt_ppt"),
        "output_yaml": rel(output_yaml, dataset_root),
        "output_ppt": rel(output_ppt, dataset_root) if output_ppt.exists() else None,
        "output_png": rel(output_png, dataset_root) if output_png.exists() else None,
        "corruption_json": rel(corruption_json, dataset_root),
    }
    write_json(corruption_json, record)
    return record


def parse_args() -> argparse.Namespace:
    """解析细粒度错误注入 CLI 参数。"""
    parser = argparse.ArgumentParser(description="Generate fine-grained PPT corruptions.")
    parser.add_argument("--benchmark-root", default="output/benchmark/dataset_v1")
    parser.add_argument("--splits", nargs="+", default=["train", "val", "test"])
    parser.add_argument("--families", nargs="+", choices=DEFAULT_FAMILIES, default=DEFAULT_FAMILIES)
    parser.add_argument("--samples-per-family-per-split", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260425)
    parser.add_argument("--render-png", action="store_true")
    parser.add_argument("--skip-ppt", action="store_true")
    return parser.parse_args()


def main() -> None:
    """执行细粒度错误注入，并写入 coverage 汇总。"""
    args = parse_args()
    if args.samples_per_family_per_split <= 0:
        raise ValueError("--samples-per-family-per-split must be positive")

    dataset_root = Path(args.benchmark_root).resolve()
    rows = load_sample_rows(dataset_root, args.splits)
    if not rows:
        raise FileNotFoundError(f"No GT samples found under {dataset_root}")

    resource_manager.load_all()
    manifest_path = dataset_root / "manifest" / "corruptions.jsonl"
    coverage: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_root": str(dataset_root),
        "created_at": now_iso(),
        "families": {},
    }
    produced_total = 0
    seed_gen = random.Random(args.seed)  # noqa: S311

    rows_by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_split[str(row.get("split"))].append(row)

    for split in args.splits:
        split_rows = rows_by_split.get(split, [])
        if not split_rows:
            continue
        for family in args.families:
            produced = 0
            skips = Counter()
            template_hits = Counter()
            order = prioritized_rows(split_rows, random.Random(seed_gen.randint(1, 10**9)))  # noqa: S311

            for row in order:
                if produced >= args.samples_per_family_per_split:
                    break
                variant_seed = seed_gen.randint(1, 10**9)
                try:
                    result = build_corruption(dataset_root, row, family, variant_seed)
                    if result is None:
                        skips["not_applicable"] += 1
                        continue
                    yaml_data, corruption = result
                    record = write_corruption_outputs(
                        dataset_root=dataset_root,
                        sample_row=row,
                        yaml_data=yaml_data,
                        corruption=corruption,
                        render_png=args.render_png,
                        skip_ppt=args.skip_ppt,
                    )
                    append_jsonl(manifest_path, record)
                    produced += 1
                    produced_total += 1
                    template_hits[str(row.get("template_id", ""))] += 1
                except Exception as exc:  # noqa: BLE001
                    skips[type(exc).__name__] += 1

            coverage["families"][f"{split}:{family}"] = {
                "produced": produced,
                "template_count": len(template_hits),
                "skips": dict(skips),
            }
            print(
                f"{split}/{family}: produced={produced}, "
                f"templates={len(template_hits)}, skips={dict(skips)}"
            )

    write_json(dataset_root / "manifest" / "corruption_coverage.json", coverage)
    print(f"Generated {produced_total} fine-grained corruptions")
