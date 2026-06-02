from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import pandas as pd

from method.agents import (
    ClientAgent,
    ContentValidationAgent,
    SlideAnalysisAgent,
    SlideParserAgent,
    SlideReviewInput,
)
from method.pipeline import SlideReviewWorkflow

PRESENTATION_LABEL_RE = re.compile(r"\((bar chart|line chart|pie chart|table)\)\s*$", re.I)
TREND_RE = re.compile(r"\b(increase|increased|decrease|decreased|growth|decline|upward|downward)\b", re.I)


class TestRoleClient:
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
        non_text_elements = [element for element in elements if element.get("type") != "textBox"]

        for element in non_text_elements:
            shape_kind = str(element.get("shape_kind") or element.get("type") or "")
            if shape_kind in {"chart-bar", "chart-line", "chart-pie", "table"}:
                roles[str(element["id"])] = shape_kind
            elif element.get("type") == "table":
                roles[str(element["id"])] = "table"
            else:
                roles[str(element["id"])] = "chart-bar"

        caption_ids = []
        summary_ids = []
        for element in text_elements:
            text = str(element.get("text", "")).strip()
            element_id = str(element["id"])
            if PRESENTATION_LABEL_RE.search(text) or "analysis" in text.lower():
                caption_ids.append(element_id)
            elif TREND_RE.search(text) or any(char.isdigit() for char in text):
                summary_ids.append(element_id)

        title_candidates = [
            element
            for element in text_elements
            if str(element["id"]) not in caption_ids + summary_ids
        ]
        title_candidates.sort(
            key=lambda item: (
                item.get("layout", {}).get("y", 999.0),
                len(str(item.get("text", ""))),
            )
        )
        if not title_candidates and text_elements:
            title_candidates = sorted(
                text_elements,
                key=lambda item: (
                    item.get("layout", {}).get("y", 999.0),
                    len(str(item.get("text", ""))),
                ),
            )
        title_id = str(title_candidates[0]["id"]) if title_candidates else None

        for element in text_elements:
            element_id = str(element["id"])
            if element_id in roles:
                continue
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
            }
        )


class TestAnalysisClient:
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: Path | None = None,
        response_format: str | None = None,
    ) -> str:
        del image_path, response_format
        payload = json.loads(user_prompt)
        del system_prompt
        if {"caption", "row_headers", "column_headers"}.issubset(payload):
            return json.dumps(
                {
                    "connection": {"table": "beijing_new_house"},
                    "select_columns": ["date_code", "supply_sets", "trade_sets", "dim_area"],
                    "filters": {
                        "city": "Beijing",
                        "block": "Liangxiang",
                        "start_date": "2020-01-01",
                        "end_date": "2024-12-31",
                    },
                }
            )

        metric_names = [
            name for name in payload["table_data"][0] if name not in {"category", "year", "month"}
        ] or ["value"]
        return json.dumps(
            {
                "table_type": "field-constraint",
                "dimensions": [
                    {
                        "source_col": "date_code",
                        "target_col": "year",
                        "method": "period",
                        "time_granularity": "year",
                    }
                ],
                "metrics": [
                    {
                        "name": name,
                        "source_col": "trade_sets",
                        "agg_func": "count",
                        "filter_condition": {"trade_sets": 1},
                    }
                    for name in metric_names
                ],
                "crosstab_row": None,
                "crosstab_col": None,
            }
        )


class TestSummaryValidationClient:
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: Path | None = None,
        response_format: str | None = None,
    ) -> str:
        del system_prompt, user_prompt, image_path, response_format
        return json.dumps(
            {
                "status": "pass",
                "evidence": "No contradictory summary claim.",
                "suggested_summary": "",
                "confidence": 0.9,
            }
        )


class PassThroughDataSourceValidationAgent:
    def run_with_client(self, analysis_state, client):
        del client
        return {
            "analysis_state": analysis_state,
            "validation_log": [],
            "detected_issues": [],
        }


