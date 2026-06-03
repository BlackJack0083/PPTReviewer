"""仅供 `ContentValidationAgent` 使用的工具。

这些函数不是 LangChain tools，而是 content-validation workflow 在 data source
验证完成后显式调用的确定性 helper。它们负责执行 table state、比较可见 CSV
数据、构造确认过的修改记录，以及写出 repaired artifacts。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from core.dao import RealEstateDAO
from core.schemas import QueryFilter, TableAnalysisConfig
from core.transformers import StatTransformer

ROUNDING_ABS_TOLERANCE = 0.5


def modify_textbox(
    *,
    element_id: str | None,
    new_text: str,
) -> dict[str, Any]:
    """构造 textbox 修改记录。

    Args:
        element_id: PPTX textbox 元素 id。summary 这类 slide-level 文本没有
            element id 时允许为 `None`。
        new_text: client 确认过的替换文本。

    Returns:
        artifact export 消费的 JSON-serializable update record。
    """
    return {
        "tool": "modify_textbox",
        "update_type": "text",
        "element_id": element_id,
        "new_text": new_text,
    }


def modify_chart(
    *,
    element_id: str | None,
    data_path: str | None = None,
    chart_type: str | None = None,
) -> dict[str, Any]:
    """构造 chart 修改记录。

    Args:
        element_id: PPTX chart 元素 id。
        data_path: 替换 chart data 使用的 CSV 路径。
        chart_type: 当展示形式本身需要修改时使用的可选 chart type。

    Returns:
        artifact export 消费的 JSON-serializable update record。
    """
    return {
        "tool": "modify_chart",
        "update_type": "chart",
        "element_id": element_id,
        "data_path": data_path,
        "chart_type": chart_type,
    }


def modify_table(
    *,
    element_id: str | None,
    data_path: str,
) -> dict[str, Any]:
    """构造 table 修改记录。

    Args:
        element_id: PPTX table 元素 id。
        data_path: 替换 table data 使用的 CSV 路径。

    Returns:
        artifact export 消费的 JSON-serializable update record。
    """
    return {
        "tool": "modify_table",
        "update_type": "table",
        "element_id": element_id,
        "data_path": data_path,
    }


def execute_table_state(
    table_state: dict[str, Any],
    *,
    final_data_source: dict[str, Any],
    dao: RealEstateDAO,
    transformer: StatTransformer,
) -> pd.DataFrame:
    """执行单个 table state，得到 expected displayed dataframe。

    Args:
        table_state: `analysis_state["tables"]` 中的一项，提供该表自己的
            `select_columns` 和 `calculation_logic`。
        final_data_source: client 验证后的 slide-level source slots。
        dao: 用于读取原始数据库行的 DAO。
        transformer: 执行 `TableAnalysisConfig` 的 transformer。

    Returns:
        修复后 slide 中应展示的重算 dataframe。
    """
    data_source = _execution_data_source(table_state, final_data_source)
    filters = data_source["filters"]
    query_filter = QueryFilter(
        city=filters["city"],
        block=filters["block"],
        start_date=filters["start_date"],
        end_date=filters["end_date"],
        table_name=data_source["connection"]["table"],
    )
    raw_df = dao.fetch_raw_data(query_filter, columns=data_source["select_columns"])
    config = TableAnalysisConfig.model_validate(table_state["calculation_logic"])
    return transformer.process_data_pipeline(raw_df, config)


def compare_display_dataframes(
    visible_df: pd.DataFrame,
    expected_df: pd.DataFrame,
) -> dict[str, Any]:
    """比较 PPT 可见 dataframe 和重算 dataframe。

    Args:
        visible_df: 从当前 PPT chart/table body 抽出的数据。
        expected_df: 根据已验证 state 重算的数据。

    Returns:
        `{"status": "equal"|"different", "diff_summary": "..."}`。
    """
    if _dataframes_equal(visible_df, expected_df):
        return {"status": "equal", "diff_summary": ""}
    if visible_df.shape != expected_df.shape:
        return {
            "status": "different",
            "diff_summary": f"Visible shape {visible_df.shape} differs from expected shape {expected_df.shape}.",
        }
    if list(_normalize_columns(visible_df).columns) != list(
        _normalize_columns(expected_df).columns
    ):
        return {
            "status": "different",
            "diff_summary": "Visible columns differ from recomputed columns.",
        }
    return {
        "status": "different",
        "diff_summary": "Visible CSV values differ from DB recomputation using validated data_source and calculation_logic.",
    }


def write_content_artifacts(
    *,
    analysis_state: dict[str, Any],
    ppt_representation: dict[str, Any],
    table_records: list[dict[str, Any]],
    update_log: list[dict[str, Any]],
    artifact_dir: Path,
) -> dict[str, Any]:
    """写出 repaired semantic YAML 和确认过的 table CSV 更新。

    Args:
        analysis_state: data-source validation 后的最终 analysis state。
        ppt_representation: Parser 输出，用于获取 element id 和 body type。
        table_records: validation 阶段产生的 expected/visible table data 记录。
        update_log: client 确认过的修改记录。
        artifact_dir: repaired YAML/CSV 文件写入目录。

    Returns:
        repaired artifacts 路径。由于当前层还没有实现 PPTX 重写，
        `pptx_path` 目前为 `None`。
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)
    data_paths = _write_confirmed_table_updates(
        table_records=table_records,
        update_log=update_log,
        artifact_dir=artifact_dir,
    )
    yaml_payload = _build_repaired_yaml(
        analysis_state=analysis_state,
        ppt_representation=ppt_representation,
        data_paths=data_paths,
        update_log=update_log,
    )
    yaml_path = artifact_dir / "repaired_slide.yaml"
    yaml_path.write_text(
        yaml.safe_dump(yaml_payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return {
        "yaml_path": str(yaml_path),
        "data_paths": {str(key): value for key, value in data_paths.items()},
        "pptx_path": None,
    }


def _write_confirmed_table_updates(
    *,
    table_records: list[dict[str, Any]],
    update_log: list[dict[str, Any]],
    artifact_dir: Path,
) -> dict[int, str]:
    records_by_index = {record["table_index"]: record for record in table_records}
    data_paths: dict[int, str] = {}
    for update in update_log:
        if update.get("tool") not in {"modify_chart", "modify_table"}:
            continue
        if update.get("data_path") is None:
            continue
        table_index = int(update["table_index"])
        source_path = Path(records_by_index[table_index]["expected_data_path"])
        target_path = artifact_dir / f"table_{table_index}_repaired.csv"
        shutil.copyfile(source_path, target_path)
        data_paths[table_index] = str(target_path)
    return data_paths


def _build_repaired_yaml(
    *,
    analysis_state: dict[str, Any],
    ppt_representation: dict[str, Any],
    data_paths: dict[int, str],
    update_log: list[dict[str, Any]],
) -> dict[str, Any]:
    parsed_tables = list(ppt_representation.get("structured_tables", []))
    tables = []
    for table_index, table_state in enumerate(analysis_state.get("tables", [])):
        parsed_table = parsed_tables[table_index] if table_index < len(parsed_tables) else {}
        body = parsed_table.get("body") or {}
        tables.append(
            {
                "caption": _caption_for_table(table_index, table_state, update_log),
                "body": {
                    "presentation_type": body.get("type", ""),
                    "data_path": data_paths.get(
                        table_index,
                        table_state.get("data_path", ""),
                    ),
                },
                "data_source": _execution_data_source(
                    table_state,
                    analysis_state["final_data_source"],
                ),
                "calculation_logic": table_state.get("calculation_logic", {}),
            }
        )
    return {
        "title": analysis_state.get("title", ""),
        "summary": _summary_for_slide(analysis_state, update_log),
        "tables": tables,
        "update_log": update_log,
    }


def _caption_for_table(
    table_index: int,
    table_state: dict[str, Any],
    update_log: list[dict[str, Any]],
) -> str:
    caption_obj = table_state.get("caption")
    if not isinstance(caption_obj, dict) or not isinstance(caption_obj.get("text"), str):
        raise ValueError(f"table_state.caption must contain text: {table_state}")
    caption = caption_obj["text"]
    for update in update_log:
        if update.get("tool") != "modify_textbox":
            continue
        if update.get("field") != "caption":
            continue
        if int(update.get("table_index", -1)) != table_index:
            continue
        caption_update = update.get("new_text")
        if isinstance(caption_update, str) and caption_update.strip():
            caption = caption_update
    return caption


def _summary_for_slide(
    analysis_state: dict[str, Any],
    update_log: list[dict[str, Any]],
) -> str:
    summary_obj = analysis_state.get("summary")
    if not isinstance(summary_obj, dict) or not isinstance(summary_obj.get("text"), str):
        raise ValueError(f"analysis_state.summary must contain text: {analysis_state}")
    summary = summary_obj["text"]
    for update in update_log:
        if update.get("tool") != "modify_textbox":
            continue
        if update.get("field") != "summary":
            continue
        summary_update = update.get("new_text")
        if isinstance(summary_update, str) and summary_update.strip():
            summary = summary_update
    return summary


def _execution_data_source(
    table_state: dict[str, Any],
    final_data_source: dict[str, Any],
) -> dict[str, Any]:
    caption = table_state.get("caption")
    if not isinstance(caption, dict):
        raise ValueError(f"table_state.caption must be an object: {table_state}")
    caption_data_source = caption.get("data_source")
    if not isinstance(caption_data_source, dict):
        raise ValueError(f"table_state.caption.data_source missing: {table_state}")
    select_columns = caption_data_source.get("select_columns")
    if not isinstance(select_columns, list) or not all(
        isinstance(column, str) for column in select_columns
    ):
        raise ValueError(f"caption data_source select_columns must be string list: {table_state}")
    return {
        "connection": final_data_source["connection"],
        "filters": final_data_source["filters"],
        "select_columns": list(select_columns),
    }


def _dataframes_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    left_norm = _normalize_columns(left)
    right_norm = _normalize_columns(right)
    if list(left_norm.columns) != list(right_norm.columns):
        return False
    if left_norm.shape != right_norm.shape:
        return False
    return all(
        _series_equal(left_norm[column], right_norm[column])
        for column in left_norm.columns
    )


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    return normalized.reset_index(drop=True)


def _series_equal(left: pd.Series, right: pd.Series) -> bool:
    left_numeric = pd.to_numeric(left, errors="coerce")
    right_numeric = pd.to_numeric(right, errors="coerce")
    if left_numeric.notna().all() and right_numeric.notna().all():
        delta = (left_numeric - right_numeric).abs()
        return bool((delta <= ROUNDING_ABS_TOLERANCE).all())

    left_text = left.astype(str).str.strip().reset_index(drop=True)
    right_text = right.astype(str).str.strip().reset_index(drop=True)
    return bool(left_text.equals(right_text))
