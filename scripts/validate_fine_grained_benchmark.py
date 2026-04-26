#!/usr/bin/env python3
# ruff: noqa: E402,I001
"""Command-line entrypoint for fine-grained benchmark validation."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarking.fine_grained.validator import main  # noqa: E402


if __name__ == "__main__":
    main()
