from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from core.schemas import TableAnalysisConfig
from method.utils import Client, parse_json_object

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
DEFAULT_DATA_SOURCE_PROMPT_PATH = PROMPT_DIR / "data_source_extraction_prompt.txt"
DEFAULT_FUNCTION_LOGIC_PROMPT_PATH = PROMPT_DIR / "function_logic_extraction_prompt.txt"


class SlideAnalysisAgent:
    """Extract executable data-source and calculation logic state from PPT representation."""

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
        """Run Phase 1 analysis over parser output.

        Args:
            ppt_representation: Parser output containing title, summary, and structured
                chart/table bodies with CSV paths.

        Returns:
            Analysis state with title, summary, and per-table `data_source` plus
            `calculation_logic`.

        Raises:
            ValueError: If the model output does not match the required schema.
        """
        analysis_input = build_analysis_input(ppt_representation)
        analyzed_tables = []
        for index, table_input in enumerate(analysis_input["tables"]):
            data_source = self._extract_data_source(table_input, index)
            calculation_logic = self._extract_function_logic(table_input, index)
            analyzed_tables.append(
                {
                    "caption": table_input["caption"],
                    "data_path": table_input["data_path"],
                    "data_source": data_source,
                    "calculation_logic": calculation_logic,
                }
            )
        return {
            "title": analysis_input["title"],
            "summary": analysis_input["summary"],
            "tables": analyzed_tables,
        }

    def _extract_data_source(
        self,
        table_input: dict[str, Any],
        index: int,
    ) -> dict[str, Any]:
        payload = {
            "caption": table_input["caption"],
            "row_headers": table_input["row_headers"],
            "column_headers": table_input["column_headers"],
        }
        content = self.client.chat(
            self.data_source_prompt,
            json.dumps(payload, ensure_ascii=False, indent=2),
            response_format="json_object",
        )
        return _validate_data_source(parse_json_object(content), index)

    def _extract_function_logic(
        self,
        table_input: dict[str, Any],
        index: int,
    ) -> dict[str, Any]:
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
    """Build the compact JSON payload sent to the analysis LLM."""
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


def _validate_data_source(data_source: dict[str, Any], index: int) -> dict[str, Any]:
    connection = data_source.get("connection")
    select_columns = data_source.get("select_columns")
    filters = data_source.get("filters")
    if not isinstance(connection, dict) or not isinstance(connection.get("table"), str):
        raise ValueError(f"Analysis table #{index + 1} missing connection.table.")
    if not isinstance(select_columns, list) or not all(
        isinstance(column, str) for column in select_columns
    ):
        raise ValueError(f"Analysis table #{index + 1} select_columns must be string list.")
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

    return {
        "connection": {"table": connection["table"]},
        "select_columns": list(select_columns),
        "filters": {key: filters[key] for key in ("city", "block", "start_date", "end_date")},
    }


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
