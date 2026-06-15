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


def prioritized_rows(
    rows: list[dict[str, Any]], rng: random.Random
) -> list[dict[str, Any]]:
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


def load_recipes(path: Path) -> list[dict[str, Any]]:
    """Read and validate benchmark error recipes."""
    if not path.exists():
        raise FileNotFoundError(f"Recipe config not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("recipes"), list):
        raise ValueError(f"Recipe config must contain a recipes list: {path}")

    recipes: list[dict[str, Any]] = []
    for recipe in payload["recipes"]:
        if not isinstance(recipe, dict):
            raise ValueError(f"Recipe must be an object: {recipe}")
        samples_per_split = recipe.get("samples_per_split")
        max_variants_per_gt = recipe.get("max_variants_per_gt")
        max_variants_per_type = recipe.get("max_variants_per_type")
        for key, value in (
            ("samples_per_split", samples_per_split),
            ("max_variants_per_gt", max_variants_per_gt),
            ("max_variants_per_type", max_variants_per_type),
        ):
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"Recipe requires positive {key}: {recipe}")
        recipe_steps(recipe)
        recipes.append(recipe)
    return recipes


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
    recipes = load_recipes(args.recipe_config.resolve())

    resource_manager.load_all()
    manifest_path = dataset_root / "manifest" / "corruptions.jsonl"
    if manifest_path.exists():
        manifest_path.unlink()
    coverage: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_root": str(dataset_root),
        "created_at": now_iso(),
        "recipes": {},
    }
    produced_total = 0
    seed_gen = random.Random(args.seed)  # noqa: S311
    variants_per_gt_recipe: Counter[tuple[str, str, str]] = Counter()
    variants_per_gt_type: Counter[tuple[str, str, str, tuple[str, ...]]] = Counter()

    rows_by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_split[str(row.get("split"))].append(row)

    for split in args.splits:
        split_rows = rows_by_split.get(split, [])
        if not split_rows:
            continue
        for recipe in recipes:
            current_recipe_label = recipe_label(recipe)
            samples_per_split = int(recipe["samples_per_split"])
            max_variants_per_gt = int(recipe["max_variants_per_gt"])
            max_variants_per_type = int(recipe["max_variants_per_type"])
            produced = 0
            skips = Counter()
            template_hits = Counter()
            order_rng = random.Random(seed_gen.randint(1, 10**9))  # noqa: S311
            order = prioritized_rows(split_rows, order_rng)

            for row in order:
                sample_key = (split, str(row["sample_id"]), current_recipe_label)
                if variants_per_gt_recipe[sample_key] >= max_variants_per_gt:
                    continue
                if produced >= samples_per_split:
                    break
                attempt_limit = max(8, max_variants_per_gt * 8)
                row_produced = False
                for _ in range(attempt_limit):
                    if produced >= samples_per_split:
                        break
                    if variants_per_gt_recipe[sample_key] >= max_variants_per_gt:
                        break
                    blocked_signatures = {
                        signature
                        for key_split, key_sample, key_recipe, signature in variants_per_gt_type
                        if key_split == split
                        and key_sample == str(row["sample_id"])
                        and key_recipe == current_recipe_label
                        and variants_per_gt_type[
                            (key_split, key_sample, key_recipe, signature)
                        ]
                        >= max_variants_per_type
                    }
                    variant_seed = seed_gen.randint(1, 10**9)
                    try:
                        result = build_recipe_corruption(
                            dataset_root,
                            row,
                            recipe,
                            variant_seed,
                            disallow_signatures=blocked_signatures,
                        )
                        if result is None:
                            if not row_produced:
                                skips["not_applicable"] += 1
                            break
                        yaml_data, corruption, artifact_id = result
                        signature = mutation_signature(corruption["operations"])
                        signature_key = (*sample_key, signature)
                        if (
                            variants_per_gt_type[signature_key]
                            >= max_variants_per_type
                        ):
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
                        row_produced = True
                        template_hits[str(row.get("template_id", ""))] += 1
                        variants_per_gt_recipe[sample_key] += 1
                        variants_per_gt_type[signature_key] += 1
                    except Exception as exc:  # noqa: BLE001
                        skips[type(exc).__name__] += 1
                        break

            coverage["recipes"][f"{split}:{current_recipe_label}"] = {
                "produced": produced,
                "template_count": len(template_hits),
                "skips": dict(skips),
            }
            print(
                f"{split}/{current_recipe_label}: produced={produced}, "
                f"templates={len(template_hits)}, skips={dict(skips)}"
            )

    write_json(dataset_root / "manifest" / "corruption_coverage.json", coverage)
    print(f"Generated {produced_total} fine-grained corruptions")
