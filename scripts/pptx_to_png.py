#!/usr/bin/env python3
"""
PPTX -> PNG 转换工具（Windows/WSL）

Windows 推荐：
1. pip install pptxtopdf pdf2image
2. （可选）安装 poppler，并通过 --poppler-path 指定 bin 路径

Linux/WSL 回退：
1. 安装 libreoffice-impress + poppler-utils

示例：
1) 转 benchmark 某个 split 的 GT
   uv run python scripts/pptx_to_png.py \
     --benchmark-root output/benchmark/dataset_v1 \
     --split test_size_b \
     --backend auto

2) 同时转换 GT + injected
   uv run python scripts/pptx_to_png.py \
     --benchmark-root output/benchmark/dataset_v1 \
     --split test_size_b \
     --include-injected \
     --backend auto

3) Windows 单文件（显式 windows backend）
   uv run python scripts/pptx_to_png.py \
     --pptx path/to/slide.pptx \
     --backend windows
"""

from __future__ import annotations

import argparse
import concurrent.futures
import glob
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.pptx_image_utils import convert_pptx_first_page_to_png


def discover_pptx_from_patterns(patterns: list[str]) -> list[Path]:
    items: list[Path] = []
    for pattern in patterns:
        if any(token in pattern for token in ("*", "?", "[")):
            items.extend(Path(p).resolve() for p in glob.glob(pattern))
        else:
            path = Path(pattern).resolve()
            if path.exists() and path.is_file():
                items.append(path)
    return sorted(set(items))


def discover_benchmark_pptx(
    benchmark_root: Path,
    split: str,
    include_gt: bool,
    include_injected: bool,
) -> list[Path]:
    split_root = benchmark_root / "split"
    if not split_root.exists():
        return []

    if split.lower() in {"all", "*"}:
        split_dirs = [p for p in split_root.iterdir() if p.is_dir()]
    else:
        split_dirs = [split_root / s.strip() for s in split.split(",") if s.strip()]

    results: list[Path] = []
    for sample_root in split_dirs:
        if not sample_root.exists():
            continue
        if include_gt:
            results.extend(sample_root.glob("s_*/gt/slide.pptx"))
        if include_injected:
            results.extend(sample_root.glob("s_*/injected/*/slide.pptx"))

    return sorted({p.resolve() for p in results if p.exists()})


def output_path_for(pptx_path: Path, output_root: Path | None, output_name: str) -> Path:
    if output_root is None:
        return pptx_path.with_name(output_name)
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root / f"{pptx_path.stem}.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert PPTX first page to PNG")
    parser.add_argument(
        "--pptx",
        nargs="+",
        default=None,
        help="PPTX file path(s) or glob pattern(s)",
    )
    parser.add_argument(
        "--benchmark-root",
        default=None,
        help="Benchmark root path, e.g. output/benchmark/dataset_v1",
    )
    parser.add_argument(
        "--split",
        default="test_size_b",
        help="Split for benchmark scan; supports comma list or 'all'",
    )
    parser.add_argument(
        "--include-injected",
        action="store_true",
        help="When scanning benchmark, include injected/*/slide.pptx",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "windows", "libreoffice"],
        default="auto",
        help="Conversion backend. auto: Windows uses pptxtopdf/pdf2image, others use libreoffice",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="Optional output root; default writes next to each PPTX",
    )
    parser.add_argument(
        "--output-name",
        default="slide.png",
        help="Output file name when writing next to PPTX (default: slide.png)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="PNG render dpi (default: 200)",
    )
    parser.add_argument(
        "--poppler-path",
        default=None,
        help="Optional poppler bin path for pdf2image on Windows",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel workers (recommend 1 for libreoffice backend)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing PNG files (default: skip existing)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of PPTX files to process",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    benchmark_root = Path(args.benchmark_root).resolve() if args.benchmark_root else None
    output_root = Path(args.output_root).resolve() if args.output_root else None

    pptx_files: list[Path] = []
    if args.pptx:
        pptx_files.extend(discover_pptx_from_patterns(args.pptx))
    if benchmark_root:
        include_gt = True
        include_injected = args.include_injected
        pptx_files.extend(
            discover_benchmark_pptx(
                benchmark_root=benchmark_root,
                split=args.split,
                include_gt=include_gt,
                include_injected=include_injected,
            )
        )

    pptx_files = sorted(set(pptx_files))
    if not pptx_files:
        print("No PPTX files found.")
        return

    tasks: list[tuple[Path, Path]] = []
    skipped = 0
    for pptx_path in pptx_files:
        output_png = output_path_for(
            pptx_path=pptx_path,
            output_root=output_root,
            output_name=args.output_name,
        )
        if output_png.exists() and not args.overwrite:
            skipped += 1
            continue
        tasks.append((pptx_path, output_png))

    if args.limit is not None and args.limit >= 0:
        tasks = tasks[: args.limit]

    print(
        f"Found {len(pptx_files)} PPTX files. "
        f"to_process={len(tasks)}, skipped_existing={skipped}, workers={max(1, args.workers)}"
    )
    if not tasks:
        print("Nothing to process.")
        return

    if max(1, args.workers) > 1 and args.backend in {"auto", "libreoffice"}:
        print("Warning: libreoffice with high concurrency may fail due to process lock/contention.")

    def run_one(task: tuple[Path, Path]) -> tuple[Path, Path, str]:
        pptx_path, output_png = task
        print(f"START {pptx_path}", flush=True)
        try:
            convert_pptx_first_page_to_png(
                pptx_path,
                output_png,
                dpi=args.dpi,
                backend=args.backend,
                poppler_path=args.poppler_path,
            )
            return (pptx_path, output_png, "")
        except Exception as exc:  # noqa: BLE001
            return (pptx_path, output_png, str(exc))

    success = 0
    failed = 0
    workers = max(1, args.workers)
    if workers == 1:
        for idx, task in enumerate(tasks, 1):
            pptx_path, output_png, err = run_one(task)
            if err:
                failed += 1
                print(f"[{idx}/{len(tasks)}] FAIL {pptx_path}: {err}")
            else:
                success += 1
                print(f"[{idx}/{len(tasks)}] OK {pptx_path} -> {output_png}")
    else:
        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_task = {executor.submit(run_one, task): task for task in tasks}
            for future in concurrent.futures.as_completed(future_to_task):
                done += 1
                pptx_path, output_png, err = future.result()
                if err:
                    failed += 1
                    print(f"[{done}/{len(tasks)}] FAIL {pptx_path}: {err}")
                else:
                    success += 1
                    print(f"[{done}/{len(tasks)}] OK {pptx_path} -> {output_png}")

    print(
        "Done. "
        f"total_found={len(pptx_files)}, processed={len(tasks)}, "
        f"success={success}, failed={failed}, skipped_existing={skipped}"
    )


if __name__ == "__main__":
    main()
