"""Evaluation helpers for slide review and feedback-aware repair planning."""

from .slide_review_evaluator import (
    SlideReviewEvaluator,
    evaluate_detection,
)

__all__ = [
    "SlideReviewEvaluator",
    "evaluate_detection",
]
