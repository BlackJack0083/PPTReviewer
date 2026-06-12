from __future__ import annotations

import copy
from typing import Any

from method.agents import (
    ContentValidationAgent,
    DataSourceValidationAgent,
    SlideAnalysisAgent,
    SlideParserAgent,
    SlideReviewResult,
)
from method.agents.types import SlideReviewInput


class SlideReviewWorkflow:
    """Run slide parsing, state extraction, source repair, and content validation."""

    def __init__(
        self,
        *,
        slide_parser_agent: SlideParserAgent,
        slide_analysis_agent: SlideAnalysisAgent,
        data_source_validation_agent: DataSourceValidationAgent,
        content_validation_agent: ContentValidationAgent,
    ):
        self.slide_parser_agent = slide_parser_agent
        self.slide_analysis_agent = slide_analysis_agent
        self.data_source_validation_agent = data_source_validation_agent
        self.content_validation_agent = content_validation_agent

    async def arun(
        self,
        slide_input: SlideReviewInput,
        *,
        client_agent,
    ) -> SlideReviewResult:
        parsed = await self.slide_parser_agent.arun(slide_input)
        observed_slide = parsed["observed_slide"]
        ppt_representation = parsed["ppt_representation"]
        analysis_state = await self.slide_analysis_agent.arun(
            ppt_representation=ppt_representation,
        )
        final_data_source, data_source_tool_log = await self.data_source_validation_agent.arun(
            analysis_state=analysis_state,
            client=client_agent,
        )
        analysis_state = apply_source(
            analysis_state,
            final_data_source,
        )
        data_source_validation_log = [
            {
                "final_data_source": final_data_source,
                "tool_log": data_source_tool_log,
            }
        ]
        data_source_detected_issues = _issues_from_data_source_tool_log(data_source_tool_log)

        artifact_dir = slide_input.pptx_path.parent / "review_artifacts"
        content_result = await self.content_validation_agent.arun(
            analysis_state=analysis_state,
            client=client_agent,
            artifact_dir=artifact_dir,
        )
        analysis_state = content_result["analysis_state"]

        return SlideReviewResult(
            observed_slide=observed_slide,
            ppt_representation=ppt_representation,
            analysis_state=analysis_state,
            data_source_validation_log=data_source_validation_log,
            content_validation_log=content_result["tool_log"],
            detected_issues=[
                *data_source_detected_issues,
                *content_result["detected_issues"],
            ],
            table_records=content_result["table_records"],
            repaired_artifacts=content_result["repaired_artifacts"],
        )


def apply_source(
    analysis_state: dict[str, Any],
    final_source: dict[str, Any],
) -> dict[str, Any]:
    """把确认后的 slide-level datasource 写回 analysis state。

    Args:
        analysis_state: Slide analysis 输出的 state。
        final_source: Data source validation 确认后的 slide-level source。

    Returns:
        datasource 已归一化的 state。
    """
    state = copy.deepcopy(analysis_state)
    state["final_data_source"] = copy.deepcopy(final_source)

    state["summary"]["data_source"]["connection"] = copy.deepcopy(final_source["connection"])
    state["summary"]["data_source"]["filters"] = copy.deepcopy(final_source["filters"])
    for table_state in state["tables"]:
        caption_source = table_state["caption"]["data_source"]
        caption_source["connection"] = copy.deepcopy(final_source["connection"])
        caption_source["filters"] = copy.deepcopy(final_source["filters"])
    return state


def _issues_from_data_source_tool_log(tool_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for item in tool_log:
        if item.get("tool") != "ask_client":
            continue
        request = item["request"]
        issue = {
            "request_type": request["request_type"],
            "target": request.get("target", ""),
            "field": request["field"],
            "error_type": request["error_type"],
            "scope_error_type": request["scope_error_type"],
            "evidence": request["description"],
        }
        issues.append(issue)
    return issues
