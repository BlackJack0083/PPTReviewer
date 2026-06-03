from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from core.schemas import TableAnalysisConfig
from method.utils import Client, parse_json_object

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
DEFAULT_DATA_SOURCE_PROMPT_PATH = PROMPT_DIR / "data_source_extraction_prompt.txt"
DEFAULT_FUNCTION_LOGIC_PROMPT_PATH = PROMPT_DIR / "function_logic_extraction_prompt.txt"


class SlideAnalysisAgent:
    """从 PPT representation 中抽取可执行 data source 和 calculation logic。"""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout_sec: int = 120,
        enable_thinking: bool | None = False,
        client: Any | None = None,
        data_source_prompt_path: Path = DEFAULT_DATA_SOURCE_PROMPT_PATH,
        function_logic_prompt_path: Path = DEFAULT_FUNCTION_LOGIC_PROMPT_PATH,
    ):
        """初始化 slide analysis agent。

        Args:
            model: OpenAI-compatible chat model 名称。未注入 `client` 时必填。
            api_key: OpenAI-compatible endpoint 的 API key。
            base_url: OpenAI-compatible endpoint 的 base URL。
            timeout_sec: LLM 请求超时时间，单位为秒。
            enable_thinking: 传给 `Client` 的 provider-specific thinking 开关。
            client: 可选的测试用 LLM client。
            data_source_prompt_path: data-source extraction prompt 路径。
            function_logic_prompt_path: calculation-logic extraction prompt 路径。

        Raise:
            ValueError: 未注入 `client` 且未提供 `model`。
        """
        if client is not None:
            self.client = client
        else:
            if model is None:
                raise ValueError("SlideAnalysisAgent requires model when client is not provided.")
            self.client = Client(
                model=model,
                api_key=api_key,
                base_url=base_url,
                timeout_sec=timeout_sec,
                enable_thinking=enable_thinking,
            )
        self.data_source_prompt = data_source_prompt_path.read_text(encoding="utf-8")
        self.function_logic_prompt = function_logic_prompt_path.read_text(encoding="utf-8")

    def run(self, *, ppt_representation: dict[str, Any]) -> dict[str, Any]:
        """对 parser 输出执行 Phase 1 analysis。

        Args:
            ppt_representation: Parser 输出，包含 title、summary，以及带 CSV
                路径的结构化 chart/table body。

        Returns:
            Analysis state，包含 title、summary source、每个 table 的 caption
            source，以及 `calculation_logic`。

        Raise:
            ValueError: 当模型输出不符合要求 schema 时抛出。
        """
        analysis_input = build_analysis_input(ppt_representation)
        # summary 和 caption 可能同时描述同一组 source slots。这里先保留为
        # 独立证据，后续由 `DataSourceValidationAgent` 聚合为一个
        # `final_data_source`。
        summary_data_source = self._extract_data_source(
            {
                "source": "summary",
                "text": analysis_input["summary"],
                "row_headers": [],
                "column_headers": [],
            },
            0,
            include_select_columns=False,
        )

        analyzed_tables = []
        for index, table_input in enumerate(analysis_input["tables"]):
            # `select_columns` 归 caption data source 管，因为即使 slide-level
            # filters 相同，不同 visual body 也可能需要不同原始列。
            data_source = self._extract_data_source(
                {
                    "source": "caption",
                    "text": table_input["caption"],
                    "row_headers": table_input["row_headers"],
                    "column_headers": table_input["column_headers"],
                },
                index,
                include_select_columns=True,
            )
            calculation_logic = self._extract_function_logic(table_input, index)
            analyzed_tables.append(
                {
                    "caption": {
                        "text": table_input["caption"],
                        "data_source": data_source,
                    },
                    "data_path": table_input["data_path"],
                    "calculation_logic": calculation_logic,
                }
            )
        return {
            "title": analysis_input["title"],
            "summary": {
                "text": analysis_input["summary"],
                "data_source": summary_data_source,
            },
            "tables": analyzed_tables,
        }

    def _extract_data_source(
        self,
        payload: dict[str, Any],
        index: int,
        *,
        include_select_columns: bool,
    ) -> dict[str, Any]:
        """从单个 summary/caption payload 中抽取 data-source slots。

        Args:
            payload: Prompt 输入，包含 `source`、`text` 和可选的 visible table
                headers。
            index: caption extraction 使用的 table index；summary 固定为 `0`。
            include_select_columns: 输出是否必须包含 `select_columns`。
                summary extraction 会设为 `False`。

        Returns:
            校验后的 data-source object。
        """
        content = self.client.chat(
            self.data_source_prompt,
            json.dumps(payload, ensure_ascii=False, indent=2),
            response_format="json_object",
        )
        return _validate_data_source(
            parse_json_object(content),
            index,
            include_select_columns=include_select_columns,
        )

    def _extract_function_logic(
        self,
        table_input: dict[str, Any],
        index: int,
    ) -> dict[str, Any]:
        """从 visible table data 中抽取 table calculation logic。

        Args:
            table_input: 单个 visible chart/table 的紧凑表示。
            index: 用于 validation error message 的 table index。

        Returns:
            序列化为字典的 `TableAnalysisConfig`。
        """
        payload = {
            "table_caption": table_input["caption"],
            "table_data": table_input["table_data"],
        }
        content = self.client.chat(
            self.function_logic_prompt,
            json.dumps(payload, ensure_ascii=False, indent=2),
            response_format="json_object",
        )
        calculation_logic = parse_json_object(content)
        return TableAnalysisConfig.model_validate(calculation_logic).model_dump()


