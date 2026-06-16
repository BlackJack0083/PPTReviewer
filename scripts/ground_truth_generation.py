#!/usr/bin/env python3
"""
Benchmark ground-truth 数据集生成脚本。

输出结构：
output/benchmark/dataset_v1/
  manifest/
    samples.jsonl
    eval_runs.jsonl
  split/<split>/s_<sample_id>/
    meta.json
    gt/slide.yaml
    gt/slide.pptx
    gt/slide.png            # 可选
    injected/
    eval/
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from tqdm.auto import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import ContextBuilder, layout_manager, resource_manager  # noqa: E402
from core.data_provider import RealEstateDataProvider  # noqa: E402
from engine import PPTGenerationEngine  # noqa: E402
from utils.pptx_image_utils import convert_pptx_first_page_to_png  # noqa: E402

GROUND_TRUTH_INPUT_DIR = PROJECT_ROOT / "config" / "benchmark" / "ground_truth_inputs"

CITY_CONFIGS = {
    "beijing": {
        "city": "Beijing",
        "new_house_table": "Beijing_new_house",
        "resale_house_table": None,
        "csv_file": GROUND_TRUTH_INPUT_DIR / "beijing.csv",
    },
    "guangzhou": {
        "city": "Guangzhou",
        "new_house_table": "Guangzhou_new_house",
        "resale_house_table": "Guangzhou_resale_house",
        "csv_file": GROUND_TRUTH_INPUT_DIR / "guangzhou.csv",
    },
    "shenzhen": {
        "city": "Shenzhen",
        "new_house_table": "Shenzhen_new_house",
        "resale_house_table": "Shenzhen_resale_house",
        "csv_file": GROUND_TRUTH_INPUT_DIR / "shenzhen.csv",
    },
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


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


def init_manifests(dataset_root: Path) -> dict[str, Path]:
    manifest_dir = dataset_root / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    return {
        "samples": manifest_dir / "samples.jsonl",
        "eval_runs": manifest_dir / "eval_runs.jsonl",
    }


def load_blocks_from_csv(csv_file: Path) -> list[str]:
    blocks: list[str] = []
    with open(csv_file, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            block = row.get("block", "").strip()
            if block:
                blocks.append(block)
    return blocks


def make_sample_id(
    city_key: str,
    block: str,
    template_id: str,
    start_year: str,
    end_year: str,
) -> str:
    raw = f"{city_key}|{block}|{template_id}|{start_year}|{end_year}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def resolve_templates(template_ids: list[str] | None) -> list[str]:
    if template_ids is None:
        template_ids = sorted(resource_manager.all_templates.keys())

    valid: list[str] = []
    for template_id in template_ids:
        if resource_manager.get_template(template_id):
            valid.append(template_id)
        else:
            logger.warning(f"模板不存在，跳过: {template_id}")
    return valid


def find_exported_yaml(gt_dir: Path) -> Path:
    candidates = [p for p in gt_dir.glob("*.yaml") if p.name != "slide.yaml"]
    if not candidates:
        raise RuntimeError(f"未找到导出的 YAML: {gt_dir}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def render_slide_png(
    pptx_path: Path,
    png_path: Path,
    dpi: int,
    backend: str,
    poppler_path: str | None,
) -> None:
    convert_pptx_first_page_to_png(
        pptx_path=pptx_path,
        output_png=png_path,
        dpi=dpi,
        backend=backend,
        poppler_path=poppler_path,
    )


def build_sample_record(
    dataset_root: Path,
    split: str,
    sample_id: str,
    city_key: str,
    city_name: str,
    table_name: str,
    block: str,
    template_id: str,
    start_year: str,
    end_year: str,
    gt_yaml: Path,
    gt_ppt: Path,
    gt_png: Path | None,
    created_at: str,
) -> dict[str, Any]:
    template_meta = resource_manager.get_template(template_id)
    if template_meta is None:
        raise ValueError(f"模板不存在: {template_id}")
    slide_size = layout_manager.get_slide_size(template_meta.layout_type)

    sample_dir = gt_yaml.parents[1]
    record = {
        "sample_id": sample_id,
        "split": split,
        "city_key": city_key,
        "city": city_name,
        "table": table_name,
        "block": block,
        "template_id": template_id,
        "layout_type": template_meta.layout_type.value,
        "slide_size": {
            "width": slide_size.width,
            "height": slide_size.height,
        },
        "start_year": start_year,
        "end_year": end_year,
        "sample_dir": str(sample_dir.relative_to(dataset_root)),
        "gt_yaml": str(gt_yaml.relative_to(dataset_root)),
        "gt_ppt": str(gt_ppt.relative_to(dataset_root)),
        "created_at": created_at,
    }
    if gt_png is not None and gt_png.exists():
        record["gt_png"] = str(gt_png.relative_to(dataset_root))
    return record


def load_existing_sample_records(samples_manifest: Path) -> dict[str, dict[str, Any]]:
    records_by_id: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(samples_manifest):
        sample_id = str(row.get("sample_id", "")).strip()
        if sample_id:
            records_by_id[sample_id] = row
    return records_by_id


def build_tasks(
    city_keys: list[str],
    templates: list[str],
    max_blocks_per_city: int | None,
    max_samples: int | None,
) -> list[dict[str, str]]:
    tasks: list[dict[str, str]] = []
    for city_key in city_keys:
        config = CITY_CONFIGS[city_key]
        blocks = load_blocks_from_csv(config["csv_file"])
        if max_blocks_per_city is not None:
            blocks = blocks[:max_blocks_per_city]

        logger.info(
            "处理城市 {}: blocks={} templates={}",
            config["city"],
            len(blocks),
            len(templates),
        )

        for block in blocks:
            for template_id in templates:
                table_name = table_name_for_template(city_key, template_id)
                if table_name is None:
                    logger.info(
                        "跳过缺少数据表的组合: city={} template={}",
                        config["city"],
                        template_id,
                    )
                    continue
                tasks.append(
                    {
                        "city_key": city_key,
                        "city_name": config["city"],
                        "table_name": table_name,
                        "block": block,
                        "template_id": template_id,
                    }
                )
                if max_samples is not None and len(tasks) >= max_samples:
                    return tasks

    return tasks


def table_name_for_template(city_key: str, template_id: str) -> str | None:
    config = CITY_CONFIGS[city_key]
    template_meta = resource_manager.get_template(template_id)
    if template_meta is None:
        raise ValueError(f"模板不存在: {template_id}")
    if template_requires_resale_table(template_meta.data_keys):
        return config["resale_house_table"]
    return config["new_house_table"]


def template_requires_resale_table(data_keys: dict[str, str]) -> bool:
    return any(data_key.startswith("resale_") for data_key in data_keys.values())


def generate_one_sample(
    dataset_root: Path,
    split: str,
    city_key: str,
    city_name: str,
    table_name: str,
    block: str,
    template_id: str,
    start_year: str,
    end_year: str,
    skip_existing: bool,
    render_png_enabled: bool,
    render_dpi: int,
    render_backend: str,
    poppler_path: str | None,
) -> tuple[bool, str, dict[str, Any] | None]:
    sample_id = make_sample_id(city_key, block, template_id, start_year, end_year)
    sample_dir = dataset_root / "split" / split / f"s_{sample_id}"
    gt_dir = sample_dir / "gt"
    injected_dir = sample_dir / "injected"
    eval_dir = sample_dir / "eval"
    gt_dir.mkdir(parents=True, exist_ok=True)
    injected_dir.mkdir(parents=True, exist_ok=True)
    eval_dir.mkdir(parents=True, exist_ok=True)

    gt_yaml = gt_dir / "slide.yaml"
    gt_ppt = gt_dir / "slide.pptx"
    gt_png = gt_dir / "slide.png"
    meta_path = sample_dir / "meta.json"

    if skip_existing and gt_yaml.exists() and gt_ppt.exists():
        if render_png_enabled and not gt_png.exists():
            render_slide_png(
                pptx_path=gt_ppt,
                png_path=gt_png,
                dpi=render_dpi,
                backend=render_backend,
                poppler_path=poppler_path,
            )

        created_at = now_iso()
        if meta_path.exists():
            with open(meta_path, encoding="utf-8") as f:
                meta_data = json.load(f)
            created_at = str(meta_data["created_at"])

        record = build_sample_record(
            dataset_root=dataset_root,
            split=split,
            sample_id=sample_id,
            city_key=city_key,
            city_name=city_name,
            table_name=table_name,
            block=block,
            template_id=template_id,
            start_year=start_year,
            end_year=end_year,
            gt_yaml=gt_yaml,
            gt_ppt=gt_ppt,
            gt_png=gt_png if render_png_enabled else None,
            created_at=created_at,
        )
        write_json(meta_path, record)
        return True, "skipped", record

    try:
        template_meta = resource_manager.get_template(template_id)
        if template_meta is None:
            raise ValueError(f"模板不存在: {template_id}")

        provider = RealEstateDataProvider(
            city_name,
            block,
            start_year,
            end_year,
            table_name,
        )
        context = ContextBuilder.build_context(
            template_meta=template_meta,
            provider=provider,
            city=city_name,
            block=block,
            start_year=start_year,
            end_year=end_year,
        )

        engine = PPTGenerationEngine(str(gt_ppt))
        engine.generate_single_slide(template_id, context)

        exported_yaml = find_exported_yaml(gt_dir)
        if gt_yaml.exists():
            gt_yaml.unlink()
        exported_yaml.rename(gt_yaml)

        for extra_yaml in gt_dir.glob("*.yaml"):
            if extra_yaml != gt_yaml:
                extra_yaml.unlink()

        if render_png_enabled:
            render_slide_png(
                pptx_path=gt_ppt,
                png_path=gt_png,
                dpi=render_dpi,
                backend=render_backend,
                poppler_path=poppler_path,
            )
        elif gt_png.exists():
            gt_png.unlink()

        created_at = now_iso()
        record = build_sample_record(
            dataset_root=dataset_root,
            split=split,
            sample_id=sample_id,
            city_key=city_key,
            city_name=city_name,
            table_name=table_name,
            block=block,
            template_id=template_id,
            start_year=start_year,
            end_year=end_year,
            gt_yaml=gt_yaml,
            gt_ppt=gt_ppt,
            gt_png=gt_png if render_png_enabled else None,
            created_at=created_at,
        )
        write_json(meta_path, record)
        return True, "generated", record

    except Exception as exc:
        logger.error(
            f"生成失败: city={city_name}, block={block}, template={template_id}, error={exc}"
        )
        logger.debug(traceback.format_exc())
        return False, "failed", None


def precheck_one_sample(
    city_name: str,
    table_name: str,
    block: str,
    template_id: str,
    start_year: str,
    end_year: str,
) -> tuple[bool, str | None]:
    """用临时目录跑完整的单样本生成链路，但不保留产物。"""
    try:
        template_meta = resource_manager.get_template(template_id)
        if template_meta is None:
            raise ValueError(f"模板不存在: {template_id}")

        provider = RealEstateDataProvider(
            city_name,
            block,
            start_year,
            end_year,
            table_name,
        )
        context = ContextBuilder.build_context(
            template_meta=template_meta,
            provider=provider,
            city=city_name,
            block=block,
            start_year=start_year,
            end_year=end_year,
        )

        with tempfile.TemporaryDirectory(prefix="gt_precheck_") as temp_dir:
            temp_ppt = Path(temp_dir) / "slide.pptx"
            PPTGenerationEngine(str(temp_ppt)).generate_single_slide(
                template_id, context
            )

        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成 benchmark GT 样本"
    )
    parser.add_argument(
        "--dataset-root",
        default="output/benchmark/dataset_v1",
        help="输出数据集根目录",
    )
    parser.add_argument(
        "--split",
        default="test",
        help="输出 split 名称",
    )
    parser.add_argument(
        "--cities",
        nargs="+",
        default=["beijing", "guangzhou", "shenzhen"],
        help=f"城市键列表，可选: {', '.join(CITY_CONFIGS.keys())}",
    )
    parser.add_argument(
        "--templates",
        nargs="+",
        default=None,
        help="模板 ID 列表；不传则使用当前全部模板",
    )
    parser.add_argument(
        "--start-year",
        default="2020",
        help="起始年份",
    )
    parser.add_argument(
        "--end-year",
        default="2024",
        help="结束年份",
    )
    parser.add_argument(
        "--max-blocks-per-city",
        type=int,
        default=None,
        help="每个城市最多处理多少个 block（默认不限制）",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="全局最多生成多少个样本（默认不限制）",
    )
    parser.add_argument(
        "--clean-dataset",
        action="store_true",
        help="开始前删除 dataset-root（谨慎使用）",
    )
    parser.add_argument(
        "--precheck-only",
        action="store_true",
        help="仅做预检查：完整跑单样本生成链路，但不写正式数据集",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="若 gt/slide.yaml 和 gt/slide.pptx 都存在则跳过重建",
    )
    parser.add_argument(
        "--render-png",
        action="store_true",
        help="同时生成 gt/slide.png，便于后续评测直接使用",
    )
    parser.add_argument(
        "--render-dpi",
        type=int,
        default=200,
        help="生成 PNG 时的 DPI",
    )
    parser.add_argument(
        "--render-backend",
        choices=["auto", "windows", "libreoffice"],
        default="auto",
        help="PPT 转 PNG 的后端",
    )
    parser.add_argument(
        "--poppler-path",
        default=None,
        help="Windows 下 pdf2image 可选的 poppler bin 路径",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset_root = Path(args.dataset_root).resolve()

    invalid_cities = [c for c in args.cities if c not in CITY_CONFIGS]
    if invalid_cities:
        raise ValueError(
            f"无效城市: {invalid_cities}, 可选: {list(CITY_CONFIGS.keys())}"
        )

    if args.clean_dataset and args.precheck_only:
        raise ValueError("--clean-dataset 不能与 --precheck-only 同时使用")

    if args.clean_dataset and dataset_root.exists():
        shutil.rmtree(dataset_root)

    resource_manager.load_all()
    templates = resolve_templates(args.templates)
    if not templates:
        raise ValueError("没有可用模板，请检查 --templates 参数")

    manifests: dict[str, Path] | None = None
    samples_records: dict[str, dict[str, Any]] = {}
    if not args.precheck_only:
        manifests = init_manifests(dataset_root)
        manifests["eval_runs"].touch(exist_ok=True)
        samples_records = load_existing_sample_records(manifests["samples"])

    logger.info(
        "开始执行{}",
        "benchmark GT 预检查" if args.precheck_only else "benchmark GT 生成",
    )
    if not args.precheck_only:
        logger.info("dataset_root: {}", dataset_root)
    logger.info("split: {}", args.split)
    logger.info("cities: {}", args.cities)
    logger.info("templates: {}", templates)
    logger.info("time_range: {}-{}", args.start_year, args.end_year)
    if not args.precheck_only:
        logger.info("render_png: {}", args.render_png)

    stats = {
        "total": 0,
        "generated": 0,
        "skipped": 0,
        "failed": 0,
    }
    tasks = build_tasks(
        city_keys=args.cities,
        templates=templates,
        max_blocks_per_city=args.max_blocks_per_city,
        max_samples=args.max_samples,
    )

    with tqdm(
        tasks,
        desc="precheck" if args.precheck_only else "gt",
        unit="sample",
    ) as progress:
        for task in progress:
            stats["total"] += 1
            city_key = task["city_key"]
            city_name = task["city_name"]
            table_name = task["table_name"]
            block = task["block"]
            template_id = task["template_id"]

            progress.set_postfix_str(f"{city_name}/{block}/{template_id}")

            if args.precheck_only:
                ok, error = precheck_one_sample(
                    city_name=city_name,
                    table_name=table_name,
                    block=block,
                    template_id=template_id,
                    start_year=args.start_year,
                    end_year=args.end_year,
                )
                if ok:
                    stats["generated"] += 1
                    logger.info("[OK] {} | {} | {}", city_name, block, template_id)
                else:
                    stats["failed"] += 1
                    logger.error(
                        "[FAIL] {} | {} | {} | {}", city_name, block, template_id, error
                    )
            else:
                ok, status, record = generate_one_sample(
                    dataset_root=dataset_root,
                    split=args.split,
                    city_key=city_key,
                    city_name=city_name,
                    table_name=table_name,
                    block=block,
                    template_id=template_id,
                    start_year=args.start_year,
                    end_year=args.end_year,
                    skip_existing=args.skip_existing,
                    render_png_enabled=args.render_png,
                    render_dpi=args.render_dpi,
                    render_backend=args.render_backend,
                    poppler_path=args.poppler_path,
                )

                if ok and record is not None:
                    if status == "generated":
                        stats["generated"] += 1
                    elif status == "skipped":
                        stats["skipped"] += 1
                    samples_records[record["sample_id"]] = record
                    logger.info(
                        "[{}] s_{} | {} | {} | {}x{}",
                        status.upper(),
                        record["sample_id"],
                        record["block"],
                        record["template_id"],
                        record["slide_size"]["width"],
                        record["slide_size"]["height"],
                    )
                else:
                    stats["failed"] += 1

    if not args.precheck_only and manifests is not None:
        write_jsonl(
            manifests["samples"],
            sorted(samples_records.values(), key=lambda row: row["sample_id"]),
        )

    logger.info("{}完成", "GT 预检查" if args.precheck_only else "GT 生成")
    logger.info(
        "总任务={} 生成={} 跳过={} 失败={}",
        stats["total"],
        stats["generated"],
        stats["skipped"],
        stats["failed"],
    )
    if not args.precheck_only and manifests is not None:
        logger.info("samples manifest: {}", manifests["samples"])

if __name__ == "__main__":
    main()
