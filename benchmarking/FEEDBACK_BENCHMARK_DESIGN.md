# Feedback Benchmark Design

本文档记录当前 feedback benchmark 的实现设计。旧版集中式 `feedback/episodes.jsonl`、多轮 `turns`、`expected_action/expected_request/user_reply/confirm` 等字段已经废弃。

## 1. 设计目标

feedback benchmark 不直接模拟开放聊天，而是给 evaluator 和 client simulator 提供结构化监督：

> 当 agent 检测到某类问题并向用户询问时，用户应补充哪些 state 字段？

它服务于三件事：

1. 判断 agent 是否问到了正确错误类型和 target。
2. 给 LLM client simulator 提供可转述的结构化 gold 信息。
3. 给 Phase 3 repair state 提供可应用的 state patch。

## 2. 数据组织

feedback 是 case-local 文件：

```text
split/<split>/s_<sample_id>/injected/<artifact_id>/
  slide.yaml
  slide.pptx
  slide.png
  corruption.json
  feedback_episode.json
  data/...
```

生成入口：

```bash
bash scripts/generate_feedback_benchmark.sh
```

等价底层命令：

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  PYTHONPATH=. \
  uv run python scripts/generate_feedback_episodes.py \
    --benchmark-root output/benchmark/dataset_v2 \
    --workers 32
