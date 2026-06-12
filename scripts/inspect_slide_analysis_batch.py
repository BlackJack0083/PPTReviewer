#!/usr/bin/env python3
"""检查 SlideAnalysisAgent 在真实 PPT parser 输出上的抽取效果。

脚本会先运行 parser 得到 `ppt_representation`，再调用真实 LLM 执行
data-source extraction 和 function-logic extraction。评估端读取 injected
case 自己的 `slide.yaml`，用于对照原始 data source 和可见 calculation logic。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from method.agents import (  # noqa: E402
    SlideAnalysisAgent,
    SlideParserAgent,
    SlideReviewInput,
)
from method.utils import Client  # noqa: E402
from scripts.inspect_slide_parser_batch import (  # noqa: E402
    InspectRoleClient,
    nearest_yaml_caption,
)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark-root",
        type=Path,
        default=Path("output/benchmark/dataset_v2"),
        help="benchmark 根目录。",
    )
    parser.add_argument("--split", default="test", help="要检查的数据 split。")
    parser.add_argument("--limit", type=int, default=3, help="检查多少个 injected PPT。")
    parser.add_argument(
        "--case-glob",
        default="s_*/injected/*",
        help="相对于 split 目录的 case glob。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/analysis_inspection/analysis_batch.json"),
        help="JSON report 输出路径。",
    )
    parser.add_argument(
        "--real-parser",
        action="store_true",
        help="使用真实 VLM parser role labeling；默认使用已验证过的稳定 role client。",
    )
    parser.add_argument(
        "--exclude-error-type",
        action="append",
        default=[],
        help="跳过包含指定 error_type 的 case，可重复传入。",
    )
    return parser.parse_args()


async def main() -> None:
    """运行 parser+analysis inspection。"""
    args = parse_args()
    split_root = args.benchmark_root / "split" / args.split
    cases = []
    for case_dir in sorted(split_root.glob(args.case_glob)):
        if len(cases) >= args.limit:
            break
        if not (
            (case_dir / "slide.pptx").exists()
            and (case_dir / "slide.png").exists()
            and (case_dir / "slide.yaml").exists()
        ):
            continue
        if case_has_excluded_error(case_dir, set(args.exclude_error_type)):
            continue
        cases.append(case_dir)
    if not cases:
        raise SystemExit(f"No cases found under {split_root} with glob={args.case_glob}")

    parser_agent = build_parser_agent(real_parser=args.real_parser)
    analysis_agent = build_analysis_agent()
    totals = Counter()
    case_reports = []

    print(f"Inspecting {len(cases)} analysis cases under {split_root}\n")
    for index, case_dir in enumerate(cases, 1):
        report = await inspect_case(parser_agent, analysis_agent, case_dir)
        totals.update(report["stats"])
        print_case_report(index, case_dir, report)
        case_reports.append(report)

    summary = {
        "cases": int(totals["cases"]),
        "schema_ok": int(totals["schema_ok"]),
        "summary_source_matches_original": int(totals["summary_source_matches_original"]),
        "caption_source_matches_original": int(totals["caption_source_matches_original"]),
        "logic_matches_visible_yaml": int(totals["logic_matches_visible_yaml"]),
        "all_logic_pass": f"{totals['logic_matches_visible_yaml']}/{totals['tables']}",
        "all_caption_source_original_match": (
            f"{totals['caption_source_matches_original']}/{totals['tables']}"
        ),
    }
    print_summary(summary)
    write_report(
        args.output,
        {
            "benchmark_root": str(args.benchmark_root),
            "split": args.split,
            "limit": args.limit,
            "case_glob": args.case_glob,
            "exclude_error_type": args.exclude_error_type,
            "parser": "real VLM" if args.real_parser else "stable inspection role client",
            "summary": summary,
            "cases": case_reports,
        },
    )
    print(f"JSON report written to: {args.output}")


def build_parser_agent(*, real_parser: bool) -> SlideParserAgent:
    """构造 parser agent。

    参数:
        real_parser: 是否调用真实 VLM 做 role labeling。

    返回:
        `SlideParserAgent` 实例。
    """
    if not real_parser:
        return SlideParserAgent(client=InspectRoleClient())
    return SlideParserAgent(
        model=required_env("DASHSCOPE_MODEL"),
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )


def build_analysis_agent() -> SlideAnalysisAgent:
    """构造调用真实 LLM 的 analysis agent。"""
    return SlideAnalysisAgent(
        client=TracingClient(
            Client(
                model=required_env("DASHSCOPE_MODEL"),
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                base_url=os.getenv(
                    "DASHSCOPE_BASE_URL",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                ),
            )
        ),
    )


class TracingClient:
    """为 inspection 打印每次 LLM 调用耗时。"""

    def __init__(self, client: Client):
        """初始化 tracing client。

        参数:
            client: 项目统一的 LLM client。
        """
        self.client = client
        self.call_index = 0

    async def achat(self, *args: Any, **kwargs: Any) -> str:
        """转发 async chat 调用并打印耗时。"""
        import time

        self.call_index += 1
        call_index = self.call_index
        print(f"    analysis LLM call {call_index} start", flush=True)
        start = time.time()
        content = await self.client.achat(*args, **kwargs)
        print(
            f"    analysis LLM call {call_index} done in {time.time() - start:.1f}s",
            flush=True,
        )
        return content


def required_env(name: str) -> str:
    """读取必需环境变量。"""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required.")
    return value


def case_has_excluded_error(case_dir: Path, excluded_error_types: set[str]) -> bool:
    """判断 case 是否包含需要跳过的 error type。"""
    if not excluded_error_types:
        return False
    corruption = read_json_if_exists(case_dir / "corruption.json")
    return bool(excluded_error_types & set(corruption.get("error_types", [])))


async def inspect_case(
    parser_agent: SlideParserAgent,
    analysis_agent: SlideAnalysisAgent,
    case_dir: Path,
) -> dict[str, Any]:
    """检查单个 case 的 analysis 输出。

    参数:
        parser_agent: 已构造的 parser agent。
        analysis_agent: 已构造的 analysis agent。
        case_dir: injected case 目录。

    返回:
        包含 analysis state、GT 对照和统计结果的字典。
    """
    expected = expected_from_yaml(case_dir / "slide.yaml")
    corruption = read_json_if_exists(case_dir / "corruption.json")
    print("  parser start", flush=True)
    parsed = await parser_agent.arun(
        SlideReviewInput(
            pptx_path=case_dir / "slide.pptx",
            image_path=case_dir / "slide.png",
        )
    )
    print("  parser done; analysis start", flush=True)
    analysis_state = await analysis_agent.arun(ppt_representation=parsed["ppt_representation"])
    print("  analysis done", flush=True)

    summary_source_cmp = compare_data_source(
        analysis_state["summary"]["data_source"],
        expected["summary_data_source"],
        include_select_columns=False,
    )
    table_reports = []
    for table_index, table_state in enumerate(analysis_state.get("tables", [])):
        expected_table = expected["tables"][table_index]
        table_reports.append(
            {
                "index": table_index,
                "caption": table_state["caption"]["text"],
                "caption_data_source": {
                    "actual": table_state["caption"]["data_source"],
                    "expected_original": expected_table["data_source"],
                    "match_original": compare_data_source(
                        table_state["caption"]["data_source"],
                        expected_table["data_source"],
                        include_select_columns=True,
                    ),
                },
                "calculation_logic": {
                    "actual": table_state["calculation_logic"],
                    "expected_visible_yaml": expected_table["calculation_logic"],
                    "match_visible_yaml": compare_calculation_logic(
                        table_state["calculation_logic"],
                        expected_table["calculation_logic"],
                    ),
                },
            }
        )

    stats = Counter(
        {
            "cases": 1,
            "schema_ok": 1,
            "summary_source_matches_original": int(summary_source_cmp["ok"]),
            "tables": len(table_reports),
            "caption_source_matches_original": sum(
                int(table["caption_data_source"]["match_original"]["ok"])
                for table in table_reports
            ),
            "logic_matches_visible_yaml": sum(
                int(table["calculation_logic"]["match_visible_yaml"]["ok"])
                for table in table_reports
            ),
        }
    )
    return {
        "case_dir": str(case_dir),
        "operations": corruption.get("operations", []),
        "contains_scope_error": "scope_error" in corruption.get("error_types", []),
        "parser_representation": parsed["ppt_representation"],
        "analysis_state": analysis_state,
        "expected_original": expected,
        "summary_data_source": {
            "actual": analysis_state["summary"]["data_source"],
            "expected_original": expected["summary_data_source"],
            "match_original": summary_source_cmp,
        },
        "tables": table_reports,
        "stats": stats,
    }


def expected_from_yaml(path: Path) -> dict[str, Any]:
    """从 injected YAML 读取原始 data source 和可见 calculation logic。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    slide_filters = normalize_slide_filters(data.get("slide_filters", []))
    elements = data.get("template_slide", {}).get("elements", [])
    captions = [element for element in elements if str(element.get("role")) == "caption"]
    bodies = [
        element
        for element in elements
        if str(element.get("role", "")).startswith("chart") or str(element.get("role")) == "table"
    ]
    query_filters = data.get("query_filters") or {}
    default_data_source = {
        "connection": {"table": slide_filters[0]["connection"]["table"] if slide_filters else ""},
        "filters": {
            "city": str(query_filters.get("city", "")),
            "block": str(query_filters.get("block", "")),
            "start_date": str(query_filters.get("start_date", "")),
            "end_date": str(query_filters.get("end_date", "")),
        },
    }

    tables = []
    for index, body in enumerate(bodies):
        data_source = slide_filters[min(index, len(slide_filters) - 1)] if slide_filters else {}
        caption = nearest_yaml_caption(body, captions) or {}
        tables.append(
            {
                "caption": str(caption.get("text", "")),
                "data_source": data_source,
                "calculation_logic": normalize_calculation_logic(body.get("args") or {}),
            }
        )

    return {
        "summary_data_source": default_data_source,
        "tables": tables,
    }


def normalize_slide_filters(items: list[Any]) -> list[dict[str, Any]]:
    """把 YAML slide_filters 规范化为 analysis 使用的 data_source 格式。"""
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        connection = item.get("connection") or {}
        table = connection.get("table", "")
        if isinstance(table, list):
            table = table[0] if table else ""
        filters = item.get("filters") or {}
        normalized.append(
            {
                "connection": {"table": str(table)},
                "select_columns": [str(column) for column in item.get("select_columns", [])],
                "filters": {
                    "city": str(filters.get("city", "")),
                    "block": str(filters.get("block", "")),
                    "start_date": str(filters.get("start_date", "")),
                    "end_date": str(filters.get("end_date", "")),
                },
            }
        )
    return normalized


def normalize_calculation_logic(args: dict[str, Any]) -> dict[str, Any]:
    """把 YAML chart/table args 规范化为 `TableAnalysisConfig` 输出格式。"""
    return {
        "table_type": str(args.get("table_type", "")),
        "dimensions": normalize_rules(args.get("dimensions", []), drop_keys={"min", "max"}),
        "metrics": normalize_rules(args.get("metrics", [])),
        "crosstab_row": args.get("crosstab_row"),
        "crosstab_col": args.get("crosstab_col"),
    }


def normalize_rules(
    rules: Any,
    *,
    drop_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    """去掉 YAML 规则中的空值，保留可比较字段。"""
    if not isinstance(rules, list):
        return []
    drop_keys = drop_keys or set()
    normalized = []
    for rule in rules:
        if isinstance(rule, dict):
            normalized.append(
                {
                    str(key): value
                    for key, value in rule.items()
                    if value is not None and str(key) not in drop_keys
                }
            )
    return normalized


def compare_data_source(
    actual: dict[str, Any],
    expected: dict[str, Any],
    *,
    include_select_columns: bool,
) -> dict[str, Any]:
    """比较 analysis 抽取的 data source 和原始 YAML data source。"""
    actual_norm = normalize_data_source(actual, include_select_columns=include_select_columns)
    expected_norm = normalize_data_source(expected, include_select_columns=include_select_columns)
    return {
        "ok": actual_norm == expected_norm,
        "actual_normalized": actual_norm,
        "expected_normalized": expected_norm,
    }


def normalize_data_source(
    source: dict[str, Any],
    *,
    include_select_columns: bool,
) -> dict[str, Any]:
    """规范化 data source，避免日期/YAML 类型差异影响比较。"""
    filters = source.get("filters") or {}
    normalized = {
        "connection": {"table": str((source.get("connection") or {}).get("table", ""))},
        "filters": {
            "city": str(filters.get("city", "")),
            "block": str(filters.get("block", "")),
            "start_date": str(filters.get("start_date", "")),
            "end_date": str(filters.get("end_date", "")),
        },
    }
    if include_select_columns:
        normalized["select_columns"] = sorted(
            str(column) for column in source.get("select_columns", [])
        )
    return normalized


def compare_calculation_logic(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """比较 function logic 输出和 injected YAML 中的可见 args。"""
    actual_norm = normalize_calculation_logic(actual)
    expected_norm = normalize_calculation_logic(expected)
    return {
        "ok": actual_norm == expected_norm,
        "actual_normalized": actual_norm,
        "expected_normalized": expected_norm,
    }


def read_json_if_exists(path: Path) -> dict[str, Any]:
    """读取可选 JSON 文件。"""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_report(path: Path, report: dict[str, Any]) -> None:
    """写出 JSON report。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_jsonable(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def to_jsonable(value: Any) -> Any:
    """把 Counter、Path 等对象转成 JSON 可序列化结构。"""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Counter):
        return dict(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


def print_case_report(index: int, case_dir: Path, report: dict[str, Any]) -> None:
    """打印单个 case 的检查摘要。"""
    print(f"========== Case {index} ==========")
    print(case_dir)
    print(f"contains_scope_error: {report['contains_scope_error']}")
    if report["operations"]:
        print(f"operations: {json.dumps(report['operations'], ensure_ascii=False)}")
    summary_cmp = report["summary_data_source"]["match_original"]
    print(f"summary_data_source matches original: {summary_cmp['ok']}")
    for table in report["tables"]:
        source_cmp = table["caption_data_source"]["match_original"]
        logic_cmp = table["calculation_logic"]["match_visible_yaml"]
        print(
            f"  table {table['index']}: "
            f"caption_source_matches_original={source_cmp['ok']} "
            f"logic_matches_visible_yaml={logic_cmp['ok']}"
        )
        if not source_cmp["ok"]:
            print(f"    actual_source={source_cmp['actual_normalized']}")
            print(f"    expected_original_source={source_cmp['expected_normalized']}")
        if not logic_cmp["ok"]:
            print(f"    actual_logic={logic_cmp['actual_normalized']}")
            print(f"    expected_visible_logic={logic_cmp['expected_normalized']}")
    print()


def print_summary(summary: dict[str, Any]) -> None:
    """打印总体检查结果。"""
    print("========== 总结 ==========")
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
