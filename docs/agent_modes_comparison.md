# Agent 三种模式对比（`no_tool` / `with_tool` / `with_tool_react`）

## 1. 总览

| 模式 | 是否调用业务工具 | LLM 调用次数（典型） | 是否依赖数据库 | 可解释性 |
|---|---|---:|---|---|
| `no_tool` | 否 | 1 次 | 否 | 低 |
| `with_tool` | 是（固定流程） | 2 次（提取 + 裁决） | 是 | 高（结构化证据稳定） |
| `with_tool_react` | 是（Agent 自主决策） | 不固定（多轮） | 是 | 中-高（看轨迹） |

## 2. 各模式执行流程

## `no_tool`
1. 输入 slide 图片。
2. 单次 LLM 直接判断：`{"has_issue": true|false}`。

特点：
- 最快、成本最低。
- 完全靠视觉+文本理解，容易受表述风格影响。

---

## `with_tool`（固定 workflow）
1. `extract_claim`：LLM 从图里抽取结构化字段（`template_id/table_name/city/block/year/summary_text`）。
2. 工具执行（固定顺序）：
   - `resolve_plan`
   - `query_conclusion_vars`
   - `build_expected_summary`
3. `judge_with_tool`：第二次 LLM 对比 `summary_text` 与工具证据，输出 `has_issue`。

特点：
- 可控性强，实验稳定性通常优于 `react`。
- 证据链清晰，便于误差分析。
- 依赖 claim 抽取准确性；抽错会影响后续。

---

## `with_tool_react`
1. ReAct Agent 收到图片和系统约束。
2. Agent 自主决定是否/何时调用工具（可多轮）。
3. 最终返回结构化输出（目标同样是 `has_issue`）。

特点：
- 灵活，适合复杂场景和探索式推理。
- 轨迹更长，耗时和 token 消耗通常更高。
- 稳定性受模型工具调用策略影响更大。

## 3. 输出结构差异（当前实现）

三种模式都返回统一外层：
- `has_issue`
- `mode`
- `claim`
- `evidence`
- `tool_calls`
- `final`
- `debug`

但信息完整度不同：
- `no_tool`：
  - `claim/evidence/tool_calls` 通常为空。
  - `final.text` 是单次判定原文。
- `with_tool`：
  - `claim` 来自第一轮抽取。
  - `evidence` 来自工具计算结果（最稳定）。
  - `tool_calls` 是固定计划列表（3 个）。
- `with_tool_react`：
  - `claim/evidence` 来自 ReAct 轨迹反提取（best effort）。
  - `tool_calls` 是实际调用到的工具名序列。

## 4. 你在实验里怎么选

建议优先级（默认）：
1. 离线评测、要稳定可复现：`with_tool`
2. 快速 baseline：`no_tool`
3. 想观察 Agent 自主工具策略：`with_tool_react`

## 5. 常见误区

- `with_tool` 不是“只调用一次 LLM”，而是两次（抽取 + 最终裁决）。
- `with_tool_react` 不保证固定调用 3 个工具；它是“可能多轮、按需调用”。
- 指标对比时要同时看 `error_cases`，不能只看 `accuracy/f1`。
