# CLAUDE.md

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

### Key Files

- `core/database.py` - DatabaseManager singleton
- `core/dao.py` - RealEstateDAO for SQL queries
- `core/data_provider.py` - RealEstateDataProvider facade
- `core/transformers.py` - StatTransformer for data processing
- `core/conclusion_generator.py` - ConclusionGenerator
- `engine/ppt_engine.py` - PPTGenerationEngine
- `engine/builder.py` - SlideConfigBuilder
- `engine/slide_renderers.py` - Slide renderers
- `config/templates/template_definitions.yaml` - Template definitions
- `config/templates/layouts.yaml` - Layout configurations
- `config/templates/styles.yaml` - Style configurations
- `config/templates/text_pattern.yaml` - Jinja2 text templates

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
- **分支要求**：每次修改均需要另起一个分支，分支命名规范，并在完成测试、`pre-commit` 通过后，合并到 `main` 分支。
- **经验总结**：当代码运行失败的时候，你需要自主分析错误原因，并尝试解决。最后将解决方式写在 [PROGRESS.md](./PROGRESS.md) 内(可选)。

## 经验教训沉淀

每次遇到问题或完成重要改动后，要在 [PROGRESS.md](./PROGRESS.md) 中记录：
- 遇到了什么问题
- 如何解决的
- 以后如何避免
- **必须附上 git commit ID**

**同样的问题不要犯两次！**