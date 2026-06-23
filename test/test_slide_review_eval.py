from __future__ import annotations

import unittest

from method.eval.slide_review_eval import _is_retryable_error
from method.pipeline import WorkflowStageError


class SlideReviewEvalTest(unittest.TestCase):
    def test_retryable_error_unwraps_workflow_stage_error(self) -> None:
        error = WorkflowStageError(
            stage="content_validation",
            partial_result={},
            original_error=TimeoutError("temporary timeout"),
        )

        self.assertTrue(_is_retryable_error(error))

    def test_non_retryable_workflow_stage_error_stays_non_retryable(self) -> None:
        error = WorkflowStageError(
            stage="content_validation",
            partial_result={},
            original_error=ValueError("bad state"),
        )

        self.assertFalse(_is_retryable_error(error))


if __name__ == "__main__":
    unittest.main()
