# Feedback-Aware Agent Method

本文档定义 `benchmarking/goal.md` 对应的三阶段 agent 方法，以及当前仓库里的最小实现范围。

## 三阶段接口

### Phase 1

输入：

- injected `slide.pptx`
- injected `slide.png`

流程：

1. `SlideParserAgent` 复用 `method/slide_parser` 做 Phase 1.1 解析。
2. `StructureReasoningAgent` 把解析结果整理为 `title / summary / st.caption / st.body / st.header` 五类目标。
3. `VerificationAgent` 依据可见文本和 ST 锚点输出 `detected_issues`。

当前 `detected_issues` schema：

```json
{
  "targets": ["summary"],
  "error_types": ["scope_error"],
  "evidence": "summary references explicit scope cues: ...",
  "required_fields_guess": [
    "scope.city",
    "scope.block",
    "scope.start_year",
    "scope.end_year"
  ]
}
```

当前实现是 heuristic baseline，不预测 `mutation_type`。

### SlideAgent-inspired tool layer

我参考了 `baseline/SlideAgent` 中最有用的两段设计：

1. `sql_generator.process_slide_params`
   - 把 caption 与最近的 table/chart 配对
   - 从可见表/图中抽取 row headers、column headers
   - 形成后续 SQL/filter 推理所需的结构化参数
2. `tool_utils.execute_analysis1`
   - 把结构化 function logic quadruple 转成确定性聚合
   - 使用 `date_code / dim_area / dim_unit_price / trade_sets / supply_sets` 等真实数据字段

当前项目没有直接复用旧代码，因为旧实现依赖 LangGraph/LLM 生成 JSON、Excel 文件副作用和外部 CSV 路径；这些会把 benchmark agent 输入边界弄脏。现在新增的是 side-effect-free 工具层：

- `method/agents/query_tools.py`
  - `SlideAgentInspiredToolPlanner`
    - 从真实 injected `slide.pptx` 的可见 chart/table payload 推理 `query_intents`
    - 推理 `analysis_logic`，结构接近 SlideAgent 的 `fun_tool.quadruples`
  - `VisibleAggregationTool`
    - 不造数据，只对 PPTX 中真实可见值生成 `aggregation_profiles`
    - 给 verifier 提供 metric kind、source columns、agg func、trend、support values
  - `DatabaseAggregationTool`
    - 只提供未来 DB-backed 执行的 SQL skeleton
    - 当前 benchmark 运行不会伪造 DB 查询结果

`StructureReasoningAgent` 当前会额外输出：

```json
{
  "query_intents": [
    {
      "connection": {"table": ["beijing_new_house"]},
      "select_columns": ["date_code", "trade_sets", "supply_sets"],
      "filters": {"city": "Beijing", "start_year": 2020, "end_year": 2024},
      "source": "visible_slide"
    }
  ],
  "analysis_logic": [
    {
      "table_type": "field-constraint",
      "dimensions": ["month"],
      "metrics": [
        {
          "name": "trade_counts",
          "metric_kind": "transaction",
          "source_columns": ["trade_sets"],
          "agg_func": "sum"
        }
      ]
    }
  ],
  "aggregation_profiles": [
    {
      "source": "visible_pptx",
      "category_granularity": "month",
      "time_range": [2020, 2024]
    }
  ]
}
```

这层工具的用途是：

- 让 `VerificationAgent` 的 `st.header` / logic 检查有可解释的字段级依据，而不是只看文字。
- 为 Phase 3 真正 repair 时重新查询、重新聚合、重新生成 ST body 留出接口。
- 保持当前实验“不用 Mock 数据”：没有 DB 时只使用真实 PPTX 可见数据，不伪造数据库结果。

### Phase 2

输入：

- `detected_issues`
- evaluator-only `ClientSimulator`

流程：

1. `InteractionAgent` 为每个 issue 生成 request。
   - request 不能只包含字段名；它必须说明：
     - 发现了什么矛盾
     - 证据来自哪里
     - 为什么这类错误需要用户确认
     - 用户应该提供什么修复信息
     - 建议的结构化回答格式
2. `FeedbackMatcher` 仍按 `error_types + targets + required_fields` 对齐 `feedback_episode.json`。
3. `ClientSimulator` 返回 `state_patch`。
4. `InteractionAgent` 累积 `repair_state`。

典型 `st.header / logic_error` request：

