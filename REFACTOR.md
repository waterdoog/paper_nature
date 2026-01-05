# Refactor Notes

## Goals
- Simplify and remove unused/duplicate logic.
- Split the monolithic script into small modules (<= 200 lines each).
- Improve readability with focused, minimal comments and clear responsibilities.
- Preserve behavior and CLI interface.

## New Structure
```
crawler.py
crawler_app/
  __init__.py
  cli.py
  config.py
  crawl.py
  download_flow.py
  http_client.py
  models.py
  parser.py
  screening.py
  screening_flow.py
  storage.py
  utils.py
```

## Module Responsibilities
- `crawler.py`: CLI entrypoint that calls `crawler_app.cli.main`.
- `crawler_app/cli.py`: argument parsing, orchestration, summary generation.
- `crawler_app/config.py`: defaults and journal definitions.
- `crawler_app/models.py`: dataclasses for journals, articles, ESM resources, screening results.
- `crawler_app/http_client.py`: HTTP requests, robots cache, throttling, download progress.
- `crawler_app/utils.py`: small helpers (filename normalization, date parsing).
- `crawler_app/parser.py`: HTML parsing for listings and article pages.
- `crawler_app/screening.py`: HEAD/robots screening and GitHub zip URL resolution.
- `crawler_app/screening_flow.py`: screening stage (no downloads).
- `crawler_app/download_flow.py`: download stage + metadata creation.
- `crawler_app/storage.py`: filesystem layout, metadata IO, summary CSV.

## Before vs After (High Level)
- **Before**: Single `crawler.py` (~1000+ lines) mixed parsing, HTTP, download, and storage logic.
- **After**: Modular design with single-purpose files capped at 200 lines and clear interfaces.
- **Before**: Unused helper (`download_github_zip`) and repeated logic across sections.
- **After**: Removed unused code and centralized shared logic (screening, metadata, storage).
- **Before**: Hard to trace flow across screening vs download phases.
- **After**: Explicit two-phase flow (`screening_flow.py` then `download_flow.py`) with clear boundaries.

## Behavior Parity
- CLI flags, output structure, filtering rules, and logging remain the same.
- Summary CSV generation still reads from metadata and writes `output/summary.csv`.
