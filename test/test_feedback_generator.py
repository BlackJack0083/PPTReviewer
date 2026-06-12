from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from benchmarking.feedback.generator import build_episode, generate_feedback_episodes


def sample_gt_yaml() -> dict:
    return {
        "meta": {"template_id": "T01_Supply_Trans_Bar"},
        "query_filters": {
            "city": "Beijing",
            "block": "Liangxiang",
            "start_date": "2020-01-01",
            "end_date": "2024-12-31",
        },
        "slide_filters": [
            {
                "connection": {"table": ["beijing_new_house"]},
                "select_columns": ["date_code", "supply_sets", "trade_sets", "dim_area"],
                "filters": {
                    "city": "Beijing",
                    "block": "Liangxiang",
                    "start_date": "2020-01-01",
                    "end_date": "2024-12-31",
                },
            }
        ],
        "template_slide": {
            "elements": [
                {
                    "id": "1",
                    "type": "textBox",
                    "role": "slide-title",
                    "text": "Block Area Segment Distribution",
                },
                {
                    "id": "3",
                    "type": "textBox",
                    "role": "caption",
                    "text": "Beijing Liangxiang analysis 2020-2024 (Bar chart)",
                },
                {
                    "id": "4",
                    "type": "chart",
                    "role": "chart-bar",
                    "args": {
                        "table_type": "field-constraint",
                        "dimensions": [
                            {
                                "source_col": "dim_area",
                                "target_col": "area_range",
                            }
                        ],
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
                },
            ]
        },
    }


def sample_table_gt_yaml() -> dict:
    return {
        "meta": {"template_id": "T05_Resale_Summary_Table"},
        "query_filters": {
            "city": "Shenzhen",
            "block": "Guanlan High-Tech Zone",
            "start_date": "2020-01-01",
            "end_date": "2024-12-31",
        },
        "slide_filters": [
            {
                "connection": {"table": ["shenzhen_new_house"]},
                "select_columns": [
                    "date_code",
                    "trade_sets",
                    "dim_unit_price",
                    "dim_area",
                ],
                "filters": {
                    "city": "Shenzhen",
                    "block": "Guanlan High-Tech Zone",
                    "start_date": "2020-01-01",
                    "end_date": "2024-12-31",
                },
            }
        ],
        "template_slide": {
            "elements": [
                {
                    "id": "1",
                    "type": "textBox",
                    "role": "slide-title",
                    "text": "Resale-House Capacity & Structure",
                },
                {
                    "id": "4",
                    "type": "table",
                    "role": "table",
                    "data": "./data/element_4.csv",
                    "args": {
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
                                "name": "trade_counts",
                                "source_col": "trade_sets",
                                "agg_func": "count",
                                "filter_condition": {"trade_sets": 1},
                            },
                            {
                                "name": "avg_unit_price",
                                "source_col": "dim_unit_price",
                                "agg_func": "mean",
                                "filter_condition": {"trade_sets": 1},
                            },
                            {
                                "name": "dim_area",
                                "source_col": "dim_area",
                                "agg_func": "sum",
                                "filter_condition": {"trade_sets": 1},
                            },
                        ],
                    },
                },
            ]
        },
    }


def write_gt(root: Path, data: dict, sample_id: str = "s_1") -> Path:
    gt_yaml_path = root / "split" / "test" / sample_id / "gt" / "slide.yaml"
    gt_yaml_path.parent.mkdir(parents=True)
    gt_yaml_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return gt_yaml_path


