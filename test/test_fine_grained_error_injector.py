from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from benchmarking.fine_grained import (
    build_corruption,
    dataframe_to_split_payload,
    save_yaml,
    write_corruption_outputs,
)
from benchmarking.fine_grained.common import append_jsonl
from benchmarking.fine_grained.mutations import (
    mutate_caption_chart_type,
    mutate_caption_scope_object,
    mutate_summary_numeric_value,
    mutate_summary_scope,
    mutate_text_value,
)
from benchmarking.fine_grained.validator import validate_benchmark
from engine.yaml_importer import YAMLImporter


def minimal_slide_yaml() -> dict:
    return {
        "meta": {
            "template_id": "T01_Supply_Trans_Bar",
            "layout_type": "single_column_bar",
            "style_id": "marketing_orange_green",
            "theme_key": "Block Area Segment Distribution",
            "function_keys": ["Supply-Transaction Unit Statistic"],
        },
        "query_filters": {
            "city": "Beijing",
            "block": "Liangxiang",
            "start_date": "2020-01-01",
            "end_date": "2024-12-31",
        },
        "slide_filters": [],
        "template_slide": {
            "slide_size": {"width": 19.05, "height": 14.29},
            "elements": [
                {
                    "id": "1",
                    "type": "textBox",
                    "role": "slide-title",
                    "text": "Block Area Segment Distribution",
                    "layout": {"x": 0.5, "y": 1.0, "width": 18.0, "height": 1.1},
                },
                {
                    "id": "2",
                    "type": "textBox",
                    "role": "body-text",
                    "text": "Market activity increased by **20**%.",
                    "layout": {"x": 0.5, "y": 2.0, "width": 18.0, "height": 1.0},
                },
                {
                    "id": "3",
                    "type": "textBox",
                    "role": "caption",
                    "text": "Beijing Liangxiang analysis 2020-2024",
                    "layout": {"x": 1.0, "y": 3.5, "width": 12.0, "height": 1.0},
                },
            ],
        },
        "summary_binding": {
            "summary_template": "Market activity {{ Enum_Trend }} by **{{ Metric_Pct }}**%.",
            "summary_slots_truth": {
                "Enum_Trend": "increased",
                "Metric_Pct": "20",
            },
            "summary_context_fixed": {},
            "summary_slot_overrides": {},
            "target_text_role": "body-text",
        },
    }


