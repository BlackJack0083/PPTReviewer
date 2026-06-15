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
from benchmarking.fine_grained.common import append_jsonl, mutate_number
from benchmarking.fine_grained.mutations import (
    _mutate_claim_value,
    build_recipe_corruption,
    mutation_signature,
)
from benchmarking.fine_grained.runner import load_recipes
from benchmarking.fine_grained.validator import infer_error_family, validate_benchmark
from core import resource_manager
from engine.data_files import read_dataframe_csv, write_dataframe_csv


class FineGrainedInjectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        resource_manager.load_all()

    def test_build_corruption_rejects_unknown_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            build_corruption(
                Path(tmp),
                {"sample_id": "s1", "gt_yaml": "missing.yaml"},
                "title",
                seed=1,
            )

    def test_value_family_can_mutate_table_cell_and_write_output_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_row = _write_sample(root, _slide_yaml_with_chart())
            data_path = root / "split" / "test" / "s_1" / "gt" / "data" / "element_4.csv"
            write_dataframe_csv(
                pd.DataFrame({"category": ["2020", "2021"], "trade_counts": [10, 20]}),
                data_path,
            )

            result = build_corruption(
                root,
                sample_row,
                "value",
                seed=2,
                disallow_signatures={("value_summary_slot",)},
            )

            self.assertIsNotNone(result)
            if result is None:
                return
            mutated, corruption, artifact_id = result
            self.assertEqual(mutation_signature(corruption["operations"]), ("value_table_cell",))
            record = write_corruption_outputs(
                dataset_root=root,
                sample_row=sample_row,
                yaml_data=mutated,
                corruption=corruption,
                artifact_id=artifact_id,
                render_ppt=False,
                render_png=False,
            )
            output_yaml = root / record["output_yaml"]
            output_data = read_dataframe_csv(output_yaml.parent / "data" / "element_4.csv")
            self.assertFalse(
                output_data.equals(
                    pd.DataFrame({"category": ["2020", "2021"], "trade_counts": [10, 20]})
                )
            )

    def test_recipe_config_loads_ordered_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recipes.yaml"
            path.write_text(
                """
recipes:
  - samples_per_split: 3
    max_variants_per_gt: 2
    max_variants_per_type: 1
    recipe:
      - family: scope
        num_errors: 1
      - family: value
        num_errors: 1
""",
                encoding="utf-8",
            )

            recipes = load_recipes(path)

            self.assertEqual(recipes[0]["recipe"][0], {"family": "scope", "num_errors": 1})
            self.assertEqual(recipes[0]["recipe"][1], {"family": "value", "num_errors": 1})

    def test_recipe_corruption_can_mix_value_and_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_row = _write_sample(root, _slide_yaml_with_chart())
            write_dataframe_csv(
                pd.DataFrame({"category": ["2020", "2021"], "trade_counts": [10, 20]}),
                root / "split" / "test" / "s_1" / "gt" / "data" / "element_4.csv",
            )

            result = build_recipe_corruption(
                root,
                sample_row,
                {
                    "recipe": [
                        {"family": "value", "num_errors": 1},
                        {"family": "claim", "num_errors": 1},
                    ],
                },
                seed=3,
            )

            self.assertIsNotNone(result)
            if result is None:
                return
            _mutated, corruption, artifact_id = result
            self.assertTrue(artifact_id.startswith("s_1-value1-claim1-"))
            self.assertEqual(
                corruption["recipe"],
                [
                    {"family": "value", "num_errors": 1},
                    {"family": "claim", "num_errors": 1},
                ],
            )
            self.assertNotIn("recipe_name", corruption)
            self.assertEqual(
                {operation["error_types"][0] for operation in corruption["operations"]},
                {"value_error", "claim_error"},
            )

    def test_recipe_corruption_can_build_multiple_value_suberrors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_row = _write_sample(root, _slide_yaml_with_chart())
            write_dataframe_csv(
                pd.DataFrame({"category": ["2020", "2021"], "trade_counts": [10, 20]}),
                root / "split" / "test" / "s_1" / "gt" / "data" / "element_4.csv",
            )

            result = build_recipe_corruption(
                root,
                sample_row,
                {"recipe": [{"family": "value", "num_errors": 2}]},
                seed=9,
            )

            self.assertIsNotNone(result)
            if result is None:
                return
            _mutated, corruption, _artifact_id = result
            self.assertEqual(
                {operation["mutation_type"] for operation in corruption["operations"]},
                {"value_table_cell", "value_summary_slot"},
            )

    def test_recipe_corruption_can_build_multiple_claim_suberrors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slide = _slide_yaml_with_chart()
            slide["template_slide"]["elements"][1]["text_binding"]["slots"][
                "Trend_Trajectory_Type"
            ] = {
                "category": "claim",
                "value": "increased",
            }
            sample_row = _write_sample(root, slide)

            result = build_recipe_corruption(
                root,
                sample_row,
                {"recipe": [{"family": "claim", "num_errors": 2}]},
                seed=9,
            )

            self.assertIsNotNone(result)
            if result is None:
                return
            _mutated, corruption, _artifact_id = result
            self.assertEqual(
                {operation["mutation_type"] for operation in corruption["operations"]},
                {"claim_caption_presentation", "claim_summary_slot"},
            )

    def test_recipe_corruption_can_build_multiple_scope_suberrors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_row = _write_sample(root, _slide_yaml_with_chart())

            result = build_recipe_corruption(
                root,
                sample_row,
                {
                    "recipe": [{"family": "scope", "num_errors": 2}],
                },
                seed=7,
            )

            self.assertIsNotNone(result)
            if result is None:
                return
            _mutated, corruption, _artifact_id = result
            scope_fields = {
                operation["field"]
                for operation in corruption["operations"]
                if operation["error_types"] == ["scope_error"]
            }
            self.assertGreaterEqual(len(scope_fields), 2)

    def test_number_mutation_is_seed_controlled_and_diverse(self) -> None:
        mutated_values = {
            str(mutate_number("100", random.Random(seed))) for seed in range(20)  # noqa: S311
        }

        self.assertGreaterEqual(len(mutated_values), 4)
        self.assertNotIn("100", mutated_values)

    def test_claim_mutation_uses_pairwise_opposite_for_one_token(self) -> None:
        self.assertEqual(
            _mutate_claim_value("sales increased steadily", random.Random(0)),  # noqa: S311
            "sales decreased steadily",
        )
        self.assertEqual(
            _mutate_claim_value("equivalent to an increase of 20 units", random.Random(0)),  # noqa: S311
            "equivalent to a decrease of 20 units",
        )
        self.assertEqual(
            _mutate_claim_value("a buyer-favorable market", random.Random(0)),  # noqa: S311
            "a seller-favorable market",
        )

    def test_claim_mutation_can_vary_replaced_token_when_multiple_claims_exist(self) -> None:
        mutated_values = {
            _mutate_claim_value("sales increased with an upward trend", random.Random(seed))  # noqa: S311
            for seed in range(20)
        }

        self.assertGreaterEqual(len(mutated_values), 2)
        self.assertNotIn("sales increased with an upward trend", mutated_values)

    def test_validator_reports_new_schema_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_row = _write_sample(root, _slide_yaml_with_chart())
            write_dataframe_csv(
                pd.DataFrame({"category": ["2020", "2021"], "trade_counts": [10, 20]}),
                root / "split" / "test" / "s_1" / "gt" / "data" / "element_4.csv",
            )
            for family, mutation_type, target in (
                ("scope", "scope_city_error", "st.caption"),
                ("value", "value_summary_slot", "summary"),
                ("claim", "claim_caption_presentation", "st.caption"),
            ):
                corruption = {
                    "operations": [
                        {
                            "target": target,
                            "element_id": "3" if target == "st.caption" else "2",
                            "mutation_type": mutation_type,
                            "error_types": [f"{family}_error" if family != "claim" else "claim_error"],
                        }
                    ],
                    "expected_repair_yaml": sample_row["gt_yaml"],
                }
                record = write_corruption_outputs(
                    dataset_root=root,
                    sample_row=sample_row,
                    yaml_data=_slide_yaml_with_chart(),
                    corruption=corruption,
                    artifact_id=f"{family}-case",
                    render_ppt=False,
                    render_png=False,
                )
                append_jsonl(root / "manifest" / "corruptions.jsonl", record)

            _validation, coverage = validate_benchmark(root)

            self.assertEqual(coverage["by_family"]["scope"], 1)
            self.assertEqual(coverage["by_family"]["value"], 1)
            self.assertEqual(coverage["by_family"]["claim"], 1)

    def test_infer_error_family_returns_unknown_for_unsupported_mutation(self) -> None:
        self.assertEqual(
            infer_error_family(
                {
                    "operations": [
                        {
                            "target": "title",
                            "element_id": "1",
                            "mutation_type": "unsupported_mutation",
                        }
                    ]
                }
            ),
            "unknown",
        )

    def test_infer_error_family_returns_mixed_for_cross_family_recipe(self) -> None:
        self.assertEqual(
            infer_error_family(
                {
                    "operations": [
                        {
                            "target": "summary",
                            "element_id": "2",
                            "mutation_type": "value_summary_slot",
                        },
                        {
                            "target": "st.caption",
                            "element_id": "3",
                            "mutation_type": "claim_caption_presentation",
                        },
                    ]
                }
            ),
            "mixed",
        )


