from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from benchmarking.feedback.generator import (
    build_episode,
    derive_expected_action,
    generate_feedback_episodes,
)


def sample_gt_yaml() -> dict:
    return {
        "meta": {"template_id": "T01_Supply_Trans_Bar"},
        "query_filters": {
            "city": "Beijing",
            "block": "Liangxiang",
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
                    "text": "Block Area Segment Distribution",
                }
            ]
        },
    }


class FeedbackGeneratorTest(unittest.TestCase):
    def test_derive_expected_action_prefers_scope_over_confirm(self) -> None:
        operations = [
            {"mutation_type": "caption_chart_type_mismatch", "target": "st.caption"},
            {"mutation_type": "caption_scope_city", "target": "st.caption"},
        ]

        action = derive_expected_action(operations)

        self.assertEqual(action, "scope_correction")

    def test_build_episode_logic_for_metric_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gt_yaml_path = root / "split" / "test" / "s_1" / "gt" / "slide.yaml"
            gt_yaml_path.parent.mkdir(parents=True)
            gt_yaml_path.write_text(
                yaml.safe_dump(sample_gt_yaml(), sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            record = {
                "source_yaml": "split/test/s_1/gt/slide.yaml",
                "output_yaml": "split/test/s_1/injected/x/slide.yaml",
                "corruption_json": "split/test/s_1/injected/x/corruption.json",
                "operations": [
                    {
                        "target": "st.header",
                        "mutation_type": "series_metric_swap",
                    }
                ],
            }

            episode = build_episode(root, record, "ep_000001")

            self.assertIsNotNone(episode)
            if episode is None:
                self.fail("Expected logic episode")
            turn = episode["turns"][0]
            self.assertEqual(turn["expected_action"], "logic_correction")
            self.assertEqual(turn["action_payload"]["required_fields"], ["metrics", "group_by"])
            self.assertEqual(
                turn["user_reply"],
                {
                    "metrics": [
                        {
                            "name": "Supply Count",
                            "meaning": "供应套数",
                            "agg_func": "count",
                        },
                        {
                            "name": "Sales Count",
                            "meaning": "成交套数",
                            "agg_func": "count",
                        },
                    ],
                    "group_by": "area_range",
                },
            )

    def test_build_episode_scope_reply_uses_gt_query_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gt_yaml_path = root / "split" / "test" / "s_1" / "gt" / "slide.yaml"
            gt_yaml_path.parent.mkdir(parents=True)
            gt_yaml_path.write_text(
                yaml.safe_dump(sample_gt_yaml(), sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            record = {
                "source_yaml": "split/test/s_1/gt/slide.yaml",
                "output_yaml": "split/test/s_1/injected/x/slide.yaml",
                "corruption_json": "split/test/s_1/injected/x/corruption.json",
                "operations": [
                    {
                        "target": "summary",
                        "mutation_type": "summary_scope_year",
                    },
                    {
                        "target": "summary",
                        "mutation_type": "numeric_delta",
                    },
                ],
            }

            episode = build_episode(root, record, "ep_000002")

            self.assertIsNotNone(episode)
            if episode is None:
                self.fail("Expected scope episode")
            turn = episode["turns"][0]
            self.assertEqual(turn["expected_action"], "scope_correction")
            self.assertEqual(
                turn["action_payload"]["required_fields"],
                ["start_year", "end_year"],
            )
            self.assertEqual(
                turn["user_reply"],
                {"start_year": 2020, "end_year": 2024},
            )

    def test_build_episode_page_intent_for_three_element(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gt_yaml_path = root / "split" / "test" / "s_1" / "gt" / "slide.yaml"
            gt_yaml_path.parent.mkdir(parents=True)
            gt_yaml_path.write_text(
                yaml.safe_dump(sample_gt_yaml(), sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            record = {
                "source_yaml": "split/test/s_1/gt/slide.yaml",
                "output_yaml": "split/test/s_1/injected/x/slide.yaml",
                "corruption_json": "split/test/s_1/injected/x/corruption.json",
                "operations": [
                    {"target": "st.body", "mutation_type": "data_numeric_delta"},
                    {"target": "summary", "mutation_type": "linked_numeric_delta"},
                    {"target": "title", "mutation_type": "title_theme_drift"},
                ],
            }

            episode = build_episode(root, record, "ep_000003")

            self.assertIsNotNone(episode)
            if episode is None:
                self.fail("Expected page intent episode")
            turn = episode["turns"][0]
            self.assertEqual(turn["expected_action"], "page_intent_correction")
            self.assertEqual(turn["action_payload"]["required_fields"], ["scope", "topic"])
            self.assertEqual(
                turn["user_reply"],
                {
                    "page_intent": {
                        "scope": {
                            "city": "Beijing",
                            "block": "Liangxiang",
                            "start_year": 2020,
                            "end_year": 2024,
                        },
                        "topic": "Block Area Segment Distribution",
                    }
                },
            )

    def test_generate_feedback_episodes_skips_unsupported_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_dir = root / "manifest"
            manifest_dir.mkdir(parents=True)
            gt_yaml_path = root / "split" / "test" / "s_1" / "gt" / "slide.yaml"
            gt_yaml_path.parent.mkdir(parents=True)
            gt_yaml_path.write_text(
                yaml.safe_dump(sample_gt_yaml(), sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            records = [
                {
                    "source_yaml": "split/test/s_1/gt/slide.yaml",
                    "output_yaml": "split/test/s_1/injected/a/slide.yaml",
                    "corruption_json": "split/test/s_1/injected/a/corruption.json",
                    "operations": [
                        {
                            "target": "summary",
                            "mutation_type": "numeric_delta",
                        }
                    ],
                },
                {
                    "source_yaml": "split/test/s_1/gt/slide.yaml",
                    "output_yaml": "split/test/s_1/injected/b/slide.yaml",
                    "corruption_json": "split/test/s_1/injected/b/corruption.json",
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
            output_path = root / "feedback" / "episodes.jsonl"

            summary = generate_feedback_episodes(root, output_path)

            self.assertEqual(summary, {"generated": 1, "skipped": 1})
            lines = output_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            episode = json.loads(lines[0])
            turn = episode["turns"][0]
            self.assertEqual(turn["expected_action"], "confirm")


if __name__ == "__main__":
    unittest.main()
