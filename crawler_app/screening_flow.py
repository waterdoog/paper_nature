from typing import List, Set
from urllib.parse import urlparse

from .http_client import RobotsCache, ThrottledFetcher
from .models import JournalConfig, ScreeningResult
from .parser import extract_article_data, parse_listing
from .screening import find_working_zip_url, screen_resource
from .utils import safe_filename


def screen_journal(
    journal: JournalConfig,
    remaining: int,
    start_year: int,
    end_year: int,
    max_pages: int,
    fetcher: ThrottledFetcher,
    robots: RobotsCache,
    existing_slugs: Set[str],
    url_cache: dict[str, str],
) -> List[ScreeningResult]:
    """Return screened candidates without downloading any files."""
    candidates: List[ScreeningResult] = []
    pages = 0
    base_url = "https://www.nature.com"

    print(f"[info] Screening {journal.slug} for eligible articles...")
    while len(candidates) < remaining and pages < max_pages:
        pages += 1
        list_url = journal.list_url_template.format(page=pages)
        if not robots.allowed(list_url):
            print(f"[robots] Skip list page disallowed: {list_url}")
            break
        try:
            listing_html = fetcher.fetch_text(list_url)
        except Exception as exc:
            print(f"[error] Failed listing page {list_url}: {exc}")
            break

        entries = parse_listing(listing_html, base_url)
        if not entries:
            break

        stop_due_to_year = False
        for article_url, published in entries:
            if published.year < start_year:
                print(
                    f"[skip] reason=out_of_year_range_before_{start_year} url={article_url}"
                )
                stop_due_to_year = True
                break
            if published.year > end_year:
                print(
                    f"[skip] reason=out_of_year_range_after_{end_year} url={article_url}"
                )
                continue
            if len(candidates) >= remaining:
                break
            cached_reason = url_cache.get(article_url)
            if cached_reason:
                print(f"[skip] reason=cached:{cached_reason} url={article_url}")
                continue
            if not robots.allowed(article_url):
                print(f"[skip] reason=robots_disallowed url={article_url}")
                url_cache[article_url] = "robots_disallowed"
                continue
            article_slug = safe_filename(urlparse(article_url).path.strip("/").split("/")[-1])
            if article_slug in existing_slugs:
                continue
            try:
                article_html = fetcher.fetch_text(article_url)
            except Exception as exc:
                print(f"[error] Failed article {article_url}: {exc}")
                continue

            article = extract_article_data(journal, article_url, article_html)
            if not article.github_repos:
                print(f"[skip] reason=missing_github_link url={article_url}")
                url_cache[article_url] = "missing_github_link"
                continue
            if not article.pdf_url:
                print(f"[skip] reason=missing_pdf_link url={article_url}")
                url_cache[article_url] = "missing_pdf_link"
                continue
            peer_review_resource = next(
                (res for res in article.esm_resources if res.category == "peer_review"), None
            )
            if not peer_review_resource:
                print(f"[skip] reason=missing_peer_review_file url={article_url}")
                url_cache[article_url] = "missing_peer_review_file"
                continue

            pdf_status, pdf_reason = screen_resource(fetcher, robots, article.pdf_url)
            if pdf_status == "unavailable":
                print(f"[skip] reason=pdf_unavailable {pdf_reason} url={article_url}")
                continue
            if pdf_status == "manual_required":
                print(
                    f"[manual] reason=robots_disallowed kind=pdf url={article_url} resource={article.pdf_url}"
                )

            review_status, review_reason = screen_resource(
                fetcher, robots, peer_review_resource.url
            )
            if review_status == "unavailable":
                print(f"[skip] reason=peer_review_unavailable {review_reason} url={article_url}")
                continue
            if review_status == "manual_required":
                print(
                    f"[manual] reason=robots_disallowed kind=peer_review url={article_url} resource={peer_review_resource.url}"
                )

            code_zip_url, code_repo, code_status = find_working_zip_url(
                fetcher, robots, article.github_repos
            )
            if not code_repo:
                print(f"[skip] reason=github_repo_missing url={article_url}")
                continue
            if code_status == "manual_required":
                print(f"[manual] reason=code_zip_unavailable url={article_url} repo={code_repo}")

            candidates.append(
                ScreeningResult(
                    article=article,
                    code_zip_url=code_zip_url,
                    code_repo=code_repo,
                    peer_review_resource=peer_review_resource,
                    pdf_status=pdf_status,
                    peer_review_status=review_status,
                    code_status=code_status,
                )
            )

        if stop_due_to_year:
            break

    print(f"[info] Found {len(candidates)} eligible articles for {journal.slug}.")
    return candidates
