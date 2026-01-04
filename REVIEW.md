# Nature Crawler Review

## What it does
- Crawls Nature Human Behaviour and Palgrave Communications research-articles pages.
- Filters for papers published between 2023 and 2026 (inclusive).
- Keeps only papers with GitHub code links (OSF-only code is excluded).
- Downloads PDF, GitHub code zip, supplementary files, and peer review files when available.
- Writes a per-article metadata.json with ESM link mapping and statuses.

## Implementation notes
- Uses the journal research-articles listing pages (sorted by publication date) and paginates until enough matches are collected.
- Parses each article page for:
  - Title, DOI, publication date (JSON-LD / meta tags).
  - Code availability (GitHub links from the section or page).
  - PDF URL (citation_pdf_url meta tag or "Download PDF" links).
  - ESM resources from page links, using link text for filenames.
- Logs download progress for file downloads.
- Respects robots.txt via urllib.robotparser and throttles requests with a configurable delay.
- Screening and downloading are split into two phases: the crawler only downloads files after it has confirmed all filter conditions.
- When robots.txt disallows a resource, it is marked for manual supplementation and skipped.

## Output structure
Paths are created under the working directory by default:
- `output/<category>/<article-slug>/pdf_papers/paper.pdf` : main article PDF
- `output/<category>/<article-slug>/supplementary_materials/` : supplementary + peer review files
- `output/<category>/<article-slug>/supplementary_materials/Peer_Review_File.pdf` : peer review file
- `output/<category>/<article-slug>/code/` : GitHub code zip
- `output/<category>/<article-slug>/data/` : data files
- `output/<category>/<article-slug>/metadata.json` : article metadata + ESM mapping
- `output/summary.csv` : papers with paper/review/code files present

## Usage
Install dependencies:
```bash
pip install -r requirements.txt
```

Run the crawler (N papers per journal):
```bash
python crawler.py --n 10
```

Optional flags:
- `--start-year` / `--end-year`
- `--delay` (seconds between requests)
- `--dry-run` (no downloads, metadata only)
- `--max-pages` (safety cap for pagination)

## Assumptions / limitations
- The script assigns `nathumbehav` to `social_sci` and `palcomms` to `natural_sci` to satisfy the two-category requirement. Adjust categories if needed.
- Articles without GitHub links or a peer review file are skipped.
- ESM resources are downloaded only when they are explicit links on the page.
