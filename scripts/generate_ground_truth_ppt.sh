env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy
PYTHONPATH=.

uv run scripts/ground_truth_generation.py \
  --dataset-root output/benchmark/dataset_v2 \
  --split test \
  --cities beijing guangzhou shenzhen \
  --start-year 2020 \
  --end-year 2024
