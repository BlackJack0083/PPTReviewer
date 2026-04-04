# AGENT.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PPTReviewer is an automated PowerPoint report generation system for the real estate industry. It extracts transaction data from PostgreSQL, processes/analyzes it, and generates professional PPT reports with charts, tables, and intelligent conclusions.

## Common Commands

```bash
# Install dependencies (use uv - fast Python package manager)
uv sync

# Run interactive test tool (recommended)
uv run test_all_templates.py
```

## Architecture

```
PostgreSQL Database
    ↓
DatabaseManager (singleton - connection)
    ↓
RealEstateDAO (SQL
StatTransformer (data transformation execution)
    ↓: binning, aggregation, pivoting)
    ↓
RealEstateDataProvider (Facade - unified interface)
    ↓
ConclusionGenerator (auto-generate analysis conclusions)
    ↓
PresentationContext (data container)
    ↓
PPTGenerationEngine (generates PPT)
```

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `core/` | Business logic: database, DAO, data provider, transformers, schemas |
| `engine/` | PPT generation: ppt_engine, builder, slide_renderers |
| `config/` | Settings and YAML templates |
| `agent/` | PPT summary verification agent: LLM client, no-tool/with-tool/ReAct workflows, local tool adapter, orchestration pipeline |
| `common/` | Shared tool/function specs (e.g., function default args and allowed arg keys) |

### Key Files

- `core/database.py` - DatabaseManager singleton
- `core/dao.py` - RealEstateDAO for SQL queries
- `core/data_provider.py` - RealEstateDataProvider facade
- `core/transformers.py` - StatTransformer for data processing
- `core/conclusion_generator.py` - ConclusionGenerator
- `engine/ppt_engine.py` - PPTGenerationEngine
- `engine/builder.py` - SlideConfigBuilder
- `engine/slide_renderers.py` - Slide renderers
- `agent/pipeline.py` - `PPTSummaryJudgeAgent` unified entry (`no_tool` / `with_tool` / `with_tool_react`)
- `agent/client.py` - OpenAI-compatible vision chat client + retry handling
- `agent/react_agent.py` - LangChain ReAct graph, tool middleware, output parsing helpers
- `agent/tools_local.py` - Local tool layer for template routing, DB query vars, expected summary generation, template alias mapping
- `agent/workflows/no_tool_flow.py` - no-tool binary judge graph
- `agent/workflows/with_tool_flow.py` - extract-validate-plan-run-judge graph with tool evidence
- `common/function_specs.py` - Canonical `function_key` defaults and argument whitelist
- `config/templates/template_definitions.yaml` - Template definitions
- `config/templates/layouts.yaml` - Layout configurations
- `config/templates/styles.yaml` - Style configurations
- `config/templates/text_pattern.yaml` - Jinja2 text templates

### Agent Modes (Summary Verifier)

- `no_tool`: Visual-only check, directly outputs `{"has_issue": true|false}`.
- `with_tool`: Extract claim -> validate fields -> call local tools -> final judge with evidence.
- `with_tool_react`: LangChain ReAct agent calls tools iteratively, then returns structured `ReactJudgeOutput`.

### Agent Entry Points

- Single run entry: `agent/run_single.py`
- Batch/small eval: `scripts/run_small_eval.py`

## Database Schema

Required tables: `Beijing_new_house`, `Guangzhou_new_house`, `Guangzhou_resale_house`, `Shenzhen_new_house`, `Shenzhen_resale_house`

Fields: `dim_area`, `dim_price`, `supply_sets`, `trade_sets`, `city`, `block`, `date_code`, `project`

Configure connection in `.env` file.

## code-check

在 commit 之前，运行 pre-commit 检查

```bash
uvx pre-commit run --all_files
```

## 代码提交规范

**每次接收到我的需求后，你需要展开 plan，不断提出不清晰的问题，直至没有不清晰的地方才能开始编写代码。**

- **代码风格**：遵循 `PEP8` 规范，使用 `type hint` 进行类型标注，使用 `docstring` 进行文档编写。
- **单元测试**：编写单元测试，确保代码的正确性。
- **提交规范**：测试通过后，需要进行git commit，每次提交都应该有对应的 `commit message`，描述本次提交的主要内容。
- **分支要求**：每次修改均需要**另起一个分支**，分支命名规范遵循commitizen要求，并在完成测试、`pre-commit` 通过后，合并到 `main` 分支。
- **经验总结**：当代码运行失败的时候，你需要自主分析错误原因，并尝试解决。最后将解决方式写在 [PROGRESS.md](./PROGRESS.md) 内(可选)。

## 经验教训沉淀

每次遇到问题或完成重要改动后，要在 [PROGRESS.md](./PROGRESS.md) 中记录：
- 遇到了什么问题
- 如何解决的
- 以后如何避免
- **必须附上 git commit ID**

**同样的问题不要犯两次！**

## 第一性原理

请使用第一性原理思考。你不能总是假设我非常清楚自己想要什么和该怎么得到。请保持审慎，从原始需求和问题触发，如果动机和目标不清晰，停下来和我讨论。

## 方案规范

当需要你给出修改方案或重构方案时必须符合以下规范：

- 不允许给出兼容性或补丁性的方案
- 不允许过度设计，保持最短路径实现且不能违反第一性要求
- 不允许自行给出我提供的需求以外的方案，例如一些兜底和降级方案，这可能导致业务逻辑偏移问题
- 必须保证方案的逻辑正确，必须经过全链路的逻辑验证

## 可能遇到的问题及解决方法

- 网络一直无法连接: 关闭代理

