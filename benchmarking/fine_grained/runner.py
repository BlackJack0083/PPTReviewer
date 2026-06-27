from __future__ import annotations

import argparse
import copy
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from core import resource_manager
from engine.data_files import (
    data_elements,
    resolve_element_data_path,
    write_dataframe_csv,
)
from engine.yaml_importer import rebuild_ppt_from_yaml
from utils.pptx_image_utils import convert_pptx_first_page_to_png

from .common import (
    SCHEMA_VERSION,
    append_jsonl,
    now_iso,
    read_jsonl,
    rel,
    save_yaml,
    write_json,
)
from .mutations import (
    build_recipe_corruption,
    mutation_signature,
    recipe_label,
    recipe_steps,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECIPE_CONFIG = PROJECT_ROOT / "config" / "benchmark" / "error_recipes.yaml"


def load_sample_rows(dataset_root: Path, splits: list[str]) -> list[dict[str, Any]]:
    """读取指定 split 的 GT 样本记录。"""
    manifest_rows = read_jsonl(dataset_root / "manifest" / "samples.jsonl")
    rows = []
    for row in manifest_rows:
        if row.get("split") not in splits:
            continue
        gt_yaml = dataset_root / row.get("gt_yaml", "")
        if gt_yaml.exists():
            rows.append(row)
    return rows


def load_recipes(path: Path) -> dict[str, Any]:
    """Read and validate sample-centric benchmark corruption config."""
    if not path.exists():
        raise FileNotFoundError(f"Recipe config not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Recipe config must be an object: {path}")
    variants_by_split = payload.get("variants_by_split")
    recipe_pool = payload.get("recipe_pool")
    if not isinstance(variants_by_split, dict) or not variants_by_split:
        raise ValueError(f"Recipe config must contain variants_by_split: {path}")
    if not isinstance(recipe_pool, list) or not recipe_pool:
        raise ValueError(f"Recipe config must contain recipe_pool: {path}")
    for split, count in variants_by_split.items():
        if not isinstance(split, str) or not isinstance(count, int) or count <= 0:
            raise ValueError(f"Invalid variants_by_split entry: {variants_by_split}")

    recipes: list[dict[str, Any]] = []
    for recipe in recipe_pool:
        if not isinstance(recipe, dict):
            raise ValueError(f"Recipe must be an object: {recipe}")
        recipe_steps(recipe)
        recipes.append(recipe)
    return {"variants_by_split": variants_by_split, "recipe_pool": recipes}


def write_corruption_outputs(
    dataset_root: Path,
    sample_row: dict[str, Any],
    yaml_data: dict[str, Any],
    corruption: dict[str, Any],
    artifact_id: str,
    render_ppt: bool,
    render_png: bool,
) -> dict[str, Any]:
    """写入 injected YAML/PPT/PNG 产物，并返回对应 manifest 记录。"""
    sample_dir = dataset_root / sample_row["sample_dir"]
    out_dir = sample_dir / "injected" / artifact_id
    output_yaml = out_dir / "slide.yaml"
    output_ppt = out_dir / "slide.pptx"
    output_png = out_dir / "slide.png"
    corruption_json = out_dir / "corruption.json"

    output_data = prepare_output_yaml_data(
        yaml_data=yaml_data,
        source_yaml=dataset_root / sample_row["gt_yaml"],
        output_yaml=output_yaml,
    )
    save_yaml(output_yaml, output_data)
    if render_ppt or render_png:
        if output_ppt.exists():
            output_ppt.unlink()
        rebuild_ppt_from_yaml(str(output_yaml), str(output_ppt))
        if render_png:
            convert_pptx_first_page_to_png(output_ppt, output_png)
        if render_png and not render_ppt and output_ppt.exists():
            output_ppt.unlink()

    record = {
        **corruption,
        "sample_id": sample_row.get("sample_id"),
        "injection_id": artifact_id,
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
    write_json(corruption_json, corruption)
    return record


def prepare_output_yaml_data(
    yaml_data: dict[str, Any],
    source_yaml: Path,
    output_yaml: Path,
) -> dict[str, Any]:
    """Copy or materialize element-level CSV data for an injected slide YAML."""
    result = copy.deepcopy(yaml_data)
    result.pop("_source_yaml_path", None)
    source_yaml = source_yaml.resolve()

    for element in data_elements(result):
        override = element.pop("_dataframe_override", None)
        source_data = resolve_element_data_path(source_yaml, element)
        target_data = resolve_element_data_path(output_yaml, element)
        if override is not None:
            write_dataframe_csv(override, target_data)
            continue
        if not source_data.exists():
            raise FileNotFoundError(f"Missing source data CSV: {source_data}")
        target_data.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_data, target_data)

    return result


def parse_args() -> argparse.Namespace:
    """解析细粒度错误注入 CLI 参数。"""
    parser = argparse.ArgumentParser(
        description="Generate fine-grained PPT corruptions."
    )
    parser.add_argument("--benchmark-root", default="output/benchmark/dataset_v1")
    parser.add_argument("--splits", nargs="+", default=["train", "val", "test"])
    parser.add_argument(
        "--recipe-config",
        type=Path,
        default=DEFAULT_RECIPE_CONFIG,
        help="YAML file defining error recipes and generation counts.",
    )
    parser.add_argument("--seed", type=int, default=20260425)
    parser.add_argument("--render-ppt", action="store_true")
    parser.add_argument("--render-png", action="store_true")
    return parser.parse_args()


def main() -> None:
    """执行细粒度错误注入，并写入 coverage 汇总。"""
    args = parse_args()

    dataset_root = Path(args.benchmark_root).resolve()
    rows = load_sample_rows(dataset_root, args.splits)
    if not rows:
        raise FileNotFoundError(f"No GT samples found under {dataset_root}")
    recipe_config = load_recipes(args.recipe_config.resolve())
    variants_by_split = recipe_config["variants_by_split"]
    recipe_pool = recipe_config["recipe_pool"]

    resource_manager.load_all()
    manifest_path = dataset_root / "manifest" / "corruptions.jsonl"
    if manifest_path.exists():
        manifest_path.unlink()
    coverage: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_root": str(dataset_root),
        "created_at": now_iso(),
        "variants_by_split": dict(variants_by_split),
        "recipe_pool": [recipe_steps(recipe) for recipe in recipe_pool],
        "splits": {},
    }
    produced_total = 0
    variants_per_gt_signature: Counter[tuple[str, str, tuple[str, ...]]] = Counter()

    rows_by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_split[str(row.get("split"))].append(row)

    for split in args.splits:
        split_rows = rows_by_split.get(split, [])
        if not split_rows:
            continue
        if split not in variants_by_split:
            raise ValueError(f"Recipe config missing variants_by_split for {split}")
        target_variants = int(variants_by_split[split])

        produced = 0
        skips = Counter()
        template_hits = Counter()
        city_hits = Counter()
        recipe_hits = Counter()
        sample_produced = Counter()

        for row in sorted(split_rows, key=lambda item: str(item["sample_id"])):
            sample_id = str(row["sample_id"])
            sample_rng = random.Random(f"{args.seed}|{split}|{sample_id}")  # noqa: S311
            recipe_order = list(recipe_pool)
            sample_rng.shuffle(recipe_order)
            recipe_index = 0

            while sample_produced[sample_id] < target_variants:
                if recipe_index >= len(recipe_order):
                    skips["recipe_pool_exhausted"] += 1
                    break

                recipe = recipe_order[recipe_index]
                recipe_index += 1
                blocked_signatures = {
                    signature
                    for key_split, key_sample, signature in variants_per_gt_signature
                    if key_split == split and key_sample == sample_id
                }
                result = build_recipe_corruption(
                    dataset_root,
                    row,
                    recipe,
                    sample_rng.randint(1, 10**9),
                    disallow_signatures=blocked_signatures,
                )
                if result is None:
                    skips[f"{recipe_label(recipe)}:not_applicable"] += 1
                    continue

                yaml_data, corruption, artifact_id = result
                signature = mutation_signature(corruption["operations"])
                signature_key = (split, sample_id, signature)
                if variants_per_gt_signature[signature_key]:
                    skips[f"{recipe_label(recipe)}:duplicate_signature"] += 1
                    continue

                record = write_corruption_outputs(
                    dataset_root=dataset_root,
                    sample_row=row,
                    yaml_data=yaml_data,
                    corruption=corruption,
                    artifact_id=artifact_id,
                    render_ppt=args.render_ppt,
                    render_png=args.render_png,
                )
                append_jsonl(manifest_path, record)
                produced += 1
                produced_total += 1
                sample_produced[sample_id] += 1
                variants_per_gt_signature[signature_key] += 1
                template_hits[str(row.get("template_id", ""))] += 1
                city_hits[str(row.get("city_key", ""))] += 1
                recipe_hits[recipe_label(recipe)] += 1

        coverage["splits"][split] = {
            "samples": len(split_rows),
            "target_variants_per_sample": target_variants,
            "target_total": len(split_rows) * target_variants,
            "produced": produced,
            "samples_with_full_variants": sum(
                sample_produced[str(row["sample_id"])] >= target_variants
                for row in split_rows
            ),
            "template_count": len(template_hits),
            "city_count": len(city_hits),
            "recipes": dict(sorted(recipe_hits.items())),
            "skips": dict(sorted(skips.items())),
        }
        print(
            f"{split}: produced={produced}/{len(split_rows) * target_variants}, "
            f"samples={len(split_rows)}, templates={len(template_hits)}, "
            f"skips={dict(skips)}"
        )

    write_json(dataset_root / "manifest" / "corruption_coverage.json", coverage)
    print(f"Generated {produced_total} fine-grained corruptions")
