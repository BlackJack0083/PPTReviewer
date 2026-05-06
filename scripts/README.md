# Scripts Overview

`scripts/` 放的是命令行入口和工作流脚本；真正的 benchmark 逻辑实现在 `benchmarking/`。

## Main Pipeline

- `ground_truth_generation.py`
  - 生成 GT 样本。
  - 产物写入 `split/<split>/s_<sample_id>/gt/`。
  - 维护 `manifest/samples.jsonl`。

- `fine_grained_error_injector.py`
  - 基于 GT 生成 fine-grained injected / corruption 样本。
  - 产物写入 `split/<split>/s_<sample_id>/injected/<artifact_id>/`。
  - 维护 `manifest/corruptions.jsonl`。

- `generate_feedback_episodes.py`
  - 基于 `manifest/corruptions.jsonl` 生成 feedback benchmark episode。
  - 产物写入 `feedback/episodes.jsonl`。

## Evaluation

- `run_small_eval.py`
  - 从 `samples.jsonl` 和 `corruptions.jsonl` 采样，运行小规模评测。

- `run_model_matrix_smoke.py`
  - 跑小规模 model x mode 冒烟实验。
  - 依赖 `run_small_eval.py` 的 case staging / eval helpers。

- `validate_fine_grained_benchmark.py`
  - 校验 `corruptions.jsonl`、样本路径和 coverage 报告。

## Utilities

- `pptx_to_png.py`
  - 批量或单文件将 PPTX 渲染为 PNG。

- `generate_ground_truth_ppt.sh`
  - 生成 `dataset_v2` GT 的便捷命令。
  - 主要用于手动运行时减少环境变量输入。

## Ownership Boundary

- `scripts/` 只做入口编排，不承载复杂 benchmark 规则。
- `benchmarking/fine_grained/` 负责 corruption schema、mutation、validator。
- `benchmarking/feedback/` 负责 feedback episode schema 和生成逻辑。