def build_analysis_input(ppt_representation: dict[str, Any]) -> dict[str, Any]:
    """构造发送给 analysis LLM 的紧凑 JSON payload。

    Args:
        ppt_representation: Parser 输出，包含 title、summary、captions 和 body
            CSV 路径。

    Returns:
        包含 table headers 和 CSV rows 的紧凑 analysis input。

    Raise:
        FileNotFoundError: parser 引用的 table body CSV 不存在时抛出。
        ValueError: 引用的 CSV 为空时抛出。
    """
    tables = []
    for table in ppt_representation.get("structured_tables", []):
        body = table.get("body") or {}
        data_path = Path(str(body.get("data_path", "")))
        if not data_path.exists():
            raise FileNotFoundError(f"Missing table CSV for analysis: {data_path}")
        header, rows, table_data = _read_csv_for_analysis(data_path)
        tables.append(
            {
                "caption": _text_value(table.get("caption")),
                "body_type": str(body.get("type", "")),
                "data_path": str(data_path),
                "row_headers": [row[0] for row in rows if row],
                "column_headers": header[1:] if len(header) > 1 else header,
                "table_data": table_data,
            }
        )

    return {
        "title": _text_value(ppt_representation.get("title")),
        "summary": _text_value(ppt_representation.get("summary")),
        "tables": tables,
    }


def _validate_data_source(
    data_source: dict[str, Any],
    index: int,
    *,
    include_select_columns: bool,
) -> dict[str, Any]:
    connection = data_source.get("connection")
    filters = data_source.get("filters")
    if not isinstance(connection, dict) or not isinstance(connection.get("table"), str):
        raise ValueError(f"Analysis table #{index + 1} missing connection.table.")
    if not isinstance(filters, dict):
        raise ValueError(f"Analysis table #{index + 1} missing filters object.")

    required_filter_keys = {"city", "block", "start_date", "end_date"}
    if set(filters) != required_filter_keys:
        raise ValueError(
            f"Analysis table #{index + 1} filters must contain exactly "
            f"{sorted(required_filter_keys)}, got {sorted(filters)}."
        )
    if not all(isinstance(filters[key], str) for key in required_filter_keys):
        raise ValueError(f"Analysis table #{index + 1} filters values must be strings.")

    validated = {
        "connection": {"table": connection["table"]},
        "filters": {key: filters[key] for key in ("city", "block", "start_date", "end_date")},
    }
    if include_select_columns:
        select_columns = data_source.get("select_columns")
        if not isinstance(select_columns, list) or not all(
            isinstance(column, str) for column in select_columns
        ):
            raise ValueError(
                f"Analysis table #{index + 1} select_columns must be string list."
            )
        validated["select_columns"] = list(select_columns)
    return validated


def _text_value(element: Any) -> str:
    if isinstance(element, dict):
        return str(element.get("text", ""))
    return ""


def _read_csv_for_analysis(path: Path) -> tuple[list[str], list[list[str]], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise ValueError(f"Analysis CSV is empty: {path}")
    header = rows[0]
    body_rows = rows[1:]
    table_data = []
    for row in body_rows:
        item = {}
        for idx, name in enumerate(header):
            item[name] = row[idx] if idx < len(row) else ""
        table_data.append(item)
    return header, body_rows, table_data
