from __future__ import annotations

import unittest

from method.eval.metrics import aggregate_metrics, evaluate_detection, failure_metrics


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

        self.assertTrue(metrics["error_type"]["exact_match"])
        self.assertTrue(metrics["issue"]["exact_match"])
        self.assertEqual(metrics["error_type"]["f1"], 1.0)
        self.assertEqual(metrics["issue"]["f1"], 1.0)
        self.assertEqual(
            metrics["error_type"]["gold"],
            [{"error_type": "claim_error"}, {"error_type": "scope_error"}],
        )
        self.assertEqual(
            metrics["issue"]["gold"],
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

        self.assertFalse(metrics["error_type"]["exact_match"])
        self.assertFalse(metrics["issue"]["exact_match"])
        self.assertEqual(metrics["error_type"]["precision"], 0.5)
        self.assertEqual(metrics["error_type"]["recall"], 1.0)
        self.assertEqual(metrics["issue"]["precision"], 0.5)
        self.assertEqual(metrics["issue"]["recall"], 1.0)

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

        self.assertEqual(aggregate["error_type_macro_f1"], 2 / 3)
        self.assertEqual(aggregate["issue_macro_f1"], 2 / 3)
        self.assertEqual(aggregate["error_type_exact_accuracy"], 0.5)
        self.assertEqual(aggregate["issue_exact_accuracy"], 0.5)
        self.assertEqual(aggregate["task_success_rate"], 0.5)
        self.assertEqual(aggregate["stage_accuracy"]["parser"], 0.5)
        self.assertEqual(aggregate["stage_accuracy"]["content_repair"], 0.5)

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
