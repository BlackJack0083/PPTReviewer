"""Evaluation helpers for slide review and feedback-aware repair planning."""

from .slide_review_evaluator import (
    ClientSimulator,
    FeedbackMatcher,
    SlideReviewEvaluator,
    evaluate_detection,
    evaluate_interaction,
)

__all__ = [
    "ClientSimulator",
    "FeedbackMatcher",
    "SlideReviewEvaluator",
    "evaluate_detection",
    "evaluate_interaction",
]
