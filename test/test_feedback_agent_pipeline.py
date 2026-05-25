from __future__ import annotations

import json
import unittest
from pathlib import Path

from benchmarking.evaluation import (
    ClientSimulator,
    FeedbackMatcher,
    SlideReviewEvaluator,
)
from method.agents import (
    HeuristicRoleLabeler,
    InteractionAgent,
    RepairExecutor,
    SlideParserAgent,
    SlideReviewInput,
)
from method.pipeline import SlideReviewWorkflow
from method.agents.verification_agent import VerificationAgent


class FeedbackMatcherTest(unittest.TestCase):
    def test_interaction_agent_explains_logic_error_request(self) -> None:
        request = InteractionAgent().build_request(
            {
                "targets": ["st.header"],
                "error_types": ["logic_error"],
                "evidence": "summary ties value 1914 to transaction, but it matches supply_counts.",
                "required_fields_guess": ["logic.metrics"],
            }
        )
        self.assertIn("summary ties value 1914", request["question"])
        self.assertIn("corrected metric list", request["question"])
        self.assertIn("source_col", request["question"])
        self.assertIn("suggested_response_schema", request)
        self.assertEqual(request["required_fields"], ["logic.metrics"])

    def test_required_fields_empty_must_match_empty_request(self) -> None:
        matcher = FeedbackMatcher()
        request = {
            "targets": ["summary"],
            "error_types": ["value_error"],
            "required_fields": [],
        }
        feedback_items = [
            {
                "targets": ["summary"],
                "error_types": ["value_error"],
                "required_fields": [],
                "state_patch": {},
            }
        ]
        matched = matcher.match(request, feedback_items)
        self.assertIsNotNone(matched)

    def test_multiple_feedback_items_are_matched_separately(self) -> None:
        episode = {
            "feedback_items": [
                {
                    "targets": ["summary"],
                    "error_types": ["scope_error"],
                    "required_fields": ["scope.start_year", "scope.end_year"],
                    "state_patch": {"scope": {"start_year": 2020, "end_year": 2024}},
                },
                {
                    "targets": ["summary"],
                    "error_types": ["value_error"],
                    "required_fields": [],
                    "state_patch": {},
                },
            ]
        }
        simulator = ClientSimulator(episode)
        first = simulator.respond(
            {
                "targets": ["summary"],
                "error_types": ["scope_error"],
                "required_fields": [
                    "scope.city",
                    "scope.block",
                    "scope.start_year",
                    "scope.end_year",
                ],
            }
        )
        second = simulator.respond(
            {
                "targets": ["summary"],
                "error_types": ["value_error"],
                "required_fields": [],
            }
        )
        self.assertTrue(first["matched"])
        self.assertTrue(second["matched"])
        self.assertEqual(len(simulator.matched_feedback_keys), 2)


class FeedbackEvaluatorTest(unittest.TestCase):
    def test_evaluator_metrics(self) -> None:
        evaluator = SlideReviewEvaluator()
        metrics = evaluator.evaluate_case(
            detected_issues=[
                {
                    "targets": ["summary"],
                    "error_types": ["scope_error"],
                    "evidence": "scope cue",
                    "required_fields_guess": ["scope.start_year", "scope.end_year"],
                },
                {
                    "targets": ["summary"],
                    "error_types": ["value_error"],
                    "evidence": "value cue",
                    "required_fields_guess": [],
                },
            ],
            interaction_log=[
                {
                    "matched_feedback_key": (
                        "errors=scope_error|targets=summary|fields=scope.end_year,scope.start_year"
                    )
                }
            ],
            corruption_record={
                "operations": [
                    {"target": "summary", "error_types": ["scope_error"]},
                    {"target": "summary", "error_types": ["value_error"]},
                ]
            },
            feedback_episode={
                "feedback_items": [
                    {
                        "targets": ["summary"],
                        "error_types": ["scope_error"],
                        "required_fields": ["scope.start_year", "scope.end_year"],
                    },
                    {
                        "targets": ["summary"],
                        "error_types": ["value_error"],
                        "required_fields": [],
                    },
                ]
            },
        )
        self.assertEqual(metrics["detection"]["recall"], 1.0)
        self.assertEqual(metrics["interaction"]["matched_feedback_items"], 1)


class FeedbackPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sample_dir = Path(
            "output/benchmark/dataset_v2/split/test/s_00163f7ed3ede3ed/injected"
        )
        self.case_dir = next(path for path in sorted(self.sample_dir.iterdir()) if path.is_dir())

    def test_slide_parser_agent_reuses_method_slide_parser(self) -> None:
        agent = SlideParserAgent(HeuristicRoleLabeler())
        result = agent.run(
            SlideReviewInput(
                case_id="sample",
                pptx_path=self.case_dir / "slide.pptx",
                image_path=self.case_dir / "slide.png",
            )
        )
        self.assertIn("observed_slide", result)
        self.assertTrue(result["observed_slide"]["elements"])

    def test_pipeline_emits_detected_issues_and_repair_stub(self) -> None:
        feedback_episode = json.loads(
            (self.case_dir / "feedback_episode.json").read_text(encoding="utf-8")
        )
        workflow = SlideReviewWorkflow(
            slide_parser_agent=SlideParserAgent(HeuristicRoleLabeler())
        )
        result = workflow.run(
            SlideReviewInput(
                case_id="sample",
                pptx_path=self.case_dir / "slide.pptx",
                image_path=self.case_dir / "slide.png",
            ),
            client_simulator=ClientSimulator(feedback_episode),
        )
        self.assertTrue(result.detected_issues)
        first_issue = result.detected_issues[0]
        self.assertIn("targets", first_issue)
        self.assertIn("error_types", first_issue)
        self.assertIn("required_fields_guess", first_issue)
        self.assertEqual(result.repair_plan["status"], "stub")

    def test_verification_agent_flags_real_caption_presentation_mismatch(self) -> None:
        case_dir = Path(
            "output/benchmark/dataset_v2/split/test/s_00163f7ed3ede3ed/injected/00163f7ed3ede3ed-st_caption-935ecdac"
        )
        workflow = SlideReviewWorkflow(
            slide_parser_agent=SlideParserAgent(HeuristicRoleLabeler())
        )
        result = workflow.run(
            SlideReviewInput(
                case_id="caption_case",
                pptx_path=case_dir / "slide.pptx",
                image_path=case_dir / "slide.png",
            ),
        )
        caption_claim = [
            issue
            for issue in result.detected_issues
            if issue["targets"] == ["st.caption"] and "claim_error" in issue["error_types"]
        ]
        self.assertTrue(caption_claim)

    def test_verification_agent_uses_st_data_for_logic_error(self) -> None:
        case_dir = Path(
            "output/benchmark/dataset_v2/split/test/s_00163f7ed3ede3ed/injected/00163f7ed3ede3ed-st_header-22248c0e"
        )
        agent = SlideParserAgent(HeuristicRoleLabeler())
        parsed = agent.run(
            SlideReviewInput(
                case_id="logic_case",
                pptx_path=case_dir / "slide.pptx",
                image_path=case_dir / "slide.png",
            )
        )
        from method.agents import StructureReasoningAgent

        structured = StructureReasoningAgent().run(
            parsed["observed_slide"],
            case_dir / "slide.pptx",
        )
        detected = VerificationAgent().run(parsed["observed_slide"], structured)
        header_logic = [
            issue
            for issue in detected
            if issue["targets"] == ["st.header"] and "logic_error" in issue["error_types"]
        ]
        self.assertTrue(header_logic)

    def test_structure_agent_builds_slideagent_inspired_query_tools(self) -> None:
        case_dir = Path(
            "output/benchmark/dataset_v2/split/test/s_00163f7ed3ede3ed/injected/00163f7ed3ede3ed-st_header-22248c0e"
        )
        parsed = SlideParserAgent(HeuristicRoleLabeler()).run(
            SlideReviewInput(
                case_id="tool_case",
                pptx_path=case_dir / "slide.pptx",
                image_path=case_dir / "slide.png",
            )
        )
        from method.agents import StructureReasoningAgent

        structured = StructureReasoningAgent().run(
            parsed["observed_slide"],
            case_dir / "slide.pptx",
        )
        self.assertTrue(structured["query_intents"])
        self.assertTrue(structured["analysis_logic"])
        self.assertTrue(structured["aggregation_profiles"])
        query_intent = structured["query_intents"][0]
        self.assertIn("date_code", query_intent["select_columns"])
        self.assertIn("trade_sets", query_intent["select_columns"])
        self.assertEqual(query_intent["filters"]["start_year"], 2020)
        metric_kinds = {
            metric["metric_kind"]
            for logic in structured["analysis_logic"]
            for metric in logic["metrics"]
        }
        self.assertIn("transaction", metric_kinds)
        self.assertIn("supply", metric_kinds)

    def test_repair_executor_stub_interface(self) -> None:
        executor = RepairExecutor()
        plan = executor.plan(
            observed_slide={"elements": [{"id": "1"}]},
            repair_state={"scope": {}, "logic": {}, "claim": {}, "targets_to_repair": ["summary"]},
            source_pptx=Path("sample.pptx"),
        )
        self.assertEqual(plan["status"], "stub")
        self.assertIn("required_inputs", plan)
