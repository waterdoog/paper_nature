# Nature Paper Crawler

## Overview
This project crawls Nature Human Behaviour (social_sci) and Palgrave Communications (natural_sci) research-articles pages to collect
papers published between 2023–2026 that have GitHub code links and peer review files. It follows a screening-first
workflow, respects robots.txt, and organizes outputs under `output/`.

## What it does
- Crawls Nature Human Behaviour and Palgrave Communications research-articles pages
- Filters for papers published between 2023 and 2026 (inclusive)
- Keeps only papers with GitHub code links (OSF-only code is excluded)
- Downloads PDF, GitHub code zip, supplementary files, and peer review files when available
- Writes a per-article metadata.json with ESM link mapping and statuses

## Implementation Notes
- Uses the journal research-articles listing pages (sorted by publication date) and paginates until enough matches are collected
- Parses each article page for:
  - Title, DOI, publication date (JSON-LD / meta tags)
  - Code availability (GitHub links from the section or page)
  - PDF URL (citation_pdf_url meta tag or "Download PDF" links)
  - ESM resources from page links, using link text for filenames
- Logs download progress for file downloads
- Respects robots.txt via urllib.robotparser and throttles requests with a configurable delay
- Screening and downloading are split into two phases: the crawler only downloads files after it has confirmed all filter conditions
- When robots.txt disallows a resource, it is marked for manual supplementation and skipped
- Source code is modularized under `crawler_app/` with `crawler.py` as the entrypoint

## Requirements
- Python 3.9+
- Dependencies:
  - `beautifulsoup4`

Install:
```bash
pip install -r requirements.txt
```

## Run
```bash
python crawler.py --n 10
```

Common options:
- `--start-year` / `--end-year`
- `--delay` (seconds between requests)
- `--timeout` / `--retries`
- `--max-pages` (safety cap for pagination)
- `--dry-run` (no downloads, metadata only)
- `--output-dir`

## Output Layout
```
output/
  <category>/
    <article-slug>/
      pdf_papers/paper.pdf : main article PDF
      supplementary_materials/ : supplementary + peer review files
      supplementary_materials/Peer_Review_File.pdf : peer review file
      code/ : GitHub code zip
      data/ : data files
      metadata.json : article metadata + ESM mapping
  summary.csv : papers with paper/review/code files present
```

## Workflow Notes
- Screening happens before downloads. Only screened candidates are downloaded.
- If robots.txt blocks a resource, it is marked for manual supplementation.
- `summary.csv` is generated from existing `metadata.json` files.

## Project Structure
```
crawler.py (CLI entrypoint)
crawler_app/
  __init__.py
  cli.py : argument parsing, orchestration, summary generation
  config.py : defaults and journal definitions
  models.py : dataclasses for journals, articles, ESM resources, screening results
  http_client.py : HTTP requests, robots cache, throttling, download progress
  utils.py : small helpers (filename normalization, date parsing)
  parser.py : HTML parsing for listings and article pages
  screening.py : HEAD/robots screening and GitHub zip URL resolution
  screening_flow.py : screening stage (no downloads)
  download_flow.py : download stage + metadata creation
  storage.py : filesystem layout, metadata IO, summary CSV
```

## Assumptions / Limitations
- The script assigns `nathumbehav` to `social_sci` and `palcomms` to `natural_sci` to satisfy the two-category requirement. Adjust categories if needed.
- Articles without GitHub links or a peer review file are skipped.
- ESM resources are downloaded only when they are explicit links on the page.
