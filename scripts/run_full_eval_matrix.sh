#!/usr/bin/env bash
set -euo pipefail

# Full benchmark matrix runner.
# Safe by default:
# - unsets proxy env vars
# - stages editable files into /tmp sandbox
# - writes reports outside the dataset tree

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -z "${DASHSCOPE_API_KEY:-}" ]]; then
  echo "Missing DASHSCOPE_API_KEY" >&2
  exit 1
fi

if [[ -z "${DASHSCOPE_BASE_URL:-}" ]]; then
  echo "Missing DASHSCOPE_BASE_URL" >&2
  exit 1
fi

DATASET_ROOT="${DATASET_ROOT:-output/benchmark/dataset_20260407}"
SPLIT="${SPLIT:-test}"
GT_SAMPLES="${GT_SAMPLES:-999999}"
INJECTED_SAMPLES="${INJECTED_SAMPLES:-999999}"
WORKERS="${WORKERS:-10}"
CASE_RETRIES="${CASE_RETRIES:-2}"
SANDBOX_ROOT="${SANDBOX_ROOT:-/tmp/agent_model_matrix_full}"
OUTPUT_ROOT="${OUTPUT_ROOT:-output/eval_full}"

MODELS=("${MODELS[@]:-Qwen3.5-4B Qwen3.5-9B Qwen3.5-27B Qwen3.5-35B-A3B}")
MODES=("${MODES[@]:-no_tool with_tool with_tool_react}")

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

echo "Running full eval matrix"
echo "  dataset_root: ${DATASET_ROOT}"
echo "  split:        ${SPLIT}"
echo "  gt_samples:   ${GT_SAMPLES}"
echo "  inj_samples:  ${INJECTED_SAMPLES}"
echo "  workers:      ${WORKERS}"
echo "  sandbox_root: ${SANDBOX_ROOT}"
echo "  output_root:  ${OUTPUT_ROOT}"
echo "  models:       ${MODELS[*]}"
echo "  modes:        ${MODES[*]}"

PYTHONPATH=. .venv/bin/python scripts/run_model_matrix_smoke.py \
  --dataset-root "${DATASET_ROOT}" \
  --split "${SPLIT}" \
  --models "${MODELS[@]}" \
  --modes "${MODES[@]}" \
  --gt-samples "${GT_SAMPLES}" \
  --injected-samples "${INJECTED_SAMPLES}" \
  --workers "${WORKERS}" \
  --case-retries "${CASE_RETRIES}" \
  --sandbox-root "${SANDBOX_ROOT}" \
  --output-root "${OUTPUT_ROOT}"
