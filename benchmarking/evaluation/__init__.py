"""Compatibility exports for method evaluation metrics."""

from method.eval.metrics import (
    SlideReviewEvaluator,
    aggregate_metrics,
    evaluate_detection,
)

__all__ = [
    "SlideReviewEvaluator",
    "aggregate_metrics",
    "evaluate_detection",
]
