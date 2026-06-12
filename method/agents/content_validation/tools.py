"""Content validation agent 使用的确定性工具。"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from langchain.agents import AgentState
from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command

from method.database import query as database_query
from method.schemas import QueryFilter, TableAnalysisConfig
from method.transformers import StatTransformer

ROUNDING_ABS_TOLERANCE = 0.5
PREVIEW_ROWS = 5
MAX_DIFF_EXAMPLES = 5


@dataclass
class ContentValidationContext:
    """Content validation tools 的运行上下文。

    Args:
        client: benchmark client 或人工桥接对象。
        artifact_dir: raw/computed/repaired 文件输出目录。
        transformer: function logic 执行器。
        query_func: 数据库查询函数，签名为 `query(sql, params=None)`。
    """

    client: Any
    artifact_dir: Path
    transformer: StatTransformer = field(default_factory=StatTransformer)
    query_func: Any = database_query


class ContentValidationState(AgentState):
    """Content validation agent 的 LangGraph state。

    Args:
        analysis_state: 当前 slide analysis state。
        table_records: 已检索和重算的表格数据路径记录。
        tool_log: 本轮 ReAct 过程中所有 content validation 工具调用记录。
        detected_issues: 当前保留的显式问题记录。
    """

    analysis_state: dict[str, Any]
    table_records: list[dict[str, Any]]
    tool_log: list[dict[str, Any]]
    detected_issues: list[dict[str, Any]]


@tool
def sql_retrieve(table_index: int, runtime: ToolRuntime) -> Command:
    """根据 table state 的 datasource 查询原始数据库行。

    Args:
        table_index: `state["tables"]` 中的表格下标。

    Returns:
        raw CSV 路径、列名、行数和数据预览。
    """
    state = runtime.state
    context = runtime.context
    table_state = state["analysis_state"]["tables"][table_index]
    data_source = table_state["caption"]["data_source"]
    filters = data_source["filters"]
    raw_df = fetch_raw_data(
        QueryFilter(
            city=filters["city"],
            block=filters["block"],
            start_date=filters["start_date"],
            end_date=filters["end_date"],
            table_name=data_source["connection"]["table"],
        ),
        columns=data_source["select_columns"],
        query_func=context.query_func,
    )
    raw_path = context.artifact_dir / f"table_{table_index}_raw.csv"
    raw_df.to_csv(raw_path, index=False)
    result = {
        "table_index": table_index,
        "raw_data_path": str(raw_path),
        "row_count": int(raw_df.shape[0]),
        "columns": [str(column) for column in raw_df.columns],
        "preview": _preview(raw_df),
    }
    return _tool_command(
        runtime,
        result,
        {"tool_log": [*state["tool_log"], {"tool": "sql_retrieve", **result}]},
    )


@tool
def analysis_execute(table_index: int, raw_data_path: str, runtime: ToolRuntime) -> Command:
    """执行 analysis 阶段抽取出的 function logic。

    Args:
        table_index: `state["tables"]` 中的表格下标。
        raw_data_path: `sql_retrieve` 返回的 raw CSV 路径。

    Returns:
        computed CSV 路径、列名、行数和数据预览。
    """
    state = runtime.state
    context = runtime.context
    table_state = state["analysis_state"]["tables"][table_index]
    raw_df = pd.read_csv(raw_data_path)
    config = TableAnalysisConfig.model_validate(table_state["calculation_logic"])
    computed_df = context.transformer.process_data_pipeline(raw_df, config)
    computed_path = context.artifact_dir / f"table_{table_index}_computed.csv"
    computed_df.to_csv(computed_path, index=False)
    visible_path = str(table_state["data_path"])
    record = {
        "table_index": table_index,
        "visible_data_path": visible_path,
        "raw_data_path": raw_data_path,
        "computed_data_path": str(computed_path),
        "row_count": int(computed_df.shape[0]),
        "columns": [str(column) for column in computed_df.columns],
    }
    table_records = [
        item for item in state["table_records"] if item["table_index"] != table_index
    ]
    table_records.append(record)
    result = {**record, "preview": _preview(computed_df)}
    return _tool_command(
        runtime,
        result,
        {
            "table_records": table_records,
            "tool_log": [
                *state["tool_log"],
                {"tool": "analysis_execute", **result},
            ],
        },
    )


@tool
def compare_table(table_index: int, computed_data_path: str, runtime: ToolRuntime) -> Command:
    """比较 PPT 可见数据和 function logic 重算数据。

    Args:
        table_index: `state["tables"]` 中的表格下标。
        computed_data_path: `analysis_execute` 返回的 computed CSV 路径。

    Returns:
        比较状态、差异说明和双方数据预览。
    """
    state = runtime.state
    table_state = state["analysis_state"]["tables"][table_index]
    visible_path = str(table_state["data_path"])
    visible_df = align_visible_dataframe(pd.read_csv(visible_path), table_state)
    computed_df = pd.read_csv(computed_data_path)
    comparison = compare_display_dataframes(visible_df, computed_df)
    result = {
        "table_index": table_index,
        "visible_data_path": visible_path,
        "computed_data_path": computed_data_path,
        "comparison": comparison,
        "visible_preview": _preview(visible_df),
        "computed_preview": _preview(computed_df),
    }
    return _tool_command(
        runtime,
        result,
        {"tool_log": [*state["tool_log"], {"tool": "compare_table", **result}]},
    )


@tool
def ask_client(
    error_type: str,
    target: str,
    field: str,
    description: str,
    runtime: ToolRuntime,
) -> Command:
    """向 client 请求确认或澄清。

    Args:
        error_type: agent 判断出的错误类型，例如 `value_error` 或
            `claim_error`。
        target: 请求涉及的单个 PPT 目标，例如 `st.body`、`st.caption` 或
            `summary`。
        field: 需要确认或修改的单个字段，例如 `table_values`、
            `presentation_type` 或 `summary`。
        description: agent 对当前问题和建议修改的说明。

    Returns:
        只包含 `response` 的客户式回复。
    """
    state = runtime.state
    request: dict[str, Any] = {
        "request_type": "content_update_confirmation",
        "error_type": error_type,
        "field": field,
        "description": description,
        "target": target,
    }
    response = runtime.context.client.respond(request)
    if set(response) != {"response"} or not isinstance(response["response"], str):
        raise ValueError(f"ask_client expects client to return only response: {response}")
    detected_issue: dict[str, Any] = {
        "request_type": request["request_type"],
        "target": target,
        "field": field,
        "error_type": error_type,
        "evidence": description,
    }
    return _tool_command(
        runtime,
        response,
        {
            "detected_issues": [*state["detected_issues"], detected_issue],
            "tool_log": [
                *state["tool_log"],
                {"tool": "ask_client", "request": request, "response": response},
            ]
        },
    )


@tool("modify_chart")
def modify_chart_tool(table_index: int, data_path: str, runtime: ToolRuntime) -> Command:
    """记录用户确认后的 chart 数据修改。

    Args:
        table_index: `state["tables"]` 中的表格下标。
        data_path: 确认替换的 chart data CSV 路径。

    Returns:
        修改记录。
    """
    state = runtime.state
    analysis_state = copy.deepcopy(state["analysis_state"])
    table_state = analysis_state["tables"][table_index]
    body = table_state["body"]
    if body["type"] == "table":
        raise ValueError("modify_chart cannot update table body.")
    result = {"success": True}
    table_state["data_path"] = data_path
    table_state["body"]["data_path"] = data_path
    return _tool_command(
        runtime,
        result,
        {
            "analysis_state": analysis_state,
            "tool_log": [
                *state["tool_log"],
                {
                    "tool": "modify_chart",
                    "args": {"table_index": table_index, "data_path": data_path},
                    "result": result,
                },
            ],
        },
    )


@tool("modify_table")
def modify_table_tool(table_index: int, data_path: str, runtime: ToolRuntime) -> Command:
    """记录用户确认后的 table 数据修改。

    Args:
        table_index: `state["tables"]` 中的表格下标。
        data_path: 确认替换的 table data CSV 路径。

    Returns:
        修改记录。
    """
    state = runtime.state
    analysis_state = copy.deepcopy(state["analysis_state"])
    table_state = analysis_state["tables"][table_index]
    body = table_state["body"]
    if body["type"] != "table":
        raise ValueError("modify_table can only update table body.")
    result = {"success": True}
    table_state["data_path"] = data_path
    table_state["body"]["data_path"] = data_path
    return _tool_command(
        runtime,
        result,
        {
            "analysis_state": analysis_state,
            "tool_log": [
                *state["tool_log"],
                {
                    "tool": "modify_table",
                    "args": {"table_index": table_index, "data_path": data_path},
                    "result": result,
                },
            ],
        },
    )


@tool("modify_textbox")
def modify_textbox_tool(
    element_id: str,
    text: str,
    runtime: ToolRuntime,
) -> Command:
    """记录用户确认后的 textbox 文本修改。

    Args:
        element_id: PPTX textbox 元素 id。
        text: 新 textbox 文本。

    Returns:
        修改记录。
    """
    state = runtime.state
    analysis_state = copy.deepcopy(state["analysis_state"])
    textbox, target = _find_textbox(analysis_state, element_id)

    result = {"success": True}
    textbox["text"] = text
    return _tool_command(
        runtime,
        result,
        {
            "analysis_state": analysis_state,
            "tool_log": [
                *state["tool_log"],
                {
                    "tool": "modify_textbox",
                    "args": {"element_id": element_id, "text": text},
                    "target": target,
                    "result": result,
                },
            ],
        },
    )


CONTENT_VALIDATION_TOOLS = [
    sql_retrieve,
    analysis_execute,
    compare_table,
    ask_client,
    modify_chart_tool,
    modify_table_tool,
    modify_textbox_tool,
]


def _tool_command(
    runtime: ToolRuntime,
    result: dict[str, Any],
    update: dict[str, Any],
) -> Command:
    if runtime.tool_call_id is not None:
        update = {
            **update,
            "messages": [
                ToolMessage(
                    content=json.dumps(result, ensure_ascii=False, default=str),
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    return Command(update=update)


def _find_textbox(
    analysis_state: dict[str, Any],
    element_id: str,
) -> tuple[dict[str, Any], str]:
    title = analysis_state["title"]
    if str(title.get("element_id")) == element_id:
        return title, "title"
    summary = analysis_state["summary"]
    if str(summary.get("element_id")) == element_id:
        return summary, "summary"
    for table_state in analysis_state["tables"]:
        caption = table_state["caption"]
        if str(caption.get("element_id")) == element_id:
            return caption, "st.caption"
    raise ValueError(f"Unknown textbox element_id: {element_id}")


def execute_table_state(
    table_state: dict[str, Any],
    *,
    transformer: StatTransformer,
    query_func: Any = database_query,
) -> pd.DataFrame:
    """执行单个 table state，得到 expected displayed dataframe。

    Args:
        table_state: 已写入确认后 datasource 的单个 table state。
        transformer: 执行 `TableAnalysisConfig` 的 transformer。
        query_func: 数据库查询函数，签名为 `query(sql, params=None)`。

    Returns:
        修复后 slide 中应展示的重算 dataframe。
    """
    data_source = table_state["caption"]["data_source"]
    filters = data_source["filters"]
    query_filter = QueryFilter(
        city=filters["city"],
        block=filters["block"],
        start_date=filters["start_date"],
        end_date=filters["end_date"],
        table_name=data_source["connection"]["table"],
    )
    raw_df = fetch_raw_data(
        query_filter,
        columns=table_state["caption"]["data_source"]["select_columns"],
        query_func=query_func,
    )
    config = TableAnalysisConfig.model_validate(table_state["calculation_logic"])
    return transformer.process_data_pipeline(raw_df, config)


def fetch_raw_data(
    filters: QueryFilter,
    *,
    columns: list[str] | None,
    query_func: Any = database_query,
) -> pd.DataFrame:
    """按 data-source slots 查询原始数据库行。

    Args:
        filters: 已验证的数据源 slots。
        columns: 需要读取的原始列。
        query_func: 数据库查询函数，签名为 `query(sql, params=None)`。

    Returns:
        原始数据库行 dataframe。
    """
    col_str = ", ".join(columns) if columns else "*"
    sql = f"""
        SELECT {col_str}
        FROM public.{filters.table_name}
        WHERE city = :city
          AND block = :block
          AND date_code >= :start_date
          AND date_code <= :end_date
    """  # nosec - table/column names come from analysis state and dataset allowlists.
    return query_func(sql, filters.sql_params)


def compare_display_dataframes(
    visible_df: pd.DataFrame,
    expected_df: pd.DataFrame,
) -> dict[str, Any]:
    """比较 PPT 可见 dataframe 和重算 dataframe。

    Args:
        visible_df: 从当前 PPT chart/table body 抽出的数据。
        expected_df: 根据已验证 state 重算的数据。

    Returns:
        比较结果。值不一致时返回差异总数和最多 5 个 cell 级示例。
    """
    visible_norm = visible_df.copy().reset_index(drop=True)
    expected_norm = expected_df.copy().reset_index(drop=True)
    visible_norm.columns = [str(column).strip() for column in visible_norm.columns]
    expected_norm.columns = [str(column).strip() for column in expected_norm.columns]
    if visible_norm.shape != expected_norm.shape:
        return {
            "status": "different",
            "diff_summary": f"Visible shape {visible_norm.shape} differs from expected shape {expected_norm.shape}.",
        }
    if list(visible_norm.columns) != list(expected_norm.columns):
        return {
            "status": "different",
            "diff_summary": "Visible columns differ from recomputed columns.",
        }
    diff_count, diff_examples = _dataframe_value_differences(
        visible_norm,
        expected_norm,
        max_examples=MAX_DIFF_EXAMPLES,
    )
    if diff_count == 0:
        return {"status": "equal", "diff_summary": ""}
    return {
        "status": "different",
        "diff_count": diff_count,
        "diff_examples": diff_examples,
        "diff_summary": (
            "Visible CSV values differ from DB recomputation using validated "
            f"data_source and calculation_logic: {diff_count} cell(s) differ; "
            f"examples={diff_examples}."
        ),
    }


def align_visible_dataframe(
    visible_df: pd.DataFrame,
    table_state: dict[str, Any],
) -> pd.DataFrame:
    """把 PPT chart/table 可见数据列名对齐到 calculation logic 语义。

    PPTX chart 只保存 category labels 和 series names，不保存 category
    axis 原来的字段名。对于 chart body，parser 因此只能把第一列导出为
    `category`。这里用 analysis 阶段抽取到的第一个 dimension target_col
    明确解释该 category axis 的语义，例如 `year`、`month` 或
    `area_range`。

    Args:
        visible_df: parser 从 PPTX body 导出的可见 dataframe。
        table_state: 当前 table 的 analysis state，包含 body 类型和
            calculation_logic。

    Returns:
        列名已对齐到 calculation logic 语义的可见 dataframe。
    """
    body = table_state["body"]
    if body["type"] == "table" or visible_df.empty or visible_df.shape[1] == 0:
        return visible_df

    first_column = str(visible_df.columns[0]).strip()
    if first_column != "category":
        return visible_df

    dimensions = table_state["calculation_logic"].get("dimensions", [])
    if not dimensions:
        return visible_df
    target_col = dimensions[0].get("target_col")
    if not isinstance(target_col, str) or not target_col.strip():
        return visible_df

    return visible_df.rename(columns={visible_df.columns[0]: target_col.strip()})


def _dataframe_value_differences(
    visible_df: pd.DataFrame,
    expected_df: pd.DataFrame,
    *,
    max_examples: int,
) -> tuple[int, list[dict[str, Any]]]:
    examples: list[dict[str, Any]] = []
    diff_count = 0
    numeric_columns: dict[str, tuple[pd.Series, pd.Series, bool]] = {}
    for column in visible_df.columns:
        visible_numeric = pd.to_numeric(visible_df[column], errors="coerce")
        expected_numeric = pd.to_numeric(expected_df[column], errors="coerce")
        numeric_columns[column] = (
            visible_numeric,
            expected_numeric,
            visible_numeric.notna().all() and expected_numeric.notna().all(),
        )

    for row_index in range(visible_df.shape[0]):
        for column in visible_df.columns:
            visible_value = visible_df.at[row_index, column]
            expected_value = expected_df.at[row_index, column]
            visible_numeric, expected_numeric, numeric_pair = numeric_columns[column]
            if numeric_pair:
                visible_number = visible_numeric.iloc[row_index]
                expected_number = expected_numeric.iloc[row_index]
                if abs(visible_number - expected_number) <= ROUNDING_ABS_TOLERANCE:
                    continue
            elif str(visible_value).strip() == str(expected_value).strip():
                continue
            diff_count += 1
            if len(examples) < max_examples:
                examples.append(
                    {
                        "row": row_index,
                        "column": str(column),
                        "visible": visible_value,
                        "expected": expected_value,
                    }
                )
    return diff_count, examples


def _preview(df: pd.DataFrame) -> list[dict[str, Any]]:
    return df.head(PREVIEW_ROWS).to_dict(orient="records")