def _write_sample(root: Path, yaml_data: dict) -> dict:
    sample_dir = root / "split" / "test" / "s_1"
    gt_dir = sample_dir / "gt"
    gt_dir.mkdir(parents=True)
    save_yaml(gt_dir / "slide.yaml", yaml_data)
    row = {
        "sample_id": "s_1",
        "split": "test",
        "sample_dir": "split/test/s_1",
        "gt_yaml": "split/test/s_1/gt/slide.yaml",
        "gt_ppt": "split/test/s_1/gt/slide.pptx",
        "template_id": "T09_Monthly_Supply_Bar",
        "layout_type": "single_column_bar",
        "city_key": "beijing",
    }
    append_jsonl(root / "manifest" / "samples.jsonl", row)
    return row


def _slide_yaml_with_chart() -> dict:
    return {
        "meta": {"template_id": "T09_Monthly_Supply_Bar"},
        "query_filters": {
            "city": "Beijing",
            "block": "Liangxiang",
            "start_date": "2020-01-01",
            "end_date": "2024-12-31",
        },
        "slide_filters": [
            {
                "connection": {"table": ["beijing_new_house"]},
                "select_columns": ["date_code", "trade_sets"],
                "filters": {
                    "city": "Beijing",
                    "block": "Liangxiang",
                    "start_date": "2020-01-01",
                    "end_date": "2024-12-31",
                },
            }
        ],
        "template_slide": {
            "slide_size": {"width": 19.05, "height": 14.29},
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
                    "text": "From **2020** to **2024**, **Liangxiang** averaged **20** transactions.",
                    "text_binding": {
                        "kind": "summary",
                        "render": {
                            "theme_key": "Monthly Supply Analysis",
                            "function_key": "Monthly Supply Volume",
                            "variant_idx": 0,
                        },
                        "slots": {
                            "Temporal_Start_Year": {"category": "scope", "value": "2020"},
                            "Temporal_End_Year": {"category": "scope", "value": "2024"},
                            "Geo_Block_Name": {"category": "scope", "value": "Liangxiang"},
                            "Metric_Volume_Trade_Peak": {"category": "value", "value": "20"},
                            "Temporal_Month_Peak": {"category": "value", "value": "2021-01"},
                            "Metric_Volume_Trade_Average": {"category": "value", "value": "20"},
                            "Metric_Supply_Demand_Ratio": {"category": "value", "value": "80"},
                        },
                    },
                },
                {
                    "id": "3",
                    "type": "textBox",
                    "role": "caption",
                    "text": "**Beijing Liangxiang** Monthly Supply & Transactions (**2020**-**2024**) (Bar chart)",
                    "text_binding": {
                        "kind": "caption",
                        "render": {
                            "theme_key": "Monthly Supply Analysis",
                            "function_key": "Monthly Supply Volume",
                            "function_index": 0,
                            "view_label": "Bar chart",
                        },
                        "slots": {
                            "Geo_City_Name": {"category": "scope", "value": "Beijing"},
                            "Geo_Block_Name": {"category": "scope", "value": "Liangxiang"},
                            "Temporal_Start_Year": {"category": "scope", "value": "2020"},
                            "Temporal_End_Year": {"category": "scope", "value": "2024"},
                            "Chart_View_Label": {
                                "category": "claim",
                                "value": "Bar chart",
                                "value_type": "string",
                            },
                        },
                    },
                },
                {
                    "id": "4",
                    "type": "chart",
                    "role": "chart-bar",
                    "data": "./data/element_4.csv",
                },
            ],
        },
    }
