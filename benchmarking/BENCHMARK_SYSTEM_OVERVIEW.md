# PPT Feedback Repair Benchmark System Overview

本文档汇总当前 benchmark 系统状态，覆盖数据集组织、受控错误注入、feedback 监督、评价目标和后续方法讨论边界。

## 1. 总体目标

本 benchmark 面向 **用户反馈驱动的数据型 PPT 修正任务**。我们希望评估 agent 是否能完成一个串联流程：

1. 解析 PPT，发现元素级不一致。
2. 与用户交互，询问或确认真正需要补充的信息。
3. 根据用户反馈更新内部 repair state。
4. 重新检索、聚合、生成文本，并执行 PPT 修正。

当前主要评价拆成两类：

- **Detection success**：是否检测到错误，并定位到正确 target 与错误类型。
- **Repair success**：是否根据 GT 和用户反馈修回正确 PPT。

Interaction 是连接 detection 和 repair 的关键中间过程。当前用 `feedback_episode.json` 给出结构化监督，后续 evaluator 可以据此判断 agent 是否问到点上。

## 2. 页面语义拓扑

当前页面元素 target 固定为：

```text
st.caption
st.header
st.body
summary
title
```

其中：

- `st.caption`：ST 图表/表格的说明文字，通常包含 scope 和 presentation type。
- `st.header`：图表 series label 或表格 metric label，承载指标语义。
- `st.body`：图表/表格实际展示数据。
- `summary`：自然语言结论。
- `title`：页面主题。

核心拓扑：

```text
scope + logic -> st.body -> summary
title governs / summarizes st + summary
```

我们目前采用 ST-first 的检验思路：

- ST block 是主要可执行锚点。
- summary 作为自然语言 claim 被核验，不要求它独立恢复完整 logic。
- title 中的 topic 会影响底层表域/查询入口，因此作为 scope 的一部分被核验。

## 3. 数据集结构

每个 GT 样本：

```text
split/<split>/s_<sample_id>/gt/
  slide.yaml
  slide.pptx
  slide.png
  data/...
```

每个 injected case：

```text
split/<split>/s_<sample_id>/injected/<artifact_id>/
  slide.yaml
  slide.pptx
  slide.png
  corruption.json
  feedback_episode.json
  data/...
```

manifest：

```text
manifest/samples.jsonl
manifest/corruptions.jsonl
manifest/corruption_coverage.json
manifest/corruption_coverage_detailed.json
manifest/corruption_validation.json
```

当前已废弃：

```text
manifest/injections.jsonl
dataset-level feedback/episodes.jsonl
root-level feedback/
```

## 4. 生成链路

### 4.1 GT 生成

入口：

```text
scripts/ground_truth_generation.py
scripts/generate_ground_truth_ppt.sh
```

职责：

- 生成 GT `slide.yaml / slide.pptx / slide.png / data/*.csv`。
- 维护 `manifest/samples.jsonl`。

### 4.2 受控错误注入

入口：

```bash
bash scripts/generate_fine_grained_corruptions.sh
```

核心实现：

```text
benchmarking/fine_grained/runner.py
benchmarking/fine_grained/mutations.py
benchmarking/fine_grained/common.py
benchmarking/fine_grained/validator.py
```

职责：

- 读取 GT 样本。
- 按 family 生成 injected case。
- 写入 case-local `corruption.json`。
- 追加 `manifest/corruptions.jsonl`。

注意：错误注入脚本默认是 **追加写入**，重新生成干净数据集前需要先清理旧 `injected/` 与 corruption manifest。

### 4.3 Feedback 生成

入口：

```bash
bash scripts/generate_feedback_benchmark.sh
```

核心实现：

```text
benchmarking/feedback/generator.py
```

职责：

- 读取 `manifest/corruptions.jsonl`。
- 读取对应 GT `slide.yaml` 和必要 CSV。
- 为每个 injected case 写 `feedback_episode.json`。

## 5. Family 与 Mutation Type

`family` 是采样桶，表示错误注入落在哪个元素或元素组合上。CLI 中仍使用：

```text
st_caption
st_body
summary
title
st_header
st_summary
summary_title
three_element
```

`mutation_type` 是具体注入操作，当前公开命名为：

