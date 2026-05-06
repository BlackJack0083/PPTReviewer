from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from benchmarking.fine_grained import (
    build_corruption,
    save_yaml,
    write_corruption_outputs,
)
from benchmarking.fine_grained.common import append_jsonl
from benchmarking.fine_grained.mutations import (
    choose_candidate_bundle,
    materialize_summary_ops,
    mutate_caption_chart_type,
    mutate_caption_scope_object,
    mutate_chart_metric_label,
    mutate_metric_label,
    mutate_summary_numeric_value,
    mutate_summary_scope,
    mutate_table_metric_label,
    mutate_text_value,
    mutation_signature,
    summary_scope_candidates,
    summary_value_candidates,
)
from benchmarking.fine_grained.validator import infer_error_family, validate_benchmark
from engine.data_files import read_dataframe_csv, write_dataframe_csv
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
            [[1, 2.5], [3, 4.0]], index=["A", "B"], columns=["2020", "value"]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.csv"
            write_dataframe_csv(df, path)
            rebuilt = read_dataframe_csv(path)
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

    def test_choose_candidate_bundle_prefers_larger_combinations(self) -> None:
        rng = random.Random(9)  # noqa: S311
        candidates = [
            {
                "mutation_type": "summary_scope_city",
                "semantic_slot": "Geo_City_Name",
                "override_kind": "slot",
                "override_value": "Guangzhou",
            },
            {
                "mutation_type": "numeric_delta",
                "semantic_slot": "Metric_Volume",
                "override_kind": "slot",
                "override_value": "5200",
            },
        ]

        bundle = choose_candidate_bundle(candidates, max_slots_per_sample=2, rng=rng)

        self.assertIsNotNone(bundle)
        if bundle is None:
            self.fail("Expected two-slot candidate bundle")
        self.assertEqual(len(bundle), 2)

    def test_summary_materialization_can_merge_scope_and_numeric_slots(self) -> None:
        data = minimal_slide_yaml()
        elem = data["template_slide"]["elements"][1]
        summary_truth = {
            "summary_template": (
                "{{ Geo_City_Name }} market recorded {{ Metric_Volume_Dominant_Cluster }} "
                "units from {{ Temporal_Start_Year }} to {{ Temporal_End_Year }}."
            ),
            "fixed_context": {
                "Geo_City_Name": "Beijing",
                "Temporal_Start_Year": "2020",
                "Temporal_End_Year": "2024",
            },
            "truth_slots": {
                "Metric_Volume_Dominant_Cluster": "4605",
            },
        }
        scope_rng = random.Random(11)  # noqa: S311
        value_rng = random.Random(12)  # noqa: S311
        scope_candidate = next(
            candidate
            for candidate in summary_scope_candidates(data, summary_truth, scope_rng)
            if candidate["mutation_type"] == "summary_scope_city"
        )
        value_candidate = next(
            candidate
            for candidate in summary_value_candidates(summary_truth, value_rng)
            if candidate["mutation_type"] == "numeric_delta"
        )

        ops = materialize_summary_ops(
            elem,
            summary_truth,
            [scope_candidate, value_candidate],
        )

        self.assertEqual(len(ops), 2)
        self.assertEqual(
            {op["mutation_type"] for op in ops},
            {"summary_scope_city", "numeric_delta"},
        )
        after_text = ops[0]["_after"]
        self.assertNotIn("Beijing market recorded 4605 units", after_text)
        self.assertIn("units", after_text)

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

    def test_metric_label_swap_mutates_chart_metric_names(self) -> None:
        data = minimal_slide_yaml()
        data["template_slide"]["elements"].append(
            {
                "id": "4",
                "type": "chart",
                "role": "chart-bar",
                "layout": {"x": 1.0, "y": 4.0, "width": 12.0, "height": 7.0},
                "args": {
                    "table_type": "field-constraint",
                    "dimensions": [],
                    "metrics": [
                        {
                            "name": "Supply Count",
                            "source_col": "supply_sets",
                            "agg_func": "count",
                            "filter_condition": {"supply_sets": 1},
                        },
                        {
                            "name": "Sales Count",
                            "source_col": "trade_sets",
                            "agg_func": "count",
                            "filter_condition": {"trade_sets": 1},
                        },
                    ],
                },
            }
        )
        rng = random.Random(21)  # noqa: S311

        op = mutate_metric_label(data, rng)

        self.assertIsNotNone(op)
        if op is None:
            self.fail("Expected metric label mutation")
        self.assertEqual(op["target"], "st.header")
        self.assertEqual(op["mutation_type"], "series_metric_swap")
        self.assertEqual(op["semantic_slot"], "series_label")
        metrics = data["template_slide"]["elements"][3]["args"]["metrics"]
        self.assertEqual(metrics[0]["name"], "Sales Count")
        self.assertEqual(metrics[1]["name"], "Supply Count")

    def test_chart_metric_label_helper_mutates_chart_metric_names(self) -> None:
        data = minimal_slide_yaml()
        data["template_slide"]["elements"].append(
            {
                "id": "4",
                "type": "chart",
                "role": "chart-line",
                "layout": {"x": 1.0, "y": 4.0, "width": 12.0, "height": 7.0},
                "args": {
                    "table_type": "field-constraint",
                    "dimensions": [],
                    "metrics": [
                        {"name": "supply_counts", "source_col": "supply_sets", "agg_func": "count"},
                        {"name": "trade_counts", "source_col": "trade_sets", "agg_func": "count"},
                    ],
                },
            }
        )
        rng = random.Random(41)  # noqa: S311

        op = mutate_chart_metric_label(data, rng)

        self.assertIsNotNone(op)
        if op is None:
            self.fail("Expected chart metric label mutation")
        self.assertEqual(op["mutation_type"], "series_metric_swap")
        metrics = data["template_slide"]["elements"][3]["args"]["metrics"]
        self.assertEqual(
            [metric["name"] for metric in metrics],
            ["trade_counts", "supply_counts"],
        )

    def test_yaml_importer_aligns_chart_dataframe_with_swapped_metric_names(self) -> None:
        df = pd.DataFrame(
            [[10, 20], [30, 40]],
            index=["Supply Count", "Sales Count"],
            columns=["80-100m²", "100-120m²"],
        )
        config = YAMLImporter.build_config_from_yaml(
            {
                "table_type": "field-constraint",
                "dimensions": [],
                "metrics": [
                    {
                        "name": "Sales Count",
                        "source_col": "supply_sets",
                        "agg_func": "count",
                    },
                    {
                        "name": "Supply Count",
                        "source_col": "trade_sets",
                        "agg_func": "count",
                    },
                ],
            }
        )

        aligned = YAMLImporter.align_chart_dataframe_with_config(df, config)

        self.assertEqual(list(aligned.index), ["Sales Count", "Supply Count"])
        self.assertEqual(aligned.iloc[0, 0], 10)
        self.assertEqual(aligned.iloc[1, 0], 30)

    def test_table_metric_label_helper_swaps_metric_column_only(self) -> None:
        data = minimal_slide_yaml()
        data["template_slide"]["elements"].append(
            {
                "id": "4",
                "type": "table",
                "role": "table",
                "layout": {"x": 1.0, "y": 4.0, "width": 12.0, "height": 7.0},
            }
        )
        df = pd.DataFrame(
            {
                "metric": ["trade_counts", "avg_unit_price", "dim_area"],
                "2020": [515, 40917, 52058],
                "2021": [611, 41144, 56601],
            }
        )
        rng = random.Random(51)  # noqa: S311

        op = mutate_table_metric_label(data, data["template_slide"]["elements"][3], df, rng)

        self.assertIsNotNone(op)
        if op is None:
            self.fail("Expected table metric label mutation")
        self.assertEqual(op["mutation_type"], "table_metric_swap")
        rebuilt = data["template_slide"]["elements"][3]["_dataframe_override"]
        self.assertNotEqual(
            rebuilt["metric"].tolist(),
            ["trade_counts", "avg_unit_price", "dim_area"],
        )
        self.assertEqual(
            sorted(rebuilt["metric"].tolist()),
            sorted(["trade_counts", "avg_unit_price", "dim_area"]),
        )
        self.assertEqual(rebuilt["2020"].tolist(), [515, 40917, 52058])

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

    def test_metric_label_corruption_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gt_dir = root / "split" / "test" / "s_sample1" / "gt"
            gt_dir.mkdir(parents=True)
            yaml_data = minimal_slide_yaml()
            yaml_data["template_slide"]["elements"].append(
                {
                    "id": "4",
                    "type": "chart",
                    "role": "chart-bar",
                    "layout": {"x": 1.0, "y": 4.0, "width": 12.0, "height": 7.0},
                    "data": "./data/element_4.csv",
                    "args": {
                        "table_type": "field-constraint",
                        "dimensions": [],
                        "metrics": [
                            {
                                "name": "Supply Count",
                                "source_col": "supply_sets",
                                "agg_func": "count",
                                "filter_condition": {"supply_sets": 1},
                            },
                            {
                                "name": "Sales Count",
                                "source_col": "trade_sets",
                                "agg_func": "count",
                                "filter_condition": {"trade_sets": 1},
                            },
                        ],
                    },
                }
            )
            save_yaml(gt_dir / "slide.yaml", yaml_data)
            write_dataframe_csv(
                pd.DataFrame(
                    [[10, 20], [30, 40]],
                    index=["Supply Count", "Sales Count"],
                    columns=["80-100m²", "100-120m²"],
                ),
                gt_dir / "data" / "element_4.csv",
            )

            sample_row = {
                "sample_id": "sample1",
                "split": "test",
                "sample_dir": "split/test/s_sample1",
                "gt_yaml": "split/test/s_sample1/gt/slide.yaml",
                "gt_ppt": "split/test/s_sample1/gt/slide.pptx",
                "template_id": "T01_Supply_Trans_Bar",
            }

            result = build_corruption(root, sample_row, "metric_label", seed=23)
            self.assertIsNotNone(result)
            if result is None:
                self.fail("Expected metric_label corruption")
            mutated_yaml, corruption, _artifact_id = result
            op = corruption["operations"][0]
            self.assertEqual(op["target"], "st.header")
            self.assertEqual(op["mutation_type"], "series_metric_swap")
            metrics = mutated_yaml["template_slide"]["elements"][3]["args"]["metrics"]
            self.assertEqual(
                [metric["name"] for metric in metrics],
                ["Sales Count", "Supply Count"],
            )

    def test_metric_label_table_corruption_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gt_dir = root / "split" / "test" / "s_sample1" / "gt"
            gt_dir.mkdir(parents=True)
            yaml_data = {
                "meta": {"template_id": "T05_Resale_Summary_Table"},
                "query_filters": {
                    "city": "Shenzhen",
                    "block": "Songgang Intelligent Manufacturing Eco-City",
                    "start_date": "2020-01-01",
                    "end_date": "2024-12-31",
                },
                "slide_filters": [],
                "template_slide": {
                    "slide_size": {"width": 25.4, "height": 14.29},
                    "elements": [
                        {
                            "id": "1",
                            "type": "textBox",
                            "role": "slide-title",
                            "text": "Resale-House Capacity & Structure",
                            "layout": {"x": 0.5, "y": 1.0, "width": 24.0, "height": 1.1},
                        },
                        {
                            "id": "2",
                            "type": "table",
                            "role": "table",
                            "layout": {"x": 1.0, "y": 4.0, "width": 22.0, "height": 7.0},
                        },
                    ],
                },
            }
            save_yaml(gt_dir / "slide.yaml", yaml_data)

            data = YAMLImporter.load_yaml(gt_dir / "slide.yaml")
            rebuilt_df = pd.DataFrame(
                {
                    "metric": ["trade_counts", "avg_unit_price", "dim_area"],
                    "2020": [515, 40917, 52058],
                    "2021": [611, 41144, 56601],
                }
            )
            op = mutate_table_metric_label(
                data,
                data["template_slide"]["elements"][1],
                rebuilt_df,
                random.Random(61),  # noqa: S311
            )

            self.assertIsNotNone(op)
            if op is None:
                self.fail("Expected table metric swap")
            self.assertEqual(op["target"], "st.header")
            self.assertEqual(op["mutation_type"], "table_metric_swap")
            swapped = data["template_slide"]["elements"][1]["_dataframe_override"]
            self.assertNotEqual(
                swapped["metric"].tolist(),
                ["trade_counts", "avg_unit_price", "dim_area"],
            )
            self.assertEqual(
                sorted(swapped["metric"].tolist()),
                sorted(["trade_counts", "avg_unit_price", "dim_area"]),
            )

    def test_validator_infers_metric_label_family(self) -> None:
        family = infer_error_family(
            {
                "operations": [
                    {
                        "target": "st.header",
                        "element_id": "4",
                        "role": "chart-bar",
                        "mutation_type": "series_metric_swap",
                    }
                ]
            }
        )

        self.assertEqual(family, "metric_label")

    def test_st_caption_can_generate_multi_slot_corruption(self) -> None:
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
            }

            result = build_corruption(
                root,
                sample_row,
                "st_caption",
                seed=13,
                max_slots_per_sample=2,
            )

            self.assertIsNotNone(result)
            if result is None:
                self.fail("Expected st_caption corruption")
            _yaml_data, corruption, _artifact_id = result
            self.assertEqual(len(corruption["operations"]), 2)

    def test_build_corruption_can_avoid_used_signature(self) -> None:
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
            }

            first = build_corruption(
                root,
                sample_row,
                "st_caption",
                seed=17,
                max_slots_per_sample=2,
            )
            self.assertIsNotNone(first)
            if first is None:
                self.fail("Expected first corruption")
            first_signature = mutation_signature(first[1]["operations"])

            second = build_corruption(
                root,
                sample_row,
                "st_caption",
                seed=17,
                max_slots_per_sample=2,
                disallow_signatures={first_signature},
            )
            self.assertIsNotNone(second)
            if second is None:
                self.fail("Expected alternative corruption")
            second_signature = mutation_signature(second[1]["operations"])
            self.assertNotEqual(first_signature, second_signature)

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

    def test_validator_accepts_metric_label_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gt_dir = root / "split" / "test" / "s_sample1" / "gt"
            gt_dir.mkdir(parents=True)
            yaml_data = minimal_slide_yaml()
            yaml_data["template_slide"]["elements"].append(
                {
                    "id": "4",
                    "type": "chart",
                    "role": "chart-bar",
                    "layout": {"x": 1.0, "y": 4.0, "width": 12.0, "height": 7.0},
                    "data": "./data/element_4.csv",
                    "args": {
                        "table_type": "field-constraint",
                        "dimensions": [],
                        "metrics": [
                            {
                                "name": "Supply Count",
                                "source_col": "supply_sets",
                                "agg_func": "count",
                                "filter_condition": {"supply_sets": 1},
                            },
                            {
                                "name": "Sales Count",
                                "source_col": "trade_sets",
                                "agg_func": "count",
                                "filter_condition": {"trade_sets": 1},
                            },
                        ],
                    },
                }
            )
            save_yaml(gt_dir / "slide.yaml", yaml_data)
            write_dataframe_csv(
                pd.DataFrame(
                    [[10, 20], [30, 40]],
                    index=["Supply Count", "Sales Count"],
                    columns=["80-100m²", "100-120m²"],
                ),
                gt_dir / "data" / "element_4.csv",
            )

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

            mutated_yaml, corruption, artifact_id = build_corruption(
                root, sample_row, "metric_label", seed=31
            )
            record = write_corruption_outputs(
                dataset_root=root,
                sample_row=sample_row,
                yaml_data=mutated_yaml,
                corruption=corruption,
                artifact_id=artifact_id,
                render_png=False,
                skip_ppt=True,
            )
            append_jsonl(root / "manifest" / "corruptions.jsonl", record)

            validation, coverage = validate_benchmark(root)

            self.assertTrue(validation["valid"])
            self.assertEqual(coverage["by_family"]["metric_label"], 1)

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
