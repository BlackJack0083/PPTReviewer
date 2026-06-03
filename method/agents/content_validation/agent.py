"""内容验证 agent。

该 agent 在 data source 修正后验证 value/claim 错误。它显式调用 `tools.py`
中的确定性工具；只有 summary claim 判断会调用 LLM。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from core.dao import RealEstateDAO
from core.transformers import StatTransformer
from .tools import (
    compare_display_dataframes,
    execute_table_state,
    modify_chart,
    modify_table,
    modify_textbox,
    write_content_artifacts,
)
from method.utils import Client, parse_json_object

from ..types import DetectedIssue

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
DEFAULT_SUMMARY_PROMPT_PATH = PROMPT_DIR / "summary_claim_validation_prompt.txt"
PRESENTATION_LABEL_RE = re.compile(r"\((bar chart|line chart|pie chart|table)\)\s*$", re.I)


class ContentValidationAgent:
    """在 data-source 修正后验证表格数据和 summary claims。"""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout_sec: int = 120,
        enable_thinking: bool | None = False,
        client: Any | None = None,
        dao: RealEstateDAO | None = None,
        transformer: StatTransformer | None = None,
        summary_prompt_path: Path = DEFAULT_SUMMARY_PROMPT_PATH,
    ) -> None:
        """初始化内容验证 agent。

        Args:
            model: OpenAI-compatible chat model 名称。未注入 `client` 时必填。
            api_key: OpenAI-compatible endpoint 的 API key。
            base_url: OpenAI-compatible endpoint 的 base URL。
            timeout_sec: LLM 请求超时时间，单位为秒。
            enable_thinking: 传给 `Client` 的 provider-specific thinking 开关。
            client: 可选的测试用 LLM client。
            dao: 可选 DAO，用于读取原始数据库行。
            transformer: 可选 transformer，用于执行 calculation logic。
            summary_prompt_path: summary-claim validation 使用的 prompt 路径。

        异常:
            ValueError: 未注入 `client` 且未提供 `model`。
        """
        if client is not None:
            self.llm_client = client
        else:
            if model is None:
                raise ValueError("ContentValidationAgent requires model when client is not provided.")
            self.llm_client = Client(
                model=model,
                api_key=api_key,
                base_url=base_url,
                timeout_sec=timeout_sec,
                enable_thinking=enable_thinking,
            )
        self.dao = dao or RealEstateDAO()
        self.transformer = transformer or StatTransformer()
        self.summary_prompt = summary_prompt_path.read_text(encoding="utf-8")

    def run_with_client(
        self,
        *,
        ppt_representation: dict[str, Any],
        analysis_state: dict[str, Any],
        client: Any,
        artifact_dir: Path,
    ) -> dict[str, Any]:
        """在 client 确认下验证表格展示数据和 summary claims。

        Args:
            ppt_representation: Parser 输出，包含可见 chart/table 的数据路径和
                元素 id。
            analysis_state: 经过 `DataSourceValidationAgent` 修正后的
                analysis state。
            client: 共享的 client simulator 或人工桥接对象。
            artifact_dir: expected/repaired CSV 和 YAML 的输出目录。

        Returns:
            验证日志、检测到的问题、确认过的更新记录，以及 repaired artifact 路径。
        """
        artifact_dir.mkdir(parents=True, exist_ok=True)
        table_records: list[dict[str, Any]] = []
        validation_log: list[dict[str, Any]] = []
        update_log: list[dict[str, Any]] = []
        detected_issues: list[dict[str, Any]] = []
        parsed_tables = list(ppt_representation.get("structured_tables", []))

        # 阶段 1：用最终 state 重新计算每个可见 chart/table；记录替换前先问 client。
        for table_index, table_state in enumerate(analysis_state.get("tables", [])):
            parsed_table = parsed_tables[table_index] if table_index < len(parsed_tables) else {}
            table_result = self._validate_table_data(
                table_index=table_index,
                table_state=table_state,
                final_data_source=analysis_state["final_data_source"],
                parsed_table=parsed_table,
                client=client,
                artifact_dir=artifact_dir,
            )
            table_records.append(table_result["table_record"])
            validation_log.append(table_result["log"])
            update_log.extend(table_result["updates"])
            detected_issues.extend(table_result["detected_issues"])

        # 阶段 2：检查 caption 写的展示形式是否和实际 PPT body 不一致。
        # 当前实现只修 caption 文本。
        presentation_result = self._validate_caption_presentation(
            ppt_representation=ppt_representation,
            client=client,
        )
        validation_log.extend(presentation_result["logs"])
        update_log.extend(presentation_result["updates"])
        detected_issues.extend(presentation_result["detected_issues"])

        # 阶段 3：让 LLM 判断 summary claim 是否被重算表格支持；
        # 接受新文本前仍然需要 client 确认。
        summary_result = self._validate_summary_claim(
            analysis_state=analysis_state,
            table_records=table_records,
            client=client,
        )
        validation_log.append(summary_result["log"])
        update_log.extend(summary_result["updates"])
        detected_issues.extend(summary_result["detected_issues"])

        repaired_artifacts = write_content_artifacts(
            analysis_state=analysis_state,
            ppt_representation=ppt_representation,
            table_records=table_records,
            update_log=update_log,
            artifact_dir=artifact_dir,
        )
        return {
            "table_records": table_records,
            "content_validation_log": validation_log,
            "detected_issues": detected_issues,
            "update_log": update_log,
            "repaired_artifacts": repaired_artifacts,
        }

    def _validate_table_data(
        self,
        *,
        table_index: int,
        table_state: dict[str, Any],
        final_data_source: dict[str, Any],
        parsed_table: dict[str, Any],
        client: Any,
        artifact_dir: Path,
    ) -> dict[str, Any]:
        """用重算数据验证单个 chart/table body。

        Args:
            table_index: 在 `analysis_state["tables"]` 中的下标。
            table_state: 单个 analyzed table state。
            final_data_source: client 验证后的 slide 级 data source。
            parsed_table: 匹配的 parser table 对象，包含 body metadata。
            client: 共享的 client simulator 或人工桥接对象。
            artifact_dir: expected CSV 的写入目录。

        Returns:
            table record、验证日志、确认过的 updates 和 detected issues。
        """
        expected_df = execute_table_state(
            table_state,
            final_data_source=final_data_source,
            dao=self.dao,
            transformer=self.transformer,
        )
        expected_path = artifact_dir / f"table_{table_index}_expected.csv"
        expected_df.to_csv(expected_path, index=False)

        visible_path = Path(table_state["data_path"])
        visible_df = pd.read_csv(visible_path)
        comparison = compare_display_dataframes(visible_df, expected_df)
        table_record = {
            "table_index": table_index,
            "visible_data_path": str(visible_path),
            "expected_data_path": str(expected_path),
            "row_count": int(expected_df.shape[0]),
            "columns": [str(column) for column in expected_df.columns],
        }
        log: dict[str, Any] = {
            "stage": "table_data",
            "table_index": table_index,
            "comparison": comparison,
            "visible_dataframe": visible_df.to_dict(orient="records"),
            "expected_dataframe": expected_df.to_dict(orient="records"),
        }
        if comparison["status"] == "equal":
            return {
                "table_record": table_record,
                "log": log,
                "updates": [],
                "detected_issues": [],
            }

        description = (
            "The table/chart data extracted from the PPT differs from the data "
            f"recomputed from the validated data source and calculation logic. {comparison['diff_summary']} "
            "I suggest updating the displayed table/chart data to the recomputed data."
        )
        request = {
            "request_type": "content_update_confirmation",
            "table_index": table_index,
            "targets": ["st.body"],
            "fields": ["table_values"],
            "description": description,
        }
        response = client.respond(request)
        log["client_request"] = request
        log["client_response"] = response
        if not (response.get("matched") and response.get("decision") == "accept"):
            return {
                "table_record": table_record,
                "log": log,
                "updates": [],
                "detected_issues": [],
            }

        body = parsed_table.get("body") or {}
        body_type = str(body.get("type", ""))
        body_element_id = str(body.get("element_id", "")) or None
        if body_type == "table":
            update = modify_table(
                element_id=body_element_id,
                data_path=str(expected_path),
            )
        else:
            update = modify_chart(
                element_id=body_element_id,
                data_path=str(expected_path),
            )
        update["table_index"] = table_index
        update["field"] = "table_values"
        update["description"] = description

        return {
            "table_record": table_record,
            "log": log,
            "updates": [update],
            "detected_issues": [
                DetectedIssue(
                    targets=["st.body"],
                    error_types=["value_error"],
                    evidence=comparison["diff_summary"],
                    required_fields_guess=[],
                    confidence=0.85,
                ).to_dict()
            ],
        }

    def _validate_caption_presentation(
        self,
        *,
        ppt_representation: dict[str, Any],
        client: Any,
    ) -> dict[str, Any]:
        """验证 caption 中的 presentation-type 文本。

        Args:
            ppt_representation: Parser 输出，包含 caption 文本和 body 类型。
            client: 共享的 client simulator 或人工桥接对象。

        Returns:
            日志、确认过的 textbox updates 和 detected claim issues。
        """
        logs: list[dict[str, Any]] = []
        updates: list[dict[str, Any]] = []
        detected_issues: list[dict[str, Any]] = []
        for table_index, parsed_table in enumerate(
            ppt_representation.get("structured_tables", [])
        ):
            issue = _caption_presentation_issue(parsed_table)
            if issue is None:
                continue
            caption = _caption_with_actual_presentation_type(parsed_table)
            description = (
                f"{issue.evidence} I suggest updating the caption text so its "
                "presentation type matches the current slide body."
            )
            request = {
                "request_type": "content_update_confirmation",
                "table_index": table_index,
                "targets": ["st.caption"],
                "fields": ["presentation_type"],
                "description": description,
            }
            response = client.respond(request)
            logs.append(
                {
                    "stage": "caption_presentation",
                    "table_index": table_index,
                    "client_request": request,
                    "client_response": response,
                }
            )
            if not response.get("matched"):
                continue
            detected_issues.append(issue.to_dict())
            caption_element_id = str((parsed_table.get("caption") or {}).get("element_id", "")) or None
            update = modify_textbox(
                element_id=caption_element_id,
                new_text=caption,
            )
            update["table_index"] = table_index
            update["field"] = "caption"
            update["description"] = description
            updates.append(
                update
            )
        return {"logs": logs, "updates": updates, "detected_issues": detected_issues}

    def _validate_summary_claim(
        self,
        *,
        analysis_state: dict[str, Any],
        table_records: list[dict[str, Any]],
        client: Any,
    ) -> dict[str, Any]:
        """验证 summary 文本是否被重算表格支持。

        Args:
            analysis_state: 包含 summary 文本的最终 analysis state。
            table_records: 指向重算 expected CSV 文件的记录。
            client: 共享的 client simulator 或人工桥接对象。

        Returns:
            单条验证日志、确认过的 textbox updates 和 claim issues。
        """
        payload = {
            "summary": _summary_text(analysis_state),
            "tables": [
                {
                    "table_index": record["table_index"],
                    "data": pd.read_csv(record["expected_data_path"]).to_dict(
                        orient="records"
                    ),
                }
                for record in table_records
            ],
        }
        content = self.llm_client.chat(
            self.summary_prompt,
            json.dumps(payload, ensure_ascii=False, indent=2),
            response_format="json_object",
        )
        judgment = _validate_summary_judgment(parse_json_object(content))
        log: dict[str, Any] = {
            "stage": "summary_claim",
            "judgment": judgment,
        }
        if judgment["status"] == "pass":
            return {"log": log, "updates": [], "detected_issues": []}

        request = {
            "request_type": "content_update_confirmation",
            "table_index": 0,
            "targets": ["summary"],
            "fields": ["summary"],
            "description": (
                f"{judgment['evidence']} I suggest replacing the summary with: "
                f"{judgment['suggested_summary']}"
            ),
        }
        response = client.respond(request)
        log["client_request"] = request
        log["client_response"] = response
        if not (
            response.get("matched")
            and response.get("decision") == "accept"
        ):
            return {"log": log, "updates": [], "detected_issues": []}

        update = modify_textbox(
            element_id=None,
            new_text=judgment["suggested_summary"],
        )
        update["table_index"] = 0
        update["field"] = "summary"
        update["description"] = judgment["evidence"]

        return {
            "log": log,
            "updates": [update],
            "detected_issues": [
                DetectedIssue(
                    targets=["summary"],
                    error_types=["claim_error"],
                    evidence=judgment["evidence"],
                    required_fields_guess=["summary"],
                    confidence=judgment["confidence"],
                ).to_dict()
            ],
        }


def _validate_summary_judgment(judgment: dict[str, Any]) -> dict[str, Any]:
    status = judgment.get("status")
    if status not in {"pass", "needs_update"}:
        raise ValueError(f"Invalid summary validation status: {judgment}")
    evidence = judgment.get("evidence")
    if not isinstance(evidence, str):
        raise ValueError(f"Summary validation evidence must be a string: {judgment}")
    suggested_summary = judgment.get("suggested_summary")
    if not isinstance(suggested_summary, str):
        raise ValueError(f"Summary validation suggested_summary must be a string: {judgment}")
    confidence = judgment.get("confidence")
    if not isinstance(confidence, int | float):
        raise ValueError(f"Summary validation confidence must be numeric: {judgment}")
    if status == "needs_update" and not suggested_summary.strip():
        raise ValueError(f"needs_update summary validation requires suggested_summary: {judgment}")
    return {
        "status": status,
        "evidence": evidence,
        "suggested_summary": suggested_summary,
        "confidence": float(confidence),
    }


def _summary_text(analysis_state: dict[str, Any]) -> str:
    summary = analysis_state.get("summary")
    if not isinstance(summary, dict) or not isinstance(summary.get("text"), str):
        raise ValueError(f"analysis_state.summary must contain text: {analysis_state}")
    return summary["text"]


def _caption_presentation_issue(parsed_table: dict[str, Any]) -> DetectedIssue | None:
    caption_text = str((parsed_table.get("caption") or {}).get("text", ""))
    caption_label = _extract_presentation_label(caption_text)
    if not caption_label:
        return None

    body = parsed_table.get("body") or {}
    actual_type = _body_presentation_type(str(body.get("type", "")))
    if caption_label == actual_type:
        return None

    return DetectedIssue(
        targets=["st.caption"],
        error_types=["claim_error"],
        evidence=f"caption says '{caption_label}' but body type is '{actual_type}'.",
        required_fields_guess=["presentation_type"],
        confidence=0.9,
    )


def _caption_with_actual_presentation_type(parsed_table: dict[str, Any]) -> str:
    caption_text = str((parsed_table.get("caption") or {}).get("text", ""))
    body = parsed_table.get("body") or {}
    actual_type = _body_presentation_type(str(body.get("type", "")))
    return PRESENTATION_LABEL_RE.sub(f"({actual_type.title()})", caption_text.strip())


def _extract_presentation_label(text: str) -> str | None:
    match = PRESENTATION_LABEL_RE.search(text.strip())
    if not match:
        return None
    return match.group(1).lower()


def _body_presentation_type(body_type: str) -> str:
    if body_type == "table":
        return "table"
    if body_type.startswith("chart-"):
        return f"{body_type.removeprefix('chart-')} chart"
    return body_type
