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
        rng = random.Random(1)  # noqa: S311
        elem = {
            "id": "3",
            "type": "textBox",
            "role": "caption",
            "text": "Beijing Liangxiang analysis 2020-2024 (Bar chart)",
        }

        op = mutate_caption_chart_type(minimal_slide_yaml(), elem, rng=rng)

        self.assertIsNotNone(op)
        self.assertEqual(op["target"], "st.caption")
        self.assertEqual(op["mutation_type"], "caption_chart_type_mismatch")
        self.assertEqual(op["semantic_slot"], "Chart_View_Label")
        self.assertFalse(op["_after"].endswith("(Bar chart)"))
        self.assertRegex(op["_after"], r"\((Line chart|Pie chart|Table)\)$")

    def test_caption_scope_object_uses_real_block_donor(self) -> None:
        data = minimal_slide_yaml()
        elem = data["template_slide"]["elements"][2]
        rng = random.Random(3)  # noqa: S311

        op = mutate_caption_scope_object(data, elem, rng=rng)

        self.assertIsNotNone(op)
        self.assertEqual(op["target"], "st.caption")
        self.assertEqual(op["mutation_type"], "caption_scope_object")
        self.assertEqual(op["semantic_slot"], "Geo_Block_Name")
        self.assertNotEqual(op["_after"], elem["text"])
        self.assertNotIn("Liangxiang East", op["_after"])

    def test_summary_scope_can_mutate_time_city_and_real_block(self) -> None:
        data = minimal_slide_yaml()
        elem = data["template_slide"]["elements"][1]
        rng = random.Random(4)  # noqa: S311
        summary_truth = {
            "summary_template": (
                "{{ Geo_City_Name }} {{ Geo_Block_Name }} market from "
                "{{ Temporal_Start_Year }} to {{ Temporal_End_Year }} increased by 20%."
            ),
            "fixed_context": {
                "Geo_City_Name": "Beijing",
                "Geo_Block_Name": "Liangxiang",
                "Temporal_Start_Year": "2020",
                "Temporal_End_Year": "2024",
            },
            "truth_slots": {},
        }
        elem["text"] = (
            "Beijing Liangxiang market from 2020 to 2024 increased by 20%."
        )

        ops = mutate_summary_scope(data, elem, summary_truth, rng=rng)
        mutation_types = {op["mutation_type"] for op in ops}

        self.assertIn("summary_scope_year", mutation_types)
        self.assertIn("summary_scope_city", mutation_types)
        self.assertIn("summary_scope_object", mutation_types)
        object_op = next(
            op for op in ops if op["mutation_type"] == "summary_scope_object"
        )
        self.assertEqual(object_op["semantic_slot"], "Geo_Block_Name")
        self.assertNotEqual(object_op["_after"], elem["text"])

    def test_summary_scope_skips_missing_scope_slots(self) -> None:
        data = minimal_slide_yaml()
        elem = data["template_slide"]["elements"][1]
        rng = random.Random(4)  # noqa: S311
        summary_truth = {
            "summary_template": (
                "The {{ Seg_Area_Stratum_Dominant }} segment led with "
                "{{ Metric_Volume_Dominant_Cluster }} units."
            ),
            "fixed_context": {},
            "truth_slots": {
                "Seg_Area_Stratum_Dominant": "80-100m²",
                "Metric_Volume_Dominant_Cluster": "4605",
            },
        }

        ops = mutate_summary_scope(data, elem, summary_truth, rng=rng)

        self.assertEqual(ops, [])

    def test_summary_text_value_does_not_emit_placeholder_drift(self) -> None:
        rng = random.Random(5)  # noqa: S311
        self.assertIsNone(mutate_text_value("core band", rng=rng))

    def test_summary_numeric_delta_skips_years_and_temporal_slots(self) -> None:
        rng = random.Random(1)  # noqa: S311
        self.assertIsNone(
            mutate_summary_numeric_value("2020", rng=rng, slot_name="Temporal_Start_Year")
        )
        rng = random.Random(1)  # noqa: S311
        self.assertIsNone(
            mutate_summary_numeric_value("From 2020 to 2024", rng=rng)
        )

        rng = random.Random(1)  # noqa: S311
        mutation = mutate_summary_numeric_value("total volume reached 16716 units", rng=rng)

        self.assertIsNotNone(mutation)
        if mutation is None:
            self.fail("Expected numeric_delta mutation")
        after, mutation_type = mutation
        self.assertEqual(mutation_type, "numeric_delta")
        self.assertNotEqual(after, "total volume reached 16716 units")
        self.assertIn("units", after)

        rng = random.Random(1)  # noqa: S311
        percent_mutation = mutate_summary_numeric_value("growth reached 20%", rng=rng)
        self.assertIsNotNone(percent_mutation)
        if percent_mutation is None:
            self.fail("Expected percent numeric_delta mutation")
        percent_after, percent_mutation_type = percent_mutation
        self.assertEqual(percent_mutation_type, "numeric_delta")
        self.assertRegex(percent_after, r"growth reached \d+%")
        self.assertNotEqual(percent_after, "growth reached 20%")

    def test_summary_numeric_range_delta_skips_year_ranges(self) -> None:
        rng = random.Random(2)  # noqa: S311
        self.assertIsNone(
            mutate_summary_numeric_value("2020-2024", rng=rng)
        )

        rng = random.Random(2)  # noqa: S311
        mutation = mutate_summary_numeric_value("80-100m²", rng=rng)

        self.assertIsNotNone(mutation)
        if mutation is None:
            self.fail("Expected range_delta mutation")
        after, mutation_type = mutation
        self.assertEqual(mutation_type, "range_delta")
        self.assertNotEqual(after, "80-100m²")
        self.assertTrue(after.endswith("m²"))

    def test_title_corruption_schema_and_outputs(self) -> None:
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

            result = build_corruption(root, sample_row, "title", seed=7)
            self.assertIsNotNone(result)
            yaml_data, corruption, artifact_id = result

            self.assertNotIn("corruption", yaml_data)
            self.assertEqual(len(corruption["operations"]), 1)
            op = corruption["operations"][0]
            self.assertEqual(op["target"], "title")
            self.assertEqual(op["mutation_type"], "title_theme_drift")
            self.assertEqual(op["semantic_slot"], "title")
            self.assertNotIn("before", op)
            self.assertNotIn("after", op)
            self.assertNotIn("truth_basis", op)

            record = write_corruption_outputs(
                dataset_root=root,
                sample_row=sample_row,
                yaml_data=yaml_data,
                corruption=corruption,
                artifact_id=artifact_id,
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

            yaml_data, corruption, artifact_id = build_corruption(
                root, sample_row, "title", seed=7
            )
            record = write_corruption_outputs(
                dataset_root=root,
                sample_row=sample_row,
                yaml_data=yaml_data,
                corruption=corruption,
                artifact_id=artifact_id,
                render_png=False,
                skip_ppt=True,
            )
            append_jsonl(root / "manifest" / "corruptions.jsonl", record)

            validation, coverage = validate_benchmark(root)

            self.assertTrue(validation["valid"])
            self.assertEqual(validation["error_count"], 0)
            self.assertEqual(coverage["summary"]["total_corruptions"], 1)
            self.assertEqual(coverage["by_family"]["title"], 1)
            self.assertGreaterEqual(len(coverage["missing_template_family"]), 1)

    def test_validator_rejects_missing_output_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = {
                "operations": [
                    {
                        "target": "summary",
                        "element_id": "1",
                        "role": "body-text",
                        "mutation_type": "numeric_delta",
                        "semantic_slot": "Metric_Test",
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
