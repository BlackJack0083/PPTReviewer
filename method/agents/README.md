# Agent 目录说明

`method/agents` 按运行职责组织。某个工具如果只被一个 agent 调用，就放在该
agent 自己的目录里，避免形成难追踪的公共工具池。

## 子包

- `slide_parser/`
  - 入口：`SlideParserAgent`
  - 职责：抽取 PPTX 元素、标注可见角色、把 chart/table body 导出为 CSV，
    并生成 `ppt_representation`。
  - 局部工具：无。PPTX 抽取逻辑直接放在 `agent.py` 中，因为它不是
    LangChain tool，也只服务 parser。

- `slide_analysis/`
  - 入口：`SlideAnalysisAgent`
  - 职责：调用 LLM prompt 抽取 `summary.data_source`、
    `caption.data_source` 和每个表的 `calculation_logic`。
  - 局部工具：无。该阶段只调用配置好的 LLM client。

- `data_source_validation/`
  - 入口：`DataSourceValidationAgent`
  - 局部工具：`tools.py`
  - Agent 调用的 LangChain tool：`data_source_query_tool`
  - 职责：把可见 data-source 描述聚合成 `final_data_source`，用数据库工具
    验证 slots，并在需要时向共享 client 请求 scope 修正。

- `content_validation/`
  - 入口：`ContentValidationAgent`
  - 局部工具：`tools.py`
  - Agent/workflow 调用的确定性工具：`execute_table_state`、
    `compare_display_dataframes`、`modify_textbox`、`modify_chart`、
    `modify_table`、`write_content_artifacts`
  - 职责：基于验证后的 state 重新计算表格/图表数据，与可见 CSV 比较，
    在修复前请求 client 确认，并检查 summary claim。

- `client/`
  - 入口：`ClientAgent`
  - 职责：benchmark client simulator。它把 agent 的显式请求和
    `feedback_episode.json` 匹配，Returns精简确认或 state patch。

## 共享文件

- `types.py`：agent 之间共享的 workflow dataclass。
- `../prompts/`：可直接编辑的 prompt 文本。
- `../pipeline/slide_review_workflow.py`：只负责编排，不持有某个 agent 的专用工具。