class FakeContentValidationAgent:
    def __init__(self, issues=None):
        self.issues = list(issues or [])

    def run_with_client(
        self,
        *,
        ppt_representation,
        analysis_state,
        client,
        artifact_dir,
    ):
        del ppt_representation, analysis_state, client
        artifact_dir.mkdir(parents=True, exist_ok=True)
        yaml_path = artifact_dir / "repaired_slide.yaml"
        yaml_path.write_text("title: Example\n", encoding="utf-8")
        return {
            "table_records": [],
            "content_validation_log": [],
            "detected_issues": self.issues,
            "update_log": [],
            "repaired_artifacts": {"yaml_path": str(yaml_path), "data_paths": {}, "pptx_path": None},
        }


class FeedbackPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sample_dir = Path(
            "output/benchmark/dataset_v2/split/test/s_00163f7ed3ede3ed/injected"
        )
        self.case_dir = next(path for path in sorted(self.sample_dir.iterdir()) if path.is_dir())

    def test_slide_parser_agent_builds_ppt_representation_and_csv(self) -> None:
        agent = SlideParserAgent(client=TestRoleClient())
        result = agent.run(
            SlideReviewInput(
                pptx_path=self.case_dir / "slide.pptx",
                image_path=self.case_dir / "slide.png",
            )
        )
        self.assertIn("observed_slide", result)
        self.assertIn("ppt_representation", result)
        self.assertNotIn("role_assignments", result)
        representation = result["ppt_representation"]
        self.assertNotIn("case_id", representation)
        self.assertIn("title", representation)
        self.assertIn("summary", representation)
        self.assertTrue(representation["structured_tables"])
        first_table = representation["structured_tables"][0]
        self.assertIn("header", first_table)
        self.assertIn("body", first_table)
        self.assertIn("data_path", first_table["body"])
        self.assertEqual(Path(first_table["body"]["data_path"]).parent, self.case_dir)
        self.assertTrue(Path(first_table["body"]["data_path"]).exists())
        self.assertIn("element_id", representation["summary"])
        self.assertNotIn("element_ids", representation["summary"])

    def test_pipeline_emits_detected_issues(self) -> None:
        workflow = SlideReviewWorkflow(
            slide_parser_agent=SlideParserAgent(client=TestRoleClient()),
            slide_analysis_agent=SlideAnalysisAgent(client=TestAnalysisClient()),
            data_source_validation_agent=PassThroughDataSourceValidationAgent(),
            content_validation_agent=FakeContentValidationAgent(
                issues=[
                    {
                        "targets": ["st.body"],
                        "error_types": ["value_error"],
                        "evidence": "synthetic mismatch",
                        "required_fields_guess": [],
                    }
                ]
            ),
        )
        result = workflow.run(
            SlideReviewInput(
                pptx_path=self.case_dir / "slide.pptx",
                image_path=self.case_dir / "slide.png",
            ),
            client_agent=ClientAgent(feedback_items=[]),
        )
        self.assertTrue(result.detected_issues)
        self.assertIn("tables", result.analysis_state)
        first_issue = result.detected_issues[0]
        self.assertIn("targets", first_issue)
        self.assertIn("error_types", first_issue)
        self.assertIn("required_fields_guess", first_issue)

    def test_verification_agent_flags_real_caption_presentation_mismatch(self) -> None:
        case_dir = Path(
            "output/benchmark/dataset_v2/split/test/s_00163f7ed3ede3ed/injected/00163f7ed3ede3ed-st_caption-935ecdac"
        )
        workflow = SlideReviewWorkflow(
            slide_parser_agent=SlideParserAgent(client=TestRoleClient()),
            slide_analysis_agent=SlideAnalysisAgent(client=TestAnalysisClient()),
            data_source_validation_agent=PassThroughDataSourceValidationAgent(),
            content_validation_agent=ContentValidationAgent(
                client=TestSummaryValidationClient()
            ),
        )
        result = workflow.run(
            SlideReviewInput(
                pptx_path=case_dir / "slide.pptx",
                image_path=case_dir / "slide.png",
            ),
            client_agent=ClientAgent(
                feedback_items=[
                    {
                        "request_type": "content_update_confirmation",
                        "table_index": 0,
                        "targets": ["st.caption"],
                        "fields": ["presentation_type"],
                        "decision": "accept",
                    }
                ]
            ),
        )
        caption_claim = [
            issue
            for issue in result.detected_issues
            if issue["targets"] == ["st.caption"] and "claim_error" in issue["error_types"]
        ]
        self.assertTrue(caption_claim)

    def test_verification_agent_no_longer_emits_logic_error(self) -> None:
        case_dir = Path(
            "output/benchmark/dataset_v2/split/test/s_00163f7ed3ede3ed/injected/00163f7ed3ede3ed-st_header-22248c0e"
        )
        parsed = SlideParserAgent(client=TestRoleClient()).run(
            SlideReviewInput(
                pptx_path=case_dir / "slide.pptx",
                image_path=case_dir / "slide.png",
            )
        )
        from method.agents import VerificationAgent

        first_table = parsed["ppt_representation"]["structured_tables"][0]
        analysis_state = {
            "title": parsed["ppt_representation"]["title"]["text"],
            "summary": parsed["ppt_representation"]["summary"]["text"],
            "tables": [
                {
                    "caption": first_table["caption"]["text"],
                    "data_path": first_table["body"]["data_path"],
                    "data_source": {
                        "connection": {"table": "beijing_new_house"},
                        "select_columns": ["date_code", "supply_sets", "trade_sets"],
                        "filters": {
                            "city": "Beijing",
                            "block": "Miyun District",
                            "start_date": "2020-01-01",
                            "end_date": "2024-12-31",
                        },
                    },
                    "calculation_logic": {
                        "table_type": "field-constraint",
                        "dimensions": [
                            {
                                "source_col": "date_code",
                                "target_col": "month",
                                "method": "period",
                                "time_granularity": "month",
                            }
                        ],
                        "metrics": [
                            {
                                "name": "supply_counts",
                                "source_col": "supply_sets",
                                "agg_func": "count",
                                "filter_condition": {"supply_sets": 1},
                            },
                            {
                                "name": "trade_counts",
                                "source_col": "trade_sets",
                                "agg_func": "count",
                                "filter_condition": {"trade_sets": 1},
                            },
                        ],
                        "crosstab_row": None,
                        "crosstab_col": None,
                    },
                }
            ],
        }
        detected = VerificationAgent().run(
            ppt_representation=parsed["ppt_representation"],
            analysis_state=analysis_state,
        )
        self.assertFalse(
            [
                issue
                for issue in detected
                if "logic_error" in issue["error_types"]
            ]
        )

    def test_verification_table_compare_allows_rounding_noise(self) -> None:
        from method.agents.verification_agent import _tables_equal

        visible = pd.DataFrame({"metric": ["supply_area"], "2020": [32770.0]})
        expected_with_rounding_noise = pd.DataFrame(
            {"metric": ["supply_area"], "2020": [32770.45]}
        )
        expected_with_real_delta = pd.DataFrame({"metric": ["supply_area"], "2020": [32771.0]})

        self.assertTrue(_tables_equal(visible, expected_with_rounding_noise))
        self.assertFalse(_tables_equal(visible, expected_with_real_delta))

    def test_ppt_representation_uses_csv_instead_of_nested_chart_payload(self) -> None:
        case_dir = Path(
            "output/benchmark/dataset_v2/split/test/s_00163f7ed3ede3ed/injected/00163f7ed3ede3ed-st_header-22248c0e"
        )
        parsed = SlideParserAgent(client=TestRoleClient()).run(
            SlideReviewInput(
                pptx_path=case_dir / "slide.pptx",
                image_path=case_dir / "slide.png",
            )
        )
        representation = parsed["ppt_representation"]
        first_table = representation["structured_tables"][0]
        csv_path = Path(first_table["body"]["data_path"])
        self.assertTrue(csv_path.exists())
        self.assertEqual(csv_path.parent, case_dir)
        self.assertNotIn("table_id", first_table)
        self.assertNotIn("data_csv_path", first_table)
        self.assertNotIn("body_type", first_table)
        self.assertNotIn("body_element_id", first_table)
        self.assertNotIn("raw_observed", first_table)
        self.assertNotIn("observed", first_table)
        self.assertNotIn("derived", first_table)
        self.assertIn("trade_counts", csv_path.read_text(encoding="utf-8"))