class FineGrainedInjectorTest(unittest.TestCase):
    def test_dataframe_split_roundtrip(self) -> None:
        df = pd.DataFrame(
            [[1, 2.5], [3, 4.0]], index=["A", "B"], columns=[2020, "value"]
        )
        payload = dataframe_to_split_payload(df)
        rebuilt = YAMLImporter.dataframe_from_split_payload(payload)
        pd.testing.assert_frame_equal(rebuilt, df)

    def test_caption_chart_type_mismatch_uses_visible_text(self) -> None:
        elem = {
            "id": "3",
            "type": "textBox",
            "role": "caption",
            "text": "Beijing Liangxiang analysis 2020-2024 (Bar chart)",
        }

        op = mutate_caption_chart_type(elem, rng=random.Random(1))  # noqa: S311

        self.assertIsNotNone(op)
        self.assertEqual(op["target"], "st.caption")
        self.assertEqual(op["mutation_type"], "caption_chart_type_mismatch")
        self.assertEqual(op["truth_basis"], "visible_rendering")
        self.assertFalse(op["after"].endswith("(Bar chart)"))
        self.assertRegex(op["after"], r"\((Line chart|Pie chart|Table)\)$")

    def test_caption_scope_object_uses_real_block_donor(self) -> None:
        data = minimal_slide_yaml()
        elem = data["template_slide"]["elements"][2]

        op = mutate_caption_scope_object(data, elem, rng=random.Random(3))  # noqa: S311

        self.assertIsNotNone(op)
        self.assertEqual(op["target"], "st.caption")
        self.assertEqual(op["mutation_type"], "caption_scope_object")
        self.assertEqual(op["truth_basis"], "query_filters")
        self.assertEqual(op["scope_field"], "block")
        self.assertEqual(op["truth_value"], "Liangxiang")
        self.assertNotEqual(op["wrong_value"], "Liangxiang")
        self.assertIn(op["wrong_value"], op["after"])
        self.assertNotIn("Liangxiang East", op["after"])

    def test_summary_scope_can_mutate_time_city_and_real_block(self) -> None:
        data = minimal_slide_yaml()
        elem = data["template_slide"]["elements"][1]
        elem["text"] = "Beijing Liangxiang market from 2020 to 2024 increased by 20%."

        ops = mutate_summary_scope(data, elem, rng=random.Random(4))  # noqa: S311
        mutation_types = {op["mutation_type"] for op in ops}

        self.assertIn("summary_scope_year", mutation_types)
        self.assertIn("summary_scope_city", mutation_types)
        self.assertIn("summary_scope_object", mutation_types)
        object_op = next(op for op in ops if op["mutation_type"] == "summary_scope_object")
        self.assertEqual(object_op["truth_basis"], "query_filters")
        self.assertEqual(object_op["scope_field"], "block")
        self.assertEqual(object_op["truth_value"], "Liangxiang")
        self.assertNotEqual(object_op["wrong_value"], "Liangxiang")
        self.assertIn(object_op["wrong_value"], object_op["after"])

    def test_summary_text_value_does_not_emit_placeholder_drift(self) -> None:
        self.assertIsNone(mutate_text_value("core band", rng=random.Random(5)))  # noqa: S311

    def test_summary_numeric_delta_skips_years_and_temporal_slots(self) -> None:
        self.assertIsNone(
            mutate_summary_numeric_value("2020", rng=random.Random(1), slot_name="Temporal_Start_Year")  # noqa: S311
        )
        self.assertIsNone(
            mutate_summary_numeric_value("From 2020 to 2024", rng=random.Random(1))  # noqa: S311
        )

        mutation = mutate_summary_numeric_value("total volume reached 16716 units", rng=random.Random(1))  # noqa: S311

        self.assertIsNotNone(mutation)
        if mutation is None:
            self.fail("Expected numeric_delta mutation")
        after, mutation_type = mutation
        self.assertEqual(mutation_type, "numeric_delta")
        self.assertNotEqual(after, "total volume reached 16716 units")
        self.assertIn("units", after)

        percent_mutation = mutate_summary_numeric_value("growth reached 20%", rng=random.Random(1))  # noqa: S311
        self.assertIsNotNone(percent_mutation)
        if percent_mutation is None:
            self.fail("Expected percent numeric_delta mutation")
        percent_after, percent_mutation_type = percent_mutation
        self.assertEqual(percent_mutation_type, "numeric_delta")
        self.assertRegex(percent_after, r"growth reached \d+%")
        self.assertNotEqual(percent_after, "growth reached 20%")

    def test_summary_numeric_range_delta_skips_year_ranges(self) -> None:
        self.assertIsNone(
            mutate_summary_numeric_value("2020-2024", rng=random.Random(2))  # noqa: S311
        )

        mutation = mutate_summary_numeric_value("80-100m²", rng=random.Random(2))  # noqa: S311

        self.assertIsNotNone(mutation)
        if mutation is None:
            self.fail("Expected range_delta mutation")
        after, mutation_type = mutation
        self.assertEqual(mutation_type, "range_delta")
        self.assertNotEqual(after, "80-100m²")
        self.assertTrue(after.endswith("m²"))

    def test_summary_title_corruption_schema_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gt_dir = root / "split" / "test" / "s_sample1" / "gt"
            gt_dir.mkdir(parents=True)
            save_yaml(gt_dir / "slide.yaml", minimal_slide_yaml())

            sample_row = {
                "sample_id": "sample1",
                "split": "test",
                "sample_dir": "split/test/s_sample1",
                "gt_yaml": "split/test/s_sample1/gt/slide.yaml",
                "gt_ppt": "split/test/s_sample1/gt/slide.pptx",
                "template_id": "T01_Supply_Trans_Bar",
                "layout_type": "single_column_bar",
                "city_key": "beijing",
            }

            result = build_corruption(root, sample_row, "summary_title", seed=7)
            self.assertIsNotNone(result)
            yaml_data, corruption = result

            self.assertEqual(corruption["schema_version"], "fine-grained-v1")
            self.assertEqual(corruption["error_family"], "summary_title")
            self.assertEqual(corruption["targets"], ["summary", "title"])
            self.assertEqual(len(corruption["expected_operations"]), 2)
            for op, repair_op in zip(
                corruption["operations"],
                corruption["expected_operations"],
                strict=False,
            ):
                self.assertEqual(op["before"], repair_op["after"])
                self.assertEqual(op["after"], repair_op["before"])

            record = write_corruption_outputs(
                dataset_root=root,
                sample_row=sample_row,
                yaml_data=yaml_data,
                corruption=corruption,
                render_png=False,
                skip_ppt=True,
            )
            self.assertTrue((root / record["output_yaml"]).exists())
            self.assertTrue((root / record["corruption_json"]).exists())
            self.assertIsNone(record["output_ppt"])

    def test_validator_accepts_valid_manifest_and_reports_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gt_dir = root / "split" / "test" / "s_sample1" / "gt"
            gt_dir.mkdir(parents=True)
            save_yaml(gt_dir / "slide.yaml", minimal_slide_yaml())

            sample_row = {
                "sample_id": "sample1",
                "split": "test",
                "sample_dir": "split/test/s_sample1",
                "gt_yaml": "split/test/s_sample1/gt/slide.yaml",
                "gt_ppt": None,
                "template_id": "T01_Supply_Trans_Bar",
                "layout_type": "single_column_bar",
                "city_key": "beijing",
            }
            append_jsonl(root / "manifest" / "samples.jsonl", sample_row)

            yaml_data, corruption = build_corruption(
                root, sample_row, "summary_title", seed=7
            )
            record = write_corruption_outputs(
                dataset_root=root,
                sample_row=sample_row,
                yaml_data=yaml_data,
                corruption=corruption,
                render_png=False,
                skip_ppt=True,
            )
            append_jsonl(root / "manifest" / "corruptions.jsonl", record)

            validation, coverage = validate_benchmark(root)

            self.assertTrue(validation["valid"])
            self.assertEqual(validation["error_count"], 0)
            self.assertEqual(coverage["summary"]["total_corruptions"], 1)
            self.assertEqual(coverage["by_family"]["summary_title"], 1)
            self.assertGreaterEqual(len(coverage["missing_template_family"]), 1)

    def test_validator_rejects_missing_output_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = {
                "schema_version": "fine-grained-v1",
                "corruption_id": "bad-1",
                "sample_id": "sample1",
                "error_family": "summary",
                "error_type": "numeric_delta",
                "targets": ["summary"],
                "observability": "observable",
                "repair_mode": "unique_repair",
                "requires_user_feedback": False,
                "seed": 1,
                "operations": [
                    {
                        "target": "summary",
                        "element_id": "1",
                        "role": "body-text",
                        "before": "a",
                        "after": "b",
                        "mutation_type": "numeric_delta",
                        "truth_basis": "gt_yaml",
                    }
                ],
                "expected_operations": [
                    {
                        "target": "summary",
                        "element_id": "1",
                        "role": "body-text",
                        "before": "b",
                        "after": "a",
                        "mutation_type": "repair_numeric_delta",
                        "truth_basis": "gt_yaml",
                    }
                ],
                "expected_repair_yaml": "split/test/s_sample1/gt/slide.yaml",
                "source_yaml": "split/test/s_sample1/gt/slide.yaml",
                "output_yaml": "split/test/s_sample1/injected/bad-1/slide.yaml",
                "corruption_json": "split/test/s_sample1/injected/bad-1/corruption.json",
            }
            append_jsonl(root / "manifest" / "corruptions.jsonl", record)

            validation, _coverage = validate_benchmark(root)

            self.assertFalse(validation["valid"])
            self.assertIn(
                "path_not_found", {error["code"] for error in validation["errors"]}
            )


if __name__ == "__main__":
    unittest.main()
