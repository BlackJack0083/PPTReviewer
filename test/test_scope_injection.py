from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from benchmarking.fine_grained.mutations import build_corruption
from benchmarking.fine_grained.scope import (
    applicable_scope_issue,
    apply_scope_issues,
    extract_scope_carriers,
    resolve_scope_issues,
)
from core import resource_manager


class ScopeInjectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        resource_manager.load_all()

    def test_extract_scope_carriers_uses_only_declared_text_binding_slots(self) -> None:
        carriers = extract_scope_carriers(_slide_yaml())

        summary = carriers[0]
        caption = carriers[1]
        self.assertEqual(summary["source"], "summary")
        self.assertNotIn("city", summary["fields"])
        self.assertIn("block", summary["fields"])
        self.assertIn("time_range", summary["fields"])
        self.assertEqual(caption["fields"]["city"]["value"], "Beijing")

    def test_resolver_does_not_treat_absent_summary_city_as_missing(self) -> None:
        issues = resolve_scope_issues(
            _slide_yaml(),
            valid_values={
                "city": {"Beijing"},
                "block": {"Miyun District"},
            },
        )

        self.assertEqual(issues, [])

    def test_conflict_requires_two_carriers_for_field(self) -> None:
        carriers = extract_scope_carriers(_slide_yaml())

        self.assertFalse(
            applicable_scope_issue(
                carriers,
                {"field": "city", "scope_error_type": "conflict"},
            )
        )
        self.assertTrue(
            applicable_scope_issue(
                carriers,
                {"field": "block", "scope_error_type": "conflict"},
            )
        )

    def test_apply_scope_conflict_edits_one_carrier_and_rerenders(self) -> None:
        mutated, operations = apply_scope_issues(
            _slide_yaml(),
            [{"field": "block", "scope_error_type": "conflict"}],
            replacement_values={"block": {"Geo_Block_Name": "Nanshan CBD"}},
        )

        issues = resolve_scope_issues(
            mutated,
            valid_values={
                "city": {"Beijing", "Shenzhen"},
                "block": {"Miyun District", "Nanshan CBD"},
            },
        )
        self.assertEqual(issues, [{"field": "block", "scope_error_type": "conflict"}])
        self.assertEqual(len(operations), 1)
        self.assertIn("Nanshan CBD", mutated["template_slide"]["elements"][1]["text"])
        self.assertIn("Miyun District", mutated["template_slide"]["elements"][2]["text"])

    def test_apply_scope_missing_edits_all_carriers_for_field(self) -> None:
        mutated, operations = apply_scope_issues(
            _slide_yaml(),
            [{"field": "block", "scope_error_type": "missing"}],
        )

        issues = resolve_scope_issues(mutated)
        self.assertEqual(issues, [{"field": "block", "scope_error_type": "missing"}])
        self.assertEqual(len(operations), 2)
        self.assertNotIn("Miyun District", mutated["template_slide"]["elements"][1]["text"])
        self.assertNotIn("Miyun District", mutated["template_slide"]["elements"][2]["text"])

    def test_apply_scope_time_error_reverses_all_time_carriers(self) -> None:
        mutated, operations = apply_scope_issues(
            _slide_yaml(),
            [{"field": "time_range", "scope_error_type": "error"}],
            replacement_values={
                "time_range": {
                    "Temporal_Start_Year": "2025",
                    "Temporal_End_Year": "2024",
                }
            },
        )

        issues = resolve_scope_issues(mutated)
        self.assertEqual(
            issues,
            [{"field": "time_range", "scope_error_type": "error"}],
        )
        self.assertEqual(len(operations), 2)
        self.assertIn("**2025** to **2024**", mutated["template_slide"]["elements"][1]["text"])
        self.assertIn("**2025**-**2024**", mutated["template_slide"]["elements"][2]["text"])

    def test_apply_scope_error_requires_replacement_values(self) -> None:
        with self.assertRaises(ValueError):
            apply_scope_issues(
                _slide_yaml(),
                [{"field": "city", "scope_error_type": "error"}],
            )

    def test_apply_scope_unmatch_uses_required_donor_values(self) -> None:
        mutated, _operations = apply_scope_issues(
            _slide_yaml(),
            [{"field": "city", "scope_error_type": "unmatch"}],
            replacement_values={"city": {"Geo_City_Name": "Shenzhen"}},
        )

        issues = resolve_scope_issues(
            mutated,
            valid_values={"city": {"Beijing", "Shenzhen"}},
            unmatched_fields={"city"},
        )
        self.assertEqual(issues, [{"field": "city", "scope_error_type": "unmatch"}])
        self.assertIn("Shenzhen", mutated["template_slide"]["elements"][2]["text"])

    def test_build_corruption_supports_scope_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gt_yaml = root / "split" / "test" / "s_1" / "gt" / "slide.yaml"
            gt_yaml.parent.mkdir(parents=True)
            gt_yaml.write_text(
                yaml.safe_dump(_slide_yaml(), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            result = build_corruption(
                root,
                {
                    "sample_id": "1",
                    "gt_yaml": "split/test/s_1/gt/slide.yaml",
                },
                "scope",
                seed=7,
                max_slots_per_sample=1,
            )

        self.assertIsNotNone(result)
        if result is None:
            return
        _mutated, corruption, artifact_id = result
        operation = corruption["operations"][0]
        self.assertTrue(artifact_id.startswith("1-scope-"))
        self.assertEqual(operation["error_types"], ["scope_error"])
        self.assertIn(operation["field"], {"city", "block", "time_range"})
        self.assertIn(
            operation["scope_error_type"],
            {"missing", "error", "unmatch", "conflict"},
        )

    def test_build_corruption_supports_value_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gt_yaml = root / "split" / "test" / "s_1" / "gt" / "slide.yaml"
            gt_yaml.parent.mkdir(parents=True)
            gt_yaml.write_text(
                yaml.safe_dump(_slide_yaml(), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            result = build_corruption(
                root,
                {
                    "sample_id": "1",
                    "gt_yaml": "split/test/s_1/gt/slide.yaml",
                },
                "value",
                seed=11,
                max_slots_per_sample=1,
            )

        self.assertIsNotNone(result)
        if result is None:
            return
        mutated, corruption, artifact_id = result
        operation = corruption["operations"][0]
        self.assertTrue(artifact_id.startswith("1-value-"))
        self.assertEqual(operation["mutation_type"], "value_summary_slot")
        self.assertEqual(operation["error_types"], ["value_error"])
        self.assertNotEqual(operation["before"], operation["after"])
        self.assertIn(operation["after"], mutated["template_slide"]["elements"][1]["text"])

    def test_build_corruption_supports_claim_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slide = _slide_yaml()
            slide["template_slide"]["elements"][1]["text_binding"]["slots"][
                "Trend_Trajectory_Type"
            ] = {
                "category": "claim",
                "value": "increased",
                "value_type": "trend",
            }
            gt_yaml = root / "split" / "test" / "s_1" / "gt" / "slide.yaml"
            gt_yaml.parent.mkdir(parents=True)
            gt_yaml.write_text(
                yaml.safe_dump(slide, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            result = build_corruption(
                root,
                {
                    "sample_id": "1",
                    "gt_yaml": "split/test/s_1/gt/slide.yaml",
                },
                "claim",
                seed=13,
                max_slots_per_sample=1,
            )

        self.assertIsNotNone(result)
        if result is None:
            return
        _mutated, corruption, artifact_id = result
        operation = corruption["operations"][0]
        self.assertTrue(artifact_id.startswith("1-claim-"))
        self.assertEqual(operation["error_types"], ["claim_error"])
        self.assertIn(
            operation["mutation_type"],
            {"claim_caption_presentation", "claim_summary_slot"},
        )


def _slide_yaml() -> dict:
    return {
        "meta": {"template_id": "T09_Monthly_Supply_Bar"},
        "query_filters": {
            "city": "Beijing",
            "block": "Miyun District",
            "start_date": "2020-01-01",
            "end_date": "2024-12-31",
        },
        "slide_filters": [],
        "template_slide": {
            "elements": [
                {
                    "id": "1",
                    "type": "textBox",
                    "role": "slide-title",
                    "text": "Monthly Supply",
                },
                {
                    "id": "2",
                    "type": "textBox",
                    "role": "body-text",
                    "text": "From 2020 to 2024, Miyun District traded 136 units.",
                    "text_binding": {
                        "kind": "summary",
                        "render": {
                            "theme_key": "Monthly Supply Analysis",
                            "function_key": "Monthly Supply Volume",
                            "variant_idx": 0,
                        },
                        "slots": {
                            "Temporal_Start_Year": {
                                "category": "scope",
                                "field": "start_year",
                                "value": "2020",
                                "value_type": "number",
                            },
                            "Temporal_End_Year": {
                                "category": "scope",
                                "field": "end_year",
                                "value": "2024",
                                "value_type": "number",
                            },
                            "Geo_Block_Name": {
                                "category": "scope",
                                "field": "block",
                                "value": "Miyun District",
                                "value_type": "string",
                            },
                            "Metric_Volume_Trade_Average": {
                                "category": "value",
                                "value": "136",
                                "value_type": "number",
                            },
                        },
                    },
                },
                {
                    "id": "3",
                    "type": "textBox",
                    "role": "caption",
                    "text": "Beijing Miyun District 2020-2024 (Bar chart)",
                    "text_binding": {
                        "kind": "caption",
                        "render": {
                            "theme_key": "Monthly Supply Analysis",
                            "function_key": "Monthly Supply Volume",
                            "function_index": 0,
                            "view_label": "Bar chart",
                        },
                        "slots": {
                            "Geo_City_Name": {
                                "category": "scope",
                                "field": "city",
                                "value": "Beijing",
                                "value_type": "string",
                            },
                            "Geo_Block_Name": {
                                "category": "scope",
                                "field": "block",
                                "value": "Miyun District",
                                "value_type": "string",
                            },
                            "Temporal_Start_Year": {
                                "category": "scope",
                                "field": "start_year",
                                "value": "2020",
                                "value_type": "number",
                            },
                            "Temporal_End_Year": {
                                "category": "scope",
                                "field": "end_year",
                                "value": "2024",
                                "value_type": "number",
                            },
                            "Chart_View_Label": {
                                "category": "claim",
                                "field": "presentation_type",
                                "value": "Bar chart",
                                "value_type": "string",
                            },
                        },
                    },
                },
            ]
        },
    }


if __name__ == "__main__":
    unittest.main()
