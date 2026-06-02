from __future__ import annotations

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

    def run(
        self,
        slide_input: SlideReviewInput,
        *,
        client_agent,
    ) -> SlideReviewResult:
        parsed = self.slide_parser_agent.run(slide_input)
        observed_slide = parsed["observed_slide"]
        ppt_representation = parsed["ppt_representation"]
        analysis_state = self.slide_analysis_agent.run(
            ppt_representation=ppt_representation,
        )
        data_source_result = self.data_source_validation_agent.run_with_client(
            analysis_state=analysis_state,
            client=client_agent,
        )
        analysis_state = data_source_result["analysis_state"]
        data_source_validation_log = data_source_result["validation_log"]

        artifact_dir = slide_input.pptx_path.parent / "review_artifacts"
        content_result = self.content_validation_agent.run_with_client(
            ppt_representation=ppt_representation,
            analysis_state=analysis_state,
            client=client_agent,
            artifact_dir=artifact_dir,
        )
        detected_issues = [
            *data_source_result["detected_issues"],
            *content_result["detected_issues"],
        ]
        return SlideReviewResult(
            observed_slide=observed_slide,
            ppt_representation=ppt_representation,
            analysis_state=analysis_state,
            data_source_validation_log=data_source_validation_log,
            content_validation_log=content_result["content_validation_log"],
            detected_issues=detected_issues,
            table_records=content_result["table_records"],
            update_log=content_result["update_log"],
            repaired_artifacts=content_result["repaired_artifacts"],
        )
