#!/usr/bin/env bash
set -euo pipefail

env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  PYTHONPATH=. \
  uv run python scripts/generate_feedback_episodes.py \
    --benchmark-root output/benchmark/dataset_v2 \
    --workers 32
