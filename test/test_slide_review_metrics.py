from __future__ import annotations

import unittest

from method.eval.detection import aggregate_metrics, evaluate_detection
from method.eval.evaluator import failure_metrics


class SlideReviewMetricsTest(unittest.TestCase):
    def test_detection_uses_scope_subtype_and_field(self) -> None:
        corruption = {
            "operations": [
                {
                    "error_types": ["scope_error"],
                    "scope_error_type": "missing",
                    "field": "block",
                },
                {
                    "error_types": ["claim_error"],
                    "target": "summary",
                },
            ]
        }
        detected = [
            {
                "error_type": "scope_error",
                "scope_error_type": "missing",
                "field": "block",
            },
            {"error_type": "claim_error", "target": "summary"},
        ]

        metrics = evaluate_detection(detected, corruption)

        self.assertTrue(metrics["error_category"]["exact_match"])
        self.assertTrue(metrics["specific_issue"]["exact_match"])
        self.assertEqual(metrics["error_category"]["f1"], 1.0)
        self.assertEqual(metrics["specific_issue"]["f1"], 1.0)
        self.assertEqual(
            metrics["error_category"]["gold"],
            [{"error_type": "claim_error"}, {"error_type": "scope_error"}],
        )
        self.assertEqual(
            metrics["specific_issue"]["gold"],
            [
                {"error_type": "claim_error", "target": "summary"},
                {
                    "error_type": "scope_error",
                    "scope_error_type": "missing",
                    "field": "block",
                },
            ],
        )

    def test_detection_exact_match_rejects_extra_issue(self) -> None:
        corruption = {
            "operations": [
                {
                    "error_types": ["value_error"],
                    "target": "st.body",
                }
            ]
        }
        detected = [
            {"error_type": "value_error", "target": "st.body"},
            {"error_type": "claim_error", "target": "summary"},
        ]

        metrics = evaluate_detection(detected, corruption)

        self.assertFalse(metrics["error_category"]["exact_match"])
        self.assertFalse(metrics["specific_issue"]["exact_match"])
        self.assertEqual(metrics["error_category"]["precision"], 0.5)
        self.assertEqual(metrics["error_category"]["recall"], 1.0)
        self.assertEqual(metrics["specific_issue"]["precision"], 0.5)
        self.assertEqual(metrics["specific_issue"]["recall"], 1.0)

    def test_detection_deduplicates_repeated_scope_labels(self) -> None:
        operation = {
            "error_types": ["scope_error"],
            "scope_error_type": "missing",
            "field": "block",
        }
        detected = [
            {
                "error_type": "scope_error",
                "scope_error_type": "missing",
                "field": "block",
            }
        ]

        metrics = evaluate_detection(
            detected,
            {"operations": [operation, operation]},
        )

        self.assertTrue(metrics["specific_issue"]["exact_match"])
        self.assertEqual(
            metrics["specific_issue"]["gold"],
            [
                {
                    "error_type": "scope_error",
                    "scope_error_type": "missing",
                    "field": "block",
                }
            ],
        )

    def test_aggregate_reports_three_primary_metrics(self) -> None:
        corruption = {
            "operations": [
                {
                    "mutation_type": "value_table_cell",
                    "element_id": "4",
                    "error_types": ["value_error"],
                    "target": "st.body",
                }
            ]
        }
        successful = failure_metrics(corruption)
        successful["detection"] = evaluate_detection(
            [{"error_type": "value_error", "target": "st.body"}],
            corruption,
        )
        successful["task_success"] = True
        for stage in (
            "parser",
            "data_source_extraction",
            "function_logic",
            "data_source_validation",
        ):
            successful["stages"][stage]["success"] = True
        successful["stages"]["content_repair"] = {
            "accuracy": 1.0,
            "success": True,
            "correct": 1,
            "total": 1,
        }
        failed = failure_metrics(corruption)

        aggregate = aggregate_metrics([successful, failed])

        self.assertEqual(aggregate["error_category_macro_f1"], 2 / 3)
        self.assertEqual(aggregate["specific_issue_macro_f1"], 2 / 3)
        self.assertEqual(aggregate["error_category_exact_match_rate"], 0.5)
        self.assertEqual(aggregate["specific_issue_exact_match_rate"], 0.5)
        self.assertEqual(aggregate["end_to_end_success_rate"], 0.5)
        self.assertEqual(aggregate["stage_success_rate"]["parser"], 0.5)
        self.assertEqual(aggregate["stage_success_rate"]["content_repair"], 0.5)

    def test_content_repair_counts_each_injected_operation(self) -> None:
        operation = {
            "mutation_type": "value_table_cell",
            "element_id": "4",
            "error_types": ["value_error"],
            "target": "st.body",
        }

        metrics = failure_metrics({"operations": [operation, operation]})

        self.assertEqual(metrics["stages"]["content_repair"]["total"], 2)


if __name__ == "__main__":
    unittest.main()
