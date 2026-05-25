from __future__ import annotations

from method.agents import (
    InteractionAgent,
    RepairExecutor,
    SlideParserAgent,
    SlideReviewResult,
    StructureReasoningAgent,
    VerificationAgent,
)
from method.agents.types import SlideReviewInput


class SlideReviewWorkflow:
    """Run slide diagnosis, user-feedback interaction, and repair planning."""

    def __init__(
        self,
        *,
        slide_parser_agent: SlideParserAgent,
        structure_reasoning_agent: StructureReasoningAgent | None = None,
        verification_agent: VerificationAgent | None = None,
        interaction_agent: InteractionAgent | None = None,
        repair_executor: RepairExecutor | None = None,
    ):
        self.slide_parser_agent = slide_parser_agent
        self.structure_reasoning_agent = structure_reasoning_agent or StructureReasoningAgent()
        self.verification_agent = verification_agent or VerificationAgent()
        self.interaction_agent = interaction_agent or InteractionAgent()
        self.repair_executor = repair_executor or RepairExecutor()

    def run(
        self,
        slide_input: SlideReviewInput,
        client_simulator=None,
    ) -> SlideReviewResult:
        parsed = self.slide_parser_agent.run(slide_input)
        observed_slide = parsed["observed_slide"]
        structured_understanding = self.structure_reasoning_agent.run(
            observed_slide,
            slide_input.pptx_path,
        )
        detected_issues = self.verification_agent.run(
            observed_slide=observed_slide,
            structured_understanding=structured_understanding,
        )
        interaction = self.interaction_agent.run(
            detected_issues=detected_issues,
            client=client_simulator,
        )
        repair_plan = self.repair_executor.plan(
            observed_slide=observed_slide,
            repair_state=interaction["repair_state"],
            source_pptx=slide_input.pptx_path,
        )
        return SlideReviewResult(
            observed_slide=observed_slide,
            structured_understanding=structured_understanding,
            detected_issues=detected_issues,
            interaction_log=interaction["interaction_log"],
            repair_state=interaction["repair_state"],
            repair_plan=repair_plan,
        )