```json
{
  "targets": ["st.header"],
  "error_types": ["logic_error"],
  "required_fields": ["logic.metrics"],
  "evidence": "summary ties value 1914 to 'transaction', but the visible ST value matches a different metric series.",
  "diagnosis": "The chart/table header appears to describe a metric or aggregation that does not match the visible data series...",
  "requested_user_action": "Please provide the corrected metric list. For each metric, include name, meaning, source_col, agg_func, and filter condition.",
  "suggested_response_schema": {
    "logic": {
      "metrics": [
        {
          "name": "<visible metric name>",
          "meaning": "<human-readable meaning>",
          "source_col": "<database column>",
          "agg_func": "<count|sum|mean|...>",
          "filter_condition": {}
        }
      ],
      "group_by": "<month|year|area_range|...>",
      "dimensions": []
    }
  }
}
```

这个 request schema 的目的是真实交互可回答，而不是只服务 benchmark 匹配器。

当前 `repair_state` schema：

```json
{
  "scope": {},
  "logic": {},
  "claim": {},
  "targets_to_repair": []
}
```

### Phase 3

当前只提供 `RepairExecutor` stub。

固定接口：

- 输入：`observed_slide`、`repair_state`、原始 `slide.pptx`
- 输出：repair plan stub，记录未来真正执行修正所需的状态、目标和依赖工具

未来完整实现需要：

1. 根据 `repair_state` 更新 scope / logic / claim。
2. 重新生成或更新 `st.caption`、`st.header`、`st.body`、`summary`、`title`。
3. 必要时更新 CSV、PPT 元素和渲染图。
4. 与 `expected_repair_yaml` 或 GT slide 对比计算 repair success。

## 当前代码入口

- `method/agents/`
  - `slide_parser_agent.py`
  - `structure_reasoning_agent.py`
  - `verification_agent.py`
  - `interaction_agent.py`
  - `repair_executor.py`
  - `pptx_visible_data_extractor.py`
  - `role_labelers.py`
- `method/pipeline/slide_review_workflow.py`
  - 串联 Phase 1 + Phase 2 + Phase 3 stub
- `benchmarking/evaluation/slide_review_evaluator.py`
  - `FeedbackMatcher`
  - `ClientSimulator`
  - `SlideReviewEvaluator`
- `scripts/run_slide_review_eval.py`
  - 对少量 injected cases 运行最小闭环

## 输入边界

Agent 运行时只看：

- `slide.pptx`
- `slide.png`

Gold 文件只给：

- `corruption.json`
  - Phase 1 evaluator
- `feedback_episode.json`
  - Phase 2 client simulator / evaluator

当前实现不读取：

- `slide.yaml`
- GT YAML
- `corruption.json`
- `feedback_episode.json`

作为 agent 本身输入。

## VerificationAgent 当前策略

当前 `VerificationAgent` 不再只做纯文本规则匹配，而是：

1. 复用 `method/slide_parser` 产出 `observed_slide`
2. 通过 `pptx_visible_data_extractor.py` 从 injected `slide.pptx` 提取可见 chart/table 数据
3. 基于真实可见 ST 数据做几类一致性检查：
   - caption 展示类型 vs 实际 chart/table 类型
   - caption / summary 年份范围 vs ST 时间范围
   - summary 数值 vs ST 可见数值与派生统计
   - summary 趋势词 vs ST 趋势方向
   - metric label vs 数值分布的语义一致性

这仍然是 baseline，不等于完整 research-grade verifier，但已经比最早的“无条件按文本撒点”更接近 `goal.md` 要求的 ST-first / consistency-check 路线。

## Current Runtime Path

当前默认运行路径使用：

- 真实 injected `slide.pptx`
- 真实 injected `slide.png`
- `HeuristicRoleLabeler`

这条路径不依赖真实 VLM / API / 数据库，但不再生成或使用 mock PNG。

如果后续需要接真实图片模型，可把 `SlideParserAgent` 的 `role_labeler` 替换为 `method.slide_parser.OpenAIRoleLabeler`，并从环境变量读取：

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_MODEL`
- `DASHSCOPE_BASE_URL`

## 已知限制

1. `VerificationAgent` 目前是 benchmark-aligned heuristic baseline，不是强检测器。
2. `HeuristicRoleLabeler` 主要利用 PPTX 文本和元素类型，不会深度理解 PNG 像素。
3. `st.header` 当前通过 ST body anchor 表达，还没有从 PPT 可见对象中单独拆 header element。
4. `RepairExecutor` 只定义接口，不执行真实 PPT 修正。
