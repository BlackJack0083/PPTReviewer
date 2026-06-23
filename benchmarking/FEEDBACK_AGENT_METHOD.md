# Feedback-Aware Agent Method

本文档记录当前 `method/` 主线实现。旧的 `VerificationAgent`、
`StructureReasoningAgent`、`InteractionAgent`、`RepairExecutor` 和
`method/slide_parser` 已移除，不再作为运行入口。

## 运行路径

输入：

- injected `slide.pptx`
- injected `slide.png`
- case-local `feedback_episode.json`，仅供 `ClientAgent` 使用

主流程：

1. `SlideParserAgent`
   - 位置：`method/agents/slide_parser/agent.py`
   - 输出：`observed_slide` 和 `ppt_representation`
   - 职责：抽 PPTX 元素、用 PNG 辅助 role 标注、导出 chart/table body CSV。

2. `SlideAnalysisAgent`
   - 位置：`method/agents/slide_analysis/agent.py`
   - Prompt：`method/prompts/summary_data_source_extraction_prompt.txt`
   - Prompt：`method/prompts/caption_data_source_extraction_prompt.txt`
   - Prompt：`method/prompts/function_logic_extraction_prompt.txt`
   - 输出：`analysis_state`
   - 职责：从 summary/caption 抽 data source，从 visible table data 抽
     calculation logic。不验证对错。

3. `DataSourceValidationAgent`
   - 位置：`method/agents/data_source_validation/agent.py`
   - 工具：`method/agents/data_source_validation/tools.py`
   - LangChain tool：`slot_query`
   - 职责：聚合 `summary.data_source` 和 `caption.data_source`，维护
     `final_data_source`，调用数据库工具验证 scope slots，并在 Missing /
     Error / Unmatch / conflict 时向 `ClientAgent` 请求修正。

4. `ContentValidationAgent`
   - 位置：`method/agents/content_validation/agent.py`
   - 工具：`method/agents/content_validation/tools.py`
   - Prompt：`method/prompts/content_validation_react_prompt.txt`
   - 职责：用 `final_data_source`、每个 caption 的 `select_columns` 和
     `calculation_logic` 重新计算表格；与 PPT 可见 CSV 比较；经 client
     确认后记录 `modify_chart`、`modify_table` 或 `modify_textbox` 更新；
     再检查 summary claim。

5. `SlideReviewWorkflow`
   - 位置：`method/pipeline/slide_review_workflow.py`
   - 职责：只负责串联 agent，不拥有 agent-specific tools。

## Agent 目录组织

`method/agents/README.md` 维护目录地图。当前规则是：

- agent-specific tools 放在对应 agent package 的 `tools.py`。
- 只有跨 agent 共享的类型放在 `method/agents/types.py`。
- prompt 全部放在 `method/prompts/`，方便直接修改。
- workflow 不直接实现验证逻辑，只调用 agent。

## Client 反馈

`ClientAgent` 位置：`method/agents/client/agent.py`。

它只响应显式 request：

- `data_source_slot_clarification`
  - 返回客户式 `response`。
  - 用于澄清或修正 scope slots。
- `content_update_confirmation`
  - 返回客户式 `response`。
  - 用于确认 table/chart data、caption text、summary text 更新。

`ClientAgent` 不主动修复，也不读取 agent 不该看到的 gold state。它只根据
case-local `feedback_episode.json` 匹配 agent request。

## 输出

`SlideReviewWorkflow.arun(...)` 返回 `SlideReviewResult`：

- `observed_slide`
- `ppt_representation`
- `analysis_state`
- `data_source_validation_log`
- `content_validation_log`
- `detected_issues`
- `table_records`
- `repaired_artifacts`

`repaired_artifacts` 包含 repaired PPTX、semantic YAML 和确认更新后的 CSV。
PPTX 会按 parser `element_id` 写回文本框、chart 数据和 table 单元格。

## 运行边界

Agent 本身只看：

- `slide.pptx`
- `slide.png`
- LLM/API 返回
- 数据库查询工具返回
- `ClientAgent.respond(...)` 的交互结果

Agent 不读取：

- GT `slide.yaml`
- `corruption.json`
- `feedback_episode.json`

这些 gold/feedback 文件只属于 benchmark evaluator 或 client simulator。
