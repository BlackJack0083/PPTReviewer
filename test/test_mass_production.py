#!/usr/bin/env python3
"""
Benchmark 数据集生成脚本（阶段 1: GT）

输出结构：
output/benchmark/dataset_v1/
  manifest/
    samples.jsonl
    injections.jsonl
    eval_runs.jsonl
  split/test/s_<sample_id>/
    meta.json
    gt/slide.yaml
    gt/slide.pptx
    injected/
    eval/
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import ContextBuilder, resource_manager  # noqa: E402
from core.data_provider import RealEstateDataProvider  # noqa: E402
from engine import PPTGenerationEngine  # noqa: E402

CITY_CONFIGS = {
    "beijing": {
        "city": "Beijing",
        "table": "Beijing_new_house",
        "csv_file": PROJECT_ROOT / "test" / "beijing.csv",
    },
    "guangzhou": {
        "city": "Guangzhou",
        "table": "Guangzhou_new_house",
        "csv_file": PROJECT_ROOT / "test" / "guangzhou.csv",
    },
    "shenzhen": {
        "city": "Shenzhen",
        "table": "Shenzhen_new_house",
        "csv_file": PROJECT_ROOT / "test" / "shenzhen.csv",
    },
}

DEFAULT_TEMPLATES = [
    # "T01_Supply_Trans_Bar",
    # "T01_Supply_Trans_Line",
    "T02_Cross_Pivot_Table",
    # "T02_Area_Dist_Bar",
    # "T02_Area_Dist_Line",
    # "T02_Price_Dist_Bar",
    # "T02_Price_Dist_Line",
    # "T02_Double_Price_Dist_Line",
    # "T02_Double_Price_Dist_Bar",
    # "T04_Annual_Supply_Demand_Bar",
    # "T04_Annual_Supply_Demand_Line",
    # "T04_Supply_Transaction_Area_Bar",
    # "T04_Supply_Transaction_Area_Line",
]


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


def init_manifests(dataset_root: Path, append_samples_manifest: bool) -> dict[str, Path]:
    manifest_dir = dataset_root / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    samples_path = manifest_dir / "samples.jsonl"
    injections_path = manifest_dir / "injections.jsonl"
    eval_runs_path = manifest_dir / "eval_runs.jsonl"

    if append_samples_manifest:
        samples_path.touch(exist_ok=True)
    else:
        samples_path.write_text("", encoding="utf-8")

    injections_path.touch(exist_ok=True)
    eval_runs_path.touch(exist_ok=True)

    return {
        "samples": samples_path,
        "injections": injections_path,
        "eval_runs": eval_runs_path,
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
    city_key: str, block: str, template_id: str, start_year: str, end_year: str
) -> str:
    raw = f"{city_key}|{block}|{template_id}|{start_year}|{end_year}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest[:16]


def resolve_templates(template_ids: list[str]) -> list[str]:
    valid: list[str] = []
    for template_id in template_ids:
        if resource_manager.get_template(template_id):
            valid.append(template_id)
        else:
            logger.warning(f"模板不存在，跳过: {template_id}")
    return valid


def find_exported_yaml(gt_dir: Path) -> Path | None:
    candidates = [p for p in gt_dir.glob("*.yaml") if p.name != "slide.yaml"]
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    fallback = gt_dir / "slide.yaml"
    if fallback.exists():
        return fallback
    return None


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
    created_at: str,
) -> dict[str, Any]:
    sample_dir = gt_yaml.parents[1]
    return {
        "sample_id": sample_id,
        "split": split,
        "city_key": city_key,
        "city": city_name,
        "table": table_name,
        "block": block,
        "template_id": template_id,
        "start_year": start_year,
        "end_year": end_year,
        "sample_dir": str(sample_dir.relative_to(dataset_root)),
        "gt_yaml": str(gt_yaml.relative_to(dataset_root)),
        "gt_ppt": str(gt_ppt.relative_to(dataset_root)),
        "created_at": created_at,
    }


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
    meta_path = sample_dir / "meta.json"

    if skip_existing and gt_yaml.exists() and gt_ppt.exists():
        created_at = now_iso()
        if meta_path.exists():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta_data = json.load(f)
                created_at = meta_data.get("created_at", created_at)
            except (json.JSONDecodeError, OSError):
                pass
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
            created_at=created_at,
        )
        write_json(meta_path, record)
        return True, "skipped", record

    try:
        template_meta = resource_manager.get_template(template_id)
        if template_meta is None:
            raise ValueError(f"模板不存在: {template_id}")

        provider = RealEstateDataProvider(city_name, block, start_year, end_year, table_name)
        context = ContextBuilder.build_context(
            template_meta=template_meta,
            provider=provider,
            city=city_name,
            block=block,
            start_year=start_year,
            end_year=end_year,
        )

        engine = PPTGenerationEngine(str(gt_ppt))
        engine.generate_multiple_slides([{"template_id": template_id, "context": context}])

        exported_yaml = find_exported_yaml(gt_dir)
        if exported_yaml is None:
            raise RuntimeError(f"未找到导出的 YAML: {gt_dir}")

        if gt_yaml.exists():
            gt_yaml.unlink()
        if exported_yaml != gt_yaml:
            exported_yaml.rename(gt_yaml)

        # 清理多余 YAML，只保留 gt/slide.yaml
        for extra_yaml in gt_dir.glob("*.yaml"):
            if extra_yaml != gt_yaml:
                extra_yaml.unlink()

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


def run_injection_phase(
    dataset_root: Path,
    split: str,
    variants_per_yaml: int,
    min_slots: int,
    max_slots: int,
    seed: int,
    generate_ppt: bool,
    errors: list[str] | None,
) -> None:
    injector_script = PROJECT_ROOT / "test" / "error_injector.py"
    command = [
        sys.executable,
        str(injector_script),
        "--benchmark-root",
        str(dataset_root),
        "--split",
        split,
        "--variants-per-yaml",
        str(variants_per_yaml),
        "--min-slots",
        str(min_slots),
        "--max-slots",
        str(max_slots),
        "--seed",
        str(seed),
    ]
    if generate_ppt:
        command.append("--generate-ppt")
    if errors:
        command.extend(["--errors", *errors])

    logger.info("开始执行错误注入阶段...")
    logger.info("命令: {}", " ".join(command))
    subprocess.run(command, check=True, cwd=PROJECT_ROOT)  # noqa: S603


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 benchmark GT 样本（可选连跑错误注入）")
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
        default=DEFAULT_TEMPLATES,
        help="模板 ID 列表",
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
        default=50,
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
        "--append-samples-manifest",
        action="store_true",
        help="追加写入 samples.jsonl（默认清空重写）",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="若 gt/slide.yaml 和 gt/slide.pptx 都存在则跳过重建",
    )
    parser.add_argument(
        "--inject-after-gt",
        action="store_true",
        help="GT 生成后自动执行错误注入阶段",
    )
    parser.add_argument(
        "--inject-variants-per-yaml",
        type=int,
        default=3,
        help="注入阶段：每个 GT YAML 生成多少个错误版本",
    )
    parser.add_argument(
        "--inject-min-slots",
        type=int,
        default=1,
        help="注入阶段：单次最少修改槽位数",
    )
    parser.add_argument(
        "--inject-max-slots",
        type=int,
        default=3,
        help="注入阶段：单次最多修改槽位数",
    )
    parser.add_argument(
        "--inject-seed",
        type=int,
        default=20260306,
        help="注入阶段随机种子",
    )
    parser.add_argument(
        "--inject-generate-ppt",
        action="store_true",
        help="注入阶段是否重建 PPT",
    )
    parser.add_argument(
        "--inject-errors",
        nargs="+",
        default=None,
        help="注入阶段限制错误类型（例如 trend_flip range_reverse）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset_root = Path(args.dataset_root).resolve()

    invalid_cities = [c for c in args.cities if c not in CITY_CONFIGS]
    if invalid_cities:
        raise ValueError(f"无效城市: {invalid_cities}, 可选: {list(CITY_CONFIGS.keys())}")

    if args.clean_dataset and dataset_root.exists():
        shutil.rmtree(dataset_root)

    manifests = init_manifests(
        dataset_root=dataset_root,
        append_samples_manifest=args.append_samples_manifest,
    )

    resource_manager.load_all()
    templates = resolve_templates(args.templates)
    if not templates:
        raise ValueError("没有可用模板，请检查 --templates 参数")

    logger.info("开始生成 benchmark GT")
    logger.info("dataset_root: {}", dataset_root)
    logger.info("split: {}", args.split)
    logger.info("cities: {}", args.cities)
    logger.info("templates: {}", templates)
    logger.info("time_range: {}-{}", args.start_year, args.end_year)

    stats = {
        "total": 0,
        "generated": 0,
        "skipped": 0,
        "failed": 0,
    }

    stop = False
    for city_key in args.cities:
        config = CITY_CONFIGS[city_key]
        city_name = config["city"]
        table_name = config["table"]
        csv_file = config["csv_file"]

        blocks = load_blocks_from_csv(csv_file)
        if args.max_blocks_per_city is not None:
            blocks = blocks[: args.max_blocks_per_city]

        logger.info("处理城市 {}: blocks={} templates={}", city_name, len(blocks), len(templates))
        for block in blocks:
            for template_id in templates:
                if args.max_samples is not None and stats["total"] >= args.max_samples:
                    stop = True
                    break

                stats["total"] += 1
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
                )

                if ok and record is not None:
                    if status == "generated":
                        stats["generated"] += 1
                    elif status == "skipped":
                        stats["skipped"] += 1
                    append_jsonl(manifests["samples"], record)
                    logger.info(
                        "[{}] s_{} | {} | {}",
                        status.upper(),
                        record["sample_id"],
                        record["block"],
                        record["template_id"],
                    )
                else:
                    stats["failed"] += 1

            if stop:
                break
        if stop:
            break

    logger.info("GT 生成完成")
    logger.info(
        "总任务={} 生成={} 跳过={} 失败={}",
        stats["total"],
        stats["generated"],
        stats["skipped"],
        stats["failed"],
    )
    logger.info("samples manifest: {}", manifests["samples"])

    if args.inject_after_gt:
        run_injection_phase(
            dataset_root=dataset_root,
            split=args.split,
            variants_per_yaml=args.inject_variants_per_yaml,
            min_slots=args.inject_min_slots,
            max_slots=args.inject_max_slots,
            seed=args.inject_seed,
            generate_ppt=args.inject_generate_ppt,
            errors=args.inject_errors,
        )
        logger.info("注入阶段完成，manifest/injections.jsonl 已更新")


if __name__ == "__main__":
    main()
