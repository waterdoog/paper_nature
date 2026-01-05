import argparse
from typing import Dict, List

from .config import DEFAULT_USER_AGENT, build_journals
from .crawl import crawl_journal
from .http_client import RobotsCache, ThrottledFetcher
from .storage import collect_existing_records, write_summary_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Nature journal crawler for 2023-2026 papers with GitHub code."
    )
    parser.add_argument("--n", type=int, required=True, help="Number of papers per category/journal.")
    parser.add_argument("--start-year", type=int, default=2023)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=400)
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--dry-run", action="store_true", help="Skip downloads; only collect metadata.")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return parser


def main() -> int:
    args = build_parser().parse_args()

    journals = build_journals()
    robots = RobotsCache(args.user_agent)
    fetcher = ThrottledFetcher(args.user_agent, args.delay, args.timeout, args.retries)

    total = 0
    existing_records = collect_existing_records(args.output_dir)
    merged_records: Dict[str, Dict[str, object]] = {}
    for record in existing_records:
        output = record.get("output", {})
        article_dir = output.get("article_dir")
        if article_dir:
            merged_records[article_dir] = record

    for journal in journals:
        print(f"[info] Crawling {journal.name} ({journal.category})...")
        records = crawl_journal(
            journal=journal,
            n_per_journal=args.n,
            start_year=args.start_year,
            end_year=args.end_year,
            max_pages=args.max_pages,
            base_dir=args.output_dir,
            fetcher=fetcher,
            robots=robots,
            dry_run=args.dry_run,
        )
        print(f"[info] Collected {len(records)} records for {journal.slug}.")
        total += len(records)
        for record in records:
            output = record.get("output", {})
            article_dir = output.get("article_dir")
            if article_dir:
                merged_records[article_dir] = record

    print(f"[done] Total collected: {total}")
    write_summary_csv(args.output_dir, list(merged_records.values()))
    return 0