| mutation_type | error_types | 典型 target |
|---|---|---|
| `scope_time_range_shift` | `scope_error` | single-column `st.caption`, `summary` |
| `scope_city_substitution` | `scope_error` | single-column `st.caption`, `summary` |
| `scope_block_substitution` | `scope_error` | single-column `st.caption`, `summary` |
| `title_topic_substitution` | `scope_error` | `title` |
| `chart_metric_label_swap` | `logic_error` | `st.header` |
| `table_metric_label_swap` | `logic_error` | `st.header` |
| `numeric_value_perturbation` | `value_error` | `st.body`, `summary` |
| `range_value_shift` | `value_error` | `summary` |
| `trend_direction_flip` | `claim_error` | `summary` |
| `presentation_type_substitution` | `claim_error` | `st.caption` |

当前暂不加入 `agg_func_swap`。原因是它需要重算 CSV，且 detection 阶段必须反推聚合函数，评测链路复杂度较高。

## 6. Corruption Schema

case-local `corruption.json` 回答“错了什么”：

```json
{
  "error_types": ["scope_error", "value_error"],
  "affected_targets": ["summary"],
  "operations": [
    {
      "target": "summary",
      "element_id": "2",
      "role": "body-text",
      "mutation_type": "scope_time_range_shift",
      "error_types": ["scope_error"]
    },
    {
      "target": "summary",
      "element_id": "2",
      "role": "body-text",
      "mutation_type": "numeric_value_perturbation",
      "error_types": ["value_error"]
    }
  ],
  "expected_repair_yaml": "split/train/s_xxx/gt/slide.yaml"
}
```

原则：

- `error_types` 是所有 operation-level `error_types` 的并集。
- `affected_targets` 是所有 operation `target` 的去重集合。
- `semantic_slot` 不再写入公开标注。
- feedback 信息不写入 `corruption.json`。

## 7. Feedback Schema

case-local `feedback_episode.json` 回答“如果 agent 问到点上，用户应补充什么”：

```json
{
  "feedback_items": [
    {
      "error_types": ["scope_error"],
      "targets": ["summary"],
      "required_fields": ["scope.start_year", "scope.end_year"],
      "state_patch": {
        "scope": {
          "start_year": 2020,
          "end_year": 2024
        }
      }
    },
    {
      "error_types": ["value_error"],
      "targets": ["summary"],
      "required_fields": []
    }
  ]
}
```

不再使用旧字段：

```text
expected_action
expected_request
user_reply
confirm
text
repair_plan
source_operations
item_id
turns
grading_spec
```

`required_fields=[]` 表示该错误需要 agent 检出并说明，但用户不需要补充新的 state 字段。

## 8. 数据静态化

GT 和 injected 的 chart/table 展示数据都统一为外置 CSV：

```yaml
data: ./data/element_4.csv
```

不再使用 `mutated_data`。

这样做的原因：

- GT 与 injected 的数据展示方式统一。
- chart/table 数据隔离在 case 目录内。
- PPT 重建只读取当前 YAML 指向的 CSV。
- 后续修复可以替换对应元素的 CSV。

## 9. Method 状态

当前正在建立新的 `method/` 体系，用于逐步替代旧毕设时期的 `agent/` 代码。

已实现：

- `method/slide_parser/`
  - 先用 `python-pptx` 提取可编辑元素。
  - 再把 element list 与 slide image 交给 VLM 标注 role。
  - 输出接近 `template_slide` 的 `observed_slide`。
- `method/utils/`
  - 独立复制需要的 client 与 JSON 工具，不再依赖旧 `agent/`。

Phase 1.1 当前约束：

- 不输出 confidence。
- 不保留 `other`。
- 不保存 chart/table data。
- 不做 role 兜底修正。
- 暂不生成 `args`。

## 10. 当前仍需讨论

- Phase 1 中如何从 observed slide 恢复最小可执行 scope/logic。
- summary/title 的核验方式：expected generation 还是 claim-level comparison。
- Interaction evaluator 如何判断问到点上、少问、多问、问偏。
- Phase 3 repair executor 的 state 输入输出协议。
- 如何证明 agent 确实使用了用户反馈完成修复。
