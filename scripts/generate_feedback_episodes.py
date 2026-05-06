#!/usr/bin/env python3
"""Command-line entrypoint for feedback episode generation."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarking.feedback import generate_feedback_episodes, parse_args  # noqa: E402


def main() -> None:
    """Run feedback episode generation from CLI args."""
    args = parse_args()
    summary = generate_feedback_episodes(
        benchmark_root=args.benchmark_root,
        output_path=args.output,
    )
    print(
        f"Generated {summary['generated']} feedback episodes; "
        f"skipped {summary['skipped']} unsupported samples"
    )


if __name__ == "__main__":
    main()