class FeedbackGeneratorTest(unittest.TestCase):
    def test_build_episode_logic_for_st_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_gt(root, sample_gt_yaml())
            record = {
                "source_yaml": "split/test/s_1/gt/slide.yaml",
                "output_yaml": "split/test/s_1/injected/x/slide.yaml",
                "operations": [
                    {
                        "target": "st.header",
                        "element_id": "4",
                        "mutation_type": "chart_metric_label_swap",
                        "error_types": ["logic_error"],
                    }
                ],
            }

            episode = build_episode(root, record)

            item = episode["feedback_items"][0]
            self.assertEqual(item["request_type"], "calculation_logic_clarification")
            self.assertEqual(item["error_type"], "logic_error")
            self.assertEqual(item["target"], "st.header")
            self.assertEqual(item["field"], "metrics")
            self.assertIn("calculation_logic=", item["response"])
            self.assertIn("Supply Count", item["response"])
            self.assertIn("Sales Count", item["response"])
            self.assertNotIn("state_patch", item)

    def test_build_episode_logic_for_table_st_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gt_yaml_path = write_gt(root, sample_table_gt_yaml(), "s_2")
            (gt_yaml_path.parent / "data").mkdir(parents=True)
            (gt_yaml_path.parent / "data" / "element_4.csv").write_text(
                "__index__,metric,2020,2021,2022\n"
                "0,trade_counts,1,2,3\n"
                "1,avg_unit_price,10,11,12\n"
                "2,dim_area,100,110,120\n",
                encoding="utf-8",
            )
            record = {
                "source_yaml": "split/test/s_2/gt/slide.yaml",
                "output_yaml": "split/test/s_2/injected/x/slide.yaml",
                "operations": [
                    {
                        "target": "st.header",
                        "element_id": "4",
                        "mutation_type": "table_metric_label_swap",
                    }
                ],
            }

            episode = build_episode(root, record)

            item = episode["feedback_items"][0]
            self.assertEqual(item["request_type"], "calculation_logic_clarification")
            self.assertEqual(item["error_type"], "logic_error")
            self.assertEqual(item["target"], "st.header")
            self.assertEqual(item["field"], "metrics")
            self.assertIn("calculation_logic=", item["response"])
            self.assertIn("trade_counts", item["response"])
            self.assertIn("avg_unit_price", item["response"])
            self.assertIn("dim_area", item["response"])
            self.assertNotIn("state_patch", item)

    def test_scope_and_value_errors_split_into_two_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_gt(root, sample_gt_yaml())
            record = {
                "source_yaml": "split/test/s_1/gt/slide.yaml",
                "output_yaml": "split/test/s_1/injected/x/slide.yaml",
                "operations": [
                    {
                        "target": "summary",
                        "mutation_type": "scope_time_range_shift",
                    },
                    {
                        "target": "summary",
                        "mutation_type": "numeric_value_perturbation",
                    },
                ],
            }

            episode = build_episode(root, record)

            self.assertEqual(
                episode,
                {
                    "feedback_items": [
                        {
                            "request_type": "data_source_slot_clarification",
                            "error_type": "scope_error",
                            "scope_error_type": "error",
                            "target": "summary",
                            "field": "time_range",
                            "response": (
                                "Please use start_date=2020-01-01, "
                                "end_date=2024-12-31."
                            ),
                        },
                        {
                            "request_type": "content_update_confirmation",
                            "error_type": "value_error",
                            "target": "summary",
                            "field": "table_values",
                            "response": "Yes, please apply the proposed update.",
                        },
                    ]
                },
            )

    def test_scope_slots_on_same_target_merge_table_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_gt(root, sample_gt_yaml())
            record = {
                "source_yaml": "split/test/s_1/gt/slide.yaml",
                "output_yaml": "split/test/s_1/injected/x/slide.yaml",
                "operations": [
                    {
                        "target": "st.caption",
                        "mutation_type": "scope_city_substitution",
                    },
                    {
                        "target": "st.caption",
                        "mutation_type": "scope_block_substitution",
                    },
                ],
            }

            episode = build_episode(root, record)

            self.assertEqual(
                [item["field"] for item in episode["feedback_items"]],
                ["city", "block"],
            )
            self.assertEqual(
                [item["scope_error_type"] for item in episode["feedback_items"]],
                ["unmatch", "unmatch"],
            )
            self.assertEqual(
                episode["feedback_items"][0]["response"],
                "Please use table=beijing_new_house, city=Beijing.",
            )
            self.assertEqual(
                episode["feedback_items"][1]["response"],
                "Please use block=Liangxiang.",
            )

    def test_title_topic_substitution_is_not_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_gt(root, sample_gt_yaml())
            record = {
                "source_yaml": "split/test/s_1/gt/slide.yaml",
                "output_yaml": "split/test/s_1/injected/x/slide.yaml",
                "operations": [
                    {
                        "target": "title",
                        "mutation_type": "title_topic_substitution",
                    }
                ],
            }

            episode = build_episode(root, record)

            self.assertIsNone(episode)

    def test_presentation_type_substitution_generates_presentation_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_gt(root, sample_gt_yaml())
            record = {
                "source_yaml": "split/test/s_1/gt/slide.yaml",
                "output_yaml": "split/test/s_1/injected/x/slide.yaml",
                "operations": [
                    {
                        "target": "st.caption",
                        "element_id": "3",
                        "mutation_type": "presentation_type_substitution",
                    }
                ],
            }

            episode = build_episode(root, record)

            self.assertEqual(
                episode["feedback_items"][0],
                {
                    "request_type": "content_update_confirmation",
                    "error_type": "claim_error",
                    "target": "st.caption",
                    "field": "presentation_type",
                    "response": "Yes, please apply the proposed update.",
                },
            )

    def test_generate_feedback_episodes_skips_unsupported_samples_and_deletes_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_dir = root / "manifest"
            manifest_dir.mkdir(parents=True)
            write_gt(root, sample_gt_yaml())
            records = [
                {
                    "split": "test",
                    "source_yaml": "split/test/s_1/gt/slide.yaml",
                    "output_yaml": "split/test/s_1/injected/a/slide.yaml",
                    "operations": [
                        {
                            "target": "summary",
                            "mutation_type": "numeric_value_perturbation",
                        }
                    ],
                },
                {
                    "split": "test",
                    "source_yaml": "split/test/s_1/gt/slide.yaml",
                    "output_yaml": "split/test/s_1/injected/b/slide.yaml",
                    "operations": [
                        {
                            "target": "st.body",
                            "mutation_type": "statistic_logic_mismatch",
                        }
                    ],
                },
            ]
            manifest_path = manifest_dir / "corruptions.jsonl"
            manifest_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in records) + "\n",
                encoding="utf-8",
            )
            injected_a_dir = root / "split" / "test" / "s_1" / "injected" / "a"
            injected_b_dir = root / "split" / "test" / "s_1" / "injected" / "b"
            injected_a_dir.mkdir(parents=True)
            injected_b_dir.mkdir(parents=True)
            stale_feedback_path = injected_b_dir / "feedback_episode.json"
            stale_feedback_path.write_text('{"stale": true}\n', encoding="utf-8")

            summary = generate_feedback_episodes(root, workers=2)

            self.assertEqual(
                summary,
                {"generated": 1, "skipped": 1, "by_split": {"test": 1}},
            )
            feedback_path = injected_a_dir / "feedback_episode.json"
            self.assertTrue(feedback_path.exists())
            episode = json.loads(feedback_path.read_text(encoding="utf-8"))
            self.assertEqual(
                episode,
                {
                    "feedback_items": [
                        {
                            "request_type": "content_update_confirmation",
                            "error_type": "value_error",
                            "target": "summary",
                            "field": "table_values",
                            "response": "Yes, please apply the proposed update.",
                        }
                    ]
                },
            )
            for old_key in (
                "expected_action",
                "expected_request",
                "user_reply",
                "confirm",
            ):
                self.assertNotIn(old_key, episode)
            self.assertFalse(stale_feedback_path.exists())


if __name__ == "__main__":
    unittest.main()