```

输入：

- `manifest/corruptions.jsonl`
- 每条 corruption 的 GT `source_yaml`
- 必要时读取 GT chart/table CSV

输出：

- 每个 injected case 的 `feedback_episode.json`

## 3. Schema

当前 schema 只有一个顶层字段：

```json
{
  "feedback_items": [
    {
      "request_type": "data_source_slot_clarification",
      "table_index": 0,
      "error_types": ["scope_error"],
      "targets": ["summary"],
      "fields": ["time_range"],
      "state_patch": {
        "tables": [
          {
            "index": 0,
            "data_source": {
              "filters": {
                "start_date": "2020-01-01",
                "end_date": "2024-12-31"
              }
            }
          }
        ]
      }
    },
    {
      "request_type": "content_update_confirmation",
      "table_index": 0,
      "error_types": ["value_error"],
      "targets": ["summary"],
      "fields": ["table_values"],
      "decision": "accept"
    }
  ]
}
```

字段含义：

- `feedback_items`
  - 一个 case 中可被独立询问和命中的反馈监督项。
- `request_type`
  - agent 与 client 的交互类型，例如 `data_source_slot_clarification`、`calculation_logic_clarification`、`content_update_confirmation`。
- `table_index`
  - 对应 `analysis_state["tables"]` 中的表/图索引。
- `error_types`
  - 该 item 对应的错误大类。
- `targets`
  - 该 item 对应的 PPT target，目前每个 item 通常只有一个 target。
- `fields`
  - client 需要确认或补充的最小字段集合。
- `state_patch`
  - 命中该 item 后写回当前 `analysis_state` 的最小 patch；只包含错误点相关字段。
- `decision`
  - 用于内容更新确认，当前取值为 `accept` 或 `revise`。

当前明确不包含：

```text
episode_id
sample_ref
corruption_ref
split
turns
grading_spec
expected_action
expected_request
expected_response
user_reply
confirm
text
repair_plan
source_operations
item_id
```

这些信息要么由路径表达，要么属于 evaluator/client simulator 运行时逻辑，不应写入 gold feedback。

## 4. 生成规则

feedback generator 按 operation 生成初始 item，然后按 `(request_type, table_index, error_types, target)` 合并。

多标签 case 必须拆成多个 `feedback_items`。

例如一个 summary 同时有 scope 错和数值错：

```json
{
  "feedback_items": [
    {
      "request_type": "data_source_slot_clarification",
      "table_index": 0,
      "error_types": ["scope_error"],
      "targets": ["summary"],
      "fields": ["time_range"],
      "state_patch": {
        "tables": [
          {
            "index": 0,
            "data_source": {
              "filters": {
                "start_date": "2020-01-01",
                "end_date": "2024-12-31"
              }
            }
          }
        ]
      }
    },
    {
      "request_type": "content_update_confirmation",
      "table_index": 0,
      "error_types": ["value_error"],
      "targets": ["summary"],
      "fields": ["table_values"],
      "decision": "accept"
    }
  ]
}
```

真实交互判断方式：

- Agent 只问时间范围：命中 scope item。
- Agent 只指出 summary 数值错：命中 value item。
- Agent 两者都提到：命中两个 item。
- Agent 问 metric/source_col：问偏，不应返回 scope item 的 gold fields。

## 5. Mutation 到 Feedback 的映射

| mutation_type | request_type | fields | response |
|---|---|---|---|
| `scope_time_range_shift` | `data_source_slot_clarification` | `time_range` | patch `tables[i].data_source.filters.start_date/end_date` |
| `scope_city_substitution` | `data_source_slot_clarification` | `city` | patch `tables[i].data_source.connection.table` and `filters.city` |
| `scope_block_substitution` | `data_source_slot_clarification` | `block` | patch `tables[i].data_source.filters.block` |
| `chart_metric_label_swap` | `calculation_logic_clarification` | `metrics` | patch `tables[i].calculation_logic.metrics` |
| `table_metric_label_swap` | `calculation_logic_clarification` | `metrics` | patch `tables[i].calculation_logic.metrics` |
| `numeric_value_perturbation` | `content_update_confirmation` | `table_values` | `decision=accept` |
| `range_value_shift` | `content_update_confirmation` | `table_values` | `decision=accept` |
| `trend_direction_flip` | `content_update_confirmation` | `summary` | `decision=accept` |
| `presentation_type_substitution` | `content_update_confirmation` | `presentation_type` | `decision=accept` |

双栏图的 `st.caption` 不生成 scope 类 mutation；这类页面保留 `presentation_type_substitution`、logic/value 类错误，减少交互阶段对多 caption scope 绑定的歧义。

content update 类 item 不是让 client 提供修正文案或工具参数；它只表达“agent 用自然语言描述候选修正后，client 是否确认”。实际替换由 `ContentValidationAgent` 调用 `modify_textbox` / `modify_chart` / `modify_table` 形成 update log，workflow 最后自动导出 artifact。

## 6. Logic Feedback

当前 logic feedback 主要覆盖 `st.header` 错误：

- `chart_metric_label_swap`
- `table_metric_label_swap`

chart 情况下，`state_patch.tables[i].calculation_logic` 从 GT chart args 恢复：

```json
{
  "tables": [
    {
      "index": 0,
      "calculation_logic": {
        "metrics": [
          {
            "name": "Supply Count",
            "source_col": "supply_sets",
            "agg_func": "count",
            "filter_condition": {
              "supply_sets": 1
            }
          }
        ],
        "table_type": "field-constraint"
      }
    }
  ]
}
```

table 情况下同样写入 `tables[i].calculation_logic`。如果 GT table 元素已经静态化 `args`，优先使用该结构。

## 7. 与 Client Simulator 的关系

`feedback_episode.json` 不保存自然语言 `text`。`ClientAgent` 只在 agent 请求的 `request_type/table_index/fields/targets` 命中某个 item 时返回对应 patch 或 decision。

例如：

```json
{
  "request_type": "data_source_slot_clarification",
  "table_index": 0,
  "error_types": ["scope_error"],
  "targets": ["st.caption"],
  "fields": ["block"],
  "state_patch": {
    "tables": [
      {
        "index": 0,
        "data_source": {
          "filters": {
            "block": "Liangxiang"
          }
        }
      }
    ]
  }
}
```

可以转述为：

```text
这个页面应该分析 Liangxiang 这个 block。
```

自然语言只是包装层，gold 仍以结构化字段为准。

## 8. 当前实现优化

feedback 生成已经采用：

- manifest-driven cleanup，不全盘 glob 扫描。
- 多线程 cleanup 和写入。
- YAML/CSV cache。
- `tqdm` 进度条。

## 9. 后续待定

- Interaction evaluator 如何定义命中、少问、多问、问偏。
- 多轮交互是否需要引入。
- Client simulator 如何将结构化 `feedback_items` 转成自然语言。
- Repair evaluator 如何判断 agent 是否使用了用户反馈。
