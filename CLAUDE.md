# CLAUDE.md

This file provides guidance to Claude Code (`claude.ai/code`) when working with code in this repository.

## Project Overview

PPTReviewer is an automated PowerPoint report generation system for the real estate industry. It extracts transaction data from PostgreSQL, processes and analyzes it, and generates professional PPT reports with charts, tables, and intelligent conclusions.

## Common Commands

```bash
# Install dependencies
uv sync

# Run the interactive template test tool
uv run test_all_templates.py
```

## Architecture

```text
PostgreSQL Database
    -> DatabaseManager (singleton connection manager)
    -> RealEstateDAO (SQL access layer)
    -> StatTransformer (binning, aggregation, pivoting)
    -> RealEstateDataProvider (facade over data access and processing)
    -> ConclusionGenerator (automatic narrative generation)
    -> PresentationContext (render input container)
    -> PPTGenerationEngine (PPT generation pipeline)
```

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `core/` | Business logic: database, DAO, data provider, transformers, schemas |
| `engine/` | PPT generation: `ppt_engine`, `builder`, `slide_renderers` |
| `config/` | Settings and YAML templates |

### Key Files

- `core/database.py` - `DatabaseManager` singleton
- `core/dao.py` - `RealEstateDAO` SQL layer
- `core/data_provider.py` - `RealEstateDataProvider` facade
- `core/transformers.py` - `StatTransformer` data processing
- `core/conclusion_generator.py` - `ConclusionGenerator`
- `engine/ppt_engine.py` - `PPTGenerationEngine`
- `engine/builder.py` - `SlideConfigBuilder`
- `engine/slide_renderers.py` - Slide renderers
- `config/templates/template_definitions.yaml` - Template definitions
- `config/templates/layouts.yaml` - Layout configurations
- `config/templates/styles.yaml` - Style configurations
- `config/templates/text_pattern.yaml` - Jinja2 text templates

## Database Schema

Required tables:

- `Beijing_new_house`
- `Guangzhou_new_house`
- `Guangzhou_resale_house`
- `Shenzhen_new_house`
- `Shenzhen_resale_house`

Core fields:

- `dim_area`
- `dim_price`
- `supply_sets`
- `trade_sets`
- `city`
- `block`
- `date_code`
- `project`

Configure the database connection in `.env`.

## Code Check

Run pre-commit checks before submitting changes:

```bash
uvx pre-commit run --all_files
```

## Working Notes

- Prefer small, focused changes over broad rewrites.
- Keep type hints and docstrings readable when touching Python code.
- Run the relevant test path after modifying rendering or template logic.
- Record notable project progress or follow-up work in [PROGRESS.md](./PROGRESS.md).

## Commit Notes

- Include the related `git commit` ID when documenting important checkpoints.
- Write clear commit messages that describe the actual change.
