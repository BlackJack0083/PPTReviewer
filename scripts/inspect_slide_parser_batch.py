#!/usr/bin/env python3
"""检查 SlideParserAgent 在一批真实 PPT 上的抽取结果。

脚本会读取 injected case 自己目录下的 `slide.yaml` 作为可见 PPT 的真实结构，
并与 parser 输出比较 title、summary、caption、body type 和 body CSV。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from method.agents import SlideParserAgent, SlideReviewInput  # noqa: E402

PRESENTATION_LABEL_RE = re.compile(r"\((bar chart|line chart|pie chart|table)\)\s*$", re.I)
TREND_RE = re.compile(
    r"\b(increase|increased|decrease|decreased|growth|decline|upward|downward)\b",
    re.I,
)


class InspectRoleClient:
    """测试/检查用 role client，根据 PPTX 文本和 shape 类型生成稳定 role。"""

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: Path,
        response_format: str,
    ) -> str:
        del system_prompt, image_path, response_format
        payload = json.loads(user_prompt.split("Input elements:\n", 1)[1])
        elements = list(payload.get("elements", []))
        roles: dict[str, str] = {}
        text_elements = [element for element in elements if element.get("type") == "textBox"]

        for element in elements:
            if element.get("type") == "textBox":
                continue
            roles[str(element["id"])] = str(element.get("shape_kind") or element.get("type"))

        caption_ids = set()
        summary_ids = set()
        for element in text_elements:
            text = str(element.get("text", "")).strip()
            element_id = str(element["id"])
            if PRESENTATION_LABEL_RE.search(text) or "analysis" in text.lower():
                caption_ids.add(element_id)
            elif TREND_RE.search(text) or any(char.isdigit() for char in text):
                summary_ids.add(element_id)

        title_candidates = [
            element
            for element in text_elements
            if str(element["id"]) not in caption_ids | summary_ids
        ] or list(text_elements)
        title_candidates.sort(
            key=lambda element: (
                element.get("layout", {}).get("y", 999.0),
                len(str(element.get("text", ""))),
            )
        )
        title_id = str(title_candidates[0]["id"]) if title_candidates else ""

        for element in text_elements:
            element_id = str(element["id"])
            if element_id == title_id:
                roles[element_id] = "title"
            elif element_id in caption_ids:
                roles[element_id] = "caption"
            else:
                roles[element_id] = "summary"

        return json.dumps(
            {
                "roles": [
                    {"id": element_id, "role": role}
                    for element_id, role in sorted(roles.items(), key=lambda item: int(item[0]))
                ]
            },
            ensure_ascii=False,
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
    parser.add_argument("--limit", type=int, default=10, help="检查多少个 injected PPT。")
    parser.add_argument(
        "--case-glob",
        default="s_*/injected/*",
        help="相对于 split 目录的 case glob。",
    )
    parser.add_argument(
        "--show-rows",
        type=int,
        default=3,
        help="每个 CSV 打印前几行。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="可选 JSON report 输出路径。",
    )
    return parser.parse_args()


def main() -> None:
    """运行 parser inspection 并打印逐 case 结果。"""
    args = parse_args()
    split_root = args.benchmark_root / "split" / args.split
    cases = [
        case_dir
        for case_dir in sorted(split_root.glob(args.case_glob))
        if (case_dir / "slide.pptx").exists()
        and (case_dir / "slide.png").exists()
        and (case_dir / "slide.yaml").exists()
    ][: args.limit]
    if not cases:
        raise SystemExit(f"No cases found under {split_root} with glob={args.case_glob}")

    agent = SlideParserAgent(client=InspectRoleClient())
    totals = Counter()
    case_results = []
    print(f"Inspecting {len(cases)} parser cases under {split_root}\n")
    for idx, case_dir in enumerate(cases, 1):
        case_result = inspect_case(agent, case_dir, show_rows=args.show_rows)
        totals.update(case_result["stats"])
        print_case_result(idx, case_dir, case_result)
        case_results.append({"case_dir": str(case_dir), **case_result})

    summary = {
        key: int(totals[key])
        for key in (
            "cases",
            "title_ok",
            "summary_ok",
            "table_count_ok",
            "caption_ok",
            "body_type_ok",
            "csv_ok",
            "case_pass",
        )
    }
    summary["all_case_pass"] = f"{totals['case_pass']}/{totals['cases']}"
    print_summary(summary)
    if args.output is not None:
        write_report(
            args.output,
            {
                "benchmark_root": str(args.benchmark_root),
                "split": args.split,
                "limit": args.limit,
                "case_glob": args.case_glob,
                "summary": summary,
                "cases": case_results,
            },
        )
        print(f"JSON report written to: {args.output}")


def print_summary(summary: dict[str, Any]) -> None:
    """打印总体检查结果。"""
    print("========== 总结 ==========")
    for key in (
        "cases",
        "title_ok",
        "summary_ok",
        "table_count_ok",
        "caption_ok",
        "body_type_ok",
        "csv_ok",
    ):
        print(f"{key}: {summary[key]}")
    print(f"all_case_pass: {summary['all_case_pass']}")


def write_report(path: Path, report: dict[str, Any]) -> None:
    """写出 JSON report。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_jsonable(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def to_jsonable(value: Any) -> Any:
    """把 Path、Counter、tuple 等对象转成 JSON 可序列化结构。"""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Counter):
        return dict(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


def inspect_case(
    agent: SlideParserAgent,
    case_dir: Path,
    *,
    show_rows: int,
) -> dict[str, Any]:
    """检查单个 case 的 parser 输出和真实 YAML 是否一致。"""
    expected = expected_from_yaml(case_dir / "slide.yaml")
    corruption = {}
    corruption_path = case_dir / "corruption.json"
    if corruption_path.exists():
        corruption = json.loads(corruption_path.read_text(encoding="utf-8"))
    parsed = agent.run(
        SlideReviewInput(
            pptx_path=case_dir / "slide.pptx",
            image_path=case_dir / "slide.png",
        )
    )
    representation = parsed["ppt_representation"]

    title_cmp = compare_text(
        (representation.get("title") or {}).get("text", ""),
        expected["title"],
    )
    summary_cmp = compare_text(
        (representation.get("summary") or {}).get("text", ""),
        expected["summary"],
    )
    parsed_tables = list(representation.get("structured_tables", []))
    expected_tables = expected["tables"]
    table_count_ok = len(parsed_tables) == len(expected_tables)
    table_results = []

    for table_idx, (parsed_table, expected_table) in enumerate(
        zip(parsed_tables, expected_tables),
        1,
    ):
        parsed_csv = Path(parsed_table["body"]["data_path"])
        expected_csv = (case_dir / expected_table["data"]).resolve()
        csv_cmp = compare_csv(
            parsed_csv,
            expected_csv,
            metric_names=expected_table["metric_names"],
        )
        table_results.append(
            {
                "index": table_idx,
                "caption": compare_text(
                    (parsed_table.get("caption") or {}).get("text", ""),
                    expected_table["caption"],
                ),
                "body_type": {
                    "ok": parsed_table["body"]["type"] == expected_table["role"],
                    "actual": parsed_table["body"]["type"],
                    "expected": expected_table["role"],
                },
                "csv": csv_cmp,
                "parsed_csv": parsed_csv,
                "expected_csv": expected_csv,
                "preview": preview_csv(parsed_csv, show_rows),
            }
        )

    stats = Counter(
        {
            "cases": 1,
            "title_ok": int(title_cmp["ok"]),
            "summary_ok": int(summary_cmp["ok"]),
            "table_count_ok": int(table_count_ok),
            "caption_ok": sum(int(item["caption"]["ok"]) for item in table_results),
            "body_type_ok": sum(int(item["body_type"]["ok"]) for item in table_results),
            "csv_ok": sum(int(item["csv"]["ok"]) for item in table_results),
        }
    )
    case_pass = (
        title_cmp["ok"]
        and summary_cmp["ok"]
        and table_count_ok
        and all(item["caption"]["ok"] for item in table_results)
        and all(item["body_type"]["ok"] for item in table_results)
        and all(item["csv"]["ok"] for item in table_results)
    )
    stats["case_pass"] = int(case_pass)
    return {
        "title": title_cmp,
        "summary": summary_cmp,
        "table_count": {
            "ok": table_count_ok,
            "actual": len(parsed_tables),
            "expected": len(expected_tables),
        },
        "tables": table_results,
        "stats": stats,
        "case_pass": case_pass,
        "operations": corruption.get("operations", []),
    }


def expected_from_yaml(path: Path) -> dict[str, Any]:
    """从 injected `slide.yaml` 中读取真实可见结构。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    elements = data.get("template_slide", {}).get("elements", [])
    title = ""
    summary = ""
    captions: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    for element in elements:
        role = str(element.get("role", ""))
        if role == "slide-title":
            title = str(element.get("text", ""))
        elif role == "body-text":
            summary = str(element.get("text", ""))
        elif role == "caption":
            captions.append(element)
        elif role.startswith("chart") or role == "table":
            caption = nearest_yaml_caption(element, captions)
            tables.append(
                {
                    "role": role,
                    "caption": str((caption or {}).get("text", "")),
                    "data": str(element.get("data", "")),
                    "metric_names": metric_names_from_element(element),
                }
            )
    return {"title": title, "summary": summary, "tables": tables}


def metric_names_from_element(element: dict[str, Any]) -> list[str]:
    """从 injected YAML 的 chart args 中读取可见 series/header 名称。"""
    args = element.get("args")
    if not isinstance(args, dict):
        return []
    metrics = args.get("metrics")
    if not isinstance(metrics, list):
        return []
    names = []
    for metric in metrics:
        if isinstance(metric, dict) and str(metric.get("name", "")).strip():
            names.append(str(metric["name"]).strip())
    return names


def nearest_yaml_caption(
    body_element: dict[str, Any],
    captions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """用和 parser 一致的中心点距离规则匹配 YAML caption。"""
    if not captions:
        return None

    def center(element: dict[str, Any]) -> tuple[float, float]:
        layout = element.get("layout") or {}
        return (
            float(layout.get("x", 0.0)) + float(layout.get("width", 0.0)) / 2.0,
            float(layout.get("y", 0.0)) + float(layout.get("height", 0.0)) / 2.0,
        )

    body_center = center(body_element)
    return min(
        captions,
        key=lambda caption: abs(body_center[0] - center(caption)[0])
        + abs(body_center[1] - center(caption)[1]),
    )


def compare_text(actual: str, expected: str) -> dict[str, Any]:
    """比较文本，忽略 YAML markdown 加粗和空白差异。"""
    return {
        "ok": normalize_text(actual) == normalize_text(expected),
        "actual": actual,
        "expected": expected,
    }


def compare_csv(
    actual_path: Path,
    expected_path: Path,
    *,
    metric_names: list[str],
) -> dict[str, Any]:
    """比较 parser 导出的 CSV 和 YAML 引用的真实 CSV。"""
    if not actual_path.exists() or not expected_path.exists():
        return {
            "ok": False,
            "reason": "missing_csv",
            "actual_shape": None,
            "expected_shape": None,
        }
    actual = pd.read_csv(actual_path)
    expected = pd.read_csv(expected_path)
    expected = expected_csv_to_parser_format(expected, metric_names=metric_names)
    actual_norm = normalize_dataframe(actual)
    expected_norm = normalize_dataframe(expected)
    ok = actual_norm.equals(expected_norm)
    reason = "equal"
    if not ok and actual_norm.shape != expected_norm.shape:
        reason = f"shape {actual_norm.shape} != {expected_norm.shape}"
    elif not ok and list(actual_norm.columns) != list(expected_norm.columns):
        reason = "columns differ"
    elif not ok:
        reason = "values differ"
    return {
        "ok": ok,
        "reason": reason,
        "actual_shape": actual_norm.shape,
        "expected_shape": expected_norm.shape,
        "actual_columns": list(actual_norm.columns),
        "expected_columns": list(expected_norm.columns),
    }


def expected_csv_to_parser_format(
    df: pd.DataFrame,
    *,
    metric_names: list[str],
) -> pd.DataFrame:
    """把 injected YAML 的 data+args 转成 parser 导出的 long format。"""
    if "__index__" not in df.columns:
        return df
    if metric_names and len(metric_names) == len(df):
        df = df.copy()
        df["__index__"] = metric_names
    converted = df.set_index("__index__").transpose().reset_index()
    converted = converted.rename(columns={"index": "category"})
    converted.columns = [str(column) for column in converted.columns]
    return converted


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """标准化 dataframe，避免整数/浮点字符串格式导致的误判。"""
    normalized = df.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    for column in normalized.columns:
        numeric = pd.to_numeric(normalized[column], errors="coerce")
        if numeric.notna().all():
            normalized[column] = numeric.round(6)
        else:
            normalized[column] = normalized[column].astype(str).str.strip()
    return normalized.reset_index(drop=True)


def normalize_text(value: str) -> str:
    """标准化文本，忽略 markdown 加粗和多余空白。"""
    text = str(value).replace("**", "")
    return re.sub(r"\s+", " ", text).strip()


def preview_csv(path: Path, rows: int) -> list[dict[str, Any]]:
    """读取 CSV 前几行，供人工查看。"""
    if not path.exists():
        return []
    return pd.read_csv(path).head(rows).to_dict(orient="records")


def print_case_result(index: int, case_dir: Path, result: dict[str, Any]) -> None:
    """打印单个 case 的检查结果。"""
    status = "PASS" if result["case_pass"] else "FAIL"
    print(f"========== Case {index}: {status} ==========")
    print(case_dir)
    if result.get("operations"):
        print(f"operations: {json.dumps(result['operations'], ensure_ascii=False)}")
    print(format_text_result("title", result["title"]))
    print(format_text_result("summary", result["summary"]))
    print(
        "table_count: "
        f"{result['table_count']['actual']} / {result['table_count']['expected']} "
        f"ok={result['table_count']['ok']}"
    )
    for table in result["tables"]:
        print(f"  -- table {table['index']} --")
        print("  " + format_text_result("caption", table["caption"]))
        print(
            "  body_type: "
            f"actual={table['body_type']['actual']} expected={table['body_type']['expected']} "
            f"ok={table['body_type']['ok']}"
        )
        print(
            "  csv: "
            f"ok={table['csv']['ok']} reason={table['csv']['reason']} "
            f"actual_shape={table['csv']['actual_shape']} "
            f"expected_shape={table['csv']['expected_shape']}"
        )
        if not table["csv"]["ok"]:
            print(f"  actual_columns: {table['csv'].get('actual_columns')}")
            print(f"  expected_columns: {table['csv'].get('expected_columns')}")
        print(f"  parsed_csv: {table['parsed_csv']}")
        print(f"  expected_csv: {table['expected_csv']}")
        print(f"  csv_preview: {json.dumps(table['preview'], ensure_ascii=False)}")
    print()


def format_text_result(name: str, result: dict[str, Any]) -> str:
    """格式化文本比较结果。"""
    line = f"{name}: ok={result['ok']}"
    if result["ok"]:
        return f"{line} value={result['actual']!r}"
    return f"{line}\n  actual={result['actual']!r}\n  expected={result['expected']!r}"


if __name__ == "__main__":
    main()
