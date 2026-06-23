from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from benchmarking.feedback.generator import build_episode, generate_feedback_episodes


class FeedbackGeneratorTest(unittest.TestCase):
    def test_scope_feedback_uses_field_and_scope_error_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_gt(root)
            episode = build_episode(
                root,
                {
                    "source_yaml": "split/test/s_1/gt/slide.yaml",
                    "output_yaml": "split/test/s_1/injected/x/slide.yaml",
                    "operations": [
                        {
                            "target": "st.caption",
                            "source": "caption[0]",
                            "mutation_type": "scope_block_unmatch",
                        }
                    ],
                },
            )

            self.assertEqual(
                episode,
                {
                    "feedback_items": [
                        {
                            "request_type": "data_source_slot_clarification",
                            "error_type": "scope_error",
                            "field": "block",
                            "target": "st.caption",
                            "response": "Please use block=Liangxiang.",
                            "scope_error_type": "unmatch",
                        }
                    ]
                },
            )

    def test_scope_feedback_uses_caption_source_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_gt(root)
            gt_path = root / "split" / "test" / "s_1" / "gt" / "slide.yaml"
            gt = yaml.safe_load(gt_path.read_text(encoding="utf-8"))
            gt["slide_filters"].append(
                {
                    "connection": {"table": ["shenzhen_new_house"]},
                    "filters": {
                        "city": "Shenzhen",
                        "block": "Nanshan",
                        "start_date": "2020-01-01",
                        "end_date": "2024-12-31",
                    },
                }
            )
            gt_path.write_text(
                yaml.safe_dump(gt, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

            episode = build_episode(
                root,
                {
                    "source_yaml": "split/test/s_1/gt/slide.yaml",
                    "output_yaml": "split/test/s_1/injected/x/slide.yaml",
                    "operations": [
                        {
                            "target": "st.caption",
                            "source": "caption[1]",
                            "mutation_type": "scope_city_conflict",
                        }
                    ],
                },
            )

            self.assertEqual(
                episode,
                {
                    "feedback_items": [
                        {
                            "request_type": "data_source_slot_clarification",
                            "error_type": "scope_error",
                            "field": "city",
                            "target": "st.caption",
                            "response": "Please use table=shenzhen_new_house, city=Shenzhen.",
                            "scope_error_type": "conflict",
                        }
                    ]
                },
            )

    def test_content_feedback_uses_only_error_type_and_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_gt(root)
            episode = build_episode(
                root,
                {
                    "source_yaml": "split/test/s_1/gt/slide.yaml",
                    "output_yaml": "split/test/s_1/injected/x/slide.yaml",
                    "operations": [
                        {
                            "target": "summary",
                            "mutation_type": "value_summary_slot",
                        },
                        {
                            "target": "st.caption",
                            "mutation_type": "claim_caption_presentation",
                        },
                    ],
                },
            )

            self.assertEqual(
                episode,
                {
                    "feedback_items": [
                        {
                            "request_type": "content_update_confirmation",
                            "error_type": "value_error",
                            "target": "summary",
                            "response": "Yes, please apply the proposed update.",
                        },
                        {
                            "request_type": "content_update_confirmation",
                            "error_type": "claim_error",
                            "target": "st.caption",
                            "response": "Yes, please apply the proposed update.",
                        },
                    ]
                },
            )

    def test_unsupported_mutation_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_gt(root)
            episode = build_episode(
                root,
                {
                    "source_yaml": "split/test/s_1/gt/slide.yaml",
                    "output_yaml": "split/test/s_1/injected/x/slide.yaml",
                    "operations": [
                        {
                            "target": "title",
                            "mutation_type": "unsupported_mutation",
                        }
                    ],
                },
            )

            self.assertIsNone(episode)

    def test_generate_feedback_episodes_deletes_stale_unsupported_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_gt(root)
            manifest_dir = root / "manifest"
            manifest_dir.mkdir(parents=True)
            records = [
                {
                    "split": "test",
                    "source_yaml": "split/test/s_1/gt/slide.yaml",
                    "output_yaml": "split/test/s_1/injected/a/slide.yaml",
                    "operations": [
                        {
                            "target": "summary",
                            "mutation_type": "value_summary_slot",
                        }
                    ],
                },
                {
                    "split": "test",
                    "source_yaml": "split/test/s_1/gt/slide.yaml",
                    "output_yaml": "split/test/s_1/injected/b/slide.yaml",
                    "operations": [
                        {
                            "target": "title",
                            "mutation_type": "unsupported_mutation",
                        }
                    ],
                },
            ]
            (manifest_dir / "corruptions.jsonl").write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in records) + "\n",
                encoding="utf-8",
            )
            injected_a = root / "split" / "test" / "s_1" / "injected" / "a"
            injected_b = root / "split" / "test" / "s_1" / "injected" / "b"
            injected_a.mkdir(parents=True)
            injected_b.mkdir(parents=True)
            stale_feedback = injected_b / "feedback_episode.json"
            stale_feedback.write_text('{"stale": true}\n', encoding="utf-8")

            summary = generate_feedback_episodes(root, workers=2)

            self.assertEqual(summary, {"generated": 1, "skipped": 1, "by_split": {"test": 1}})
            self.assertTrue((injected_a / "feedback_episode.json").exists())
            self.assertFalse(stale_feedback.exists())


def _write_gt(root: Path) -> None:
    gt_path = root / "split" / "test" / "s_1" / "gt" / "slide.yaml"
    gt_path.parent.mkdir(parents=True)
    gt_path.write_text(
        yaml.safe_dump(
            {
                "slide_filters": [
                    {
                        "connection": {"table": ["beijing_new_house"]},
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
                        {"id": "2", "type": "textBox", "role": "body-text"},
                        {"id": "3", "type": "textBox", "role": "caption"},
                        {"id": "4", "type": "chart", "role": "chart-bar"},
                    ]
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
