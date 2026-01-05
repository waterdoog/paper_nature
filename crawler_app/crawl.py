import os
from typing import Dict, List

from .download_flow import download_candidates
from .http_client import RobotsCache, ThrottledFetcher
from .models import JournalConfig
from .screening_flow import screen_journal
from .storage import list_existing_article_dirs, load_metadata_for_dir, load_url_cache, save_url_cache


def crawl_journal(
    journal: JournalConfig,
    n_per_journal: int,
    start_year: int,
    end_year: int,
    max_pages: int,
    base_dir: str,
    fetcher: ThrottledFetcher,
    robots: RobotsCache,
    dry_run: bool = False,
) -> List[Dict[str, object]]:
    """Full crawl for a single journal with a screening-first flow."""
    collected: List[Dict[str, object]] = []
    os.makedirs(base_dir, exist_ok=True)
    category_dir = os.path.join(base_dir, journal.category)
    os.makedirs(category_dir, exist_ok=True)

    existing_dirs = list_existing_article_dirs(category_dir)
    existing_records = [load_metadata_for_dir(path) for path in existing_dirs]
    existing_slugs = {os.path.basename(path) for path in existing_dirs}
    if existing_records:
        collected.extend(existing_records[:n_per_journal])
    if len(collected) >= n_per_journal:
        print(
            f"[info] Using {len(collected)} existing articles for {journal.slug}; skipping crawl."
        )
        return collected

    remaining = n_per_journal - len(collected)
    url_cache = load_url_cache(base_dir, journal.slug)
    candidates = screen_journal(
        journal=journal,
        remaining=remaining,
        start_year=start_year,
        end_year=end_year,
        max_pages=max_pages,
        fetcher=fetcher,
        robots=robots,
        existing_slugs=existing_slugs,
        url_cache=url_cache,
    )
    save_url_cache(base_dir, journal.slug, url_cache)
    collected.extend(
        download_candidates(
            journal=journal,
            candidates=candidates,
            limit=remaining,
            base_dir=base_dir,
            fetcher=fetcher,
            robots=robots,
            dry_run=dry_run,
        )
    )
    return collected
