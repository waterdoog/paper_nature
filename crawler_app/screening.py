from typing import Optional, Sequence, Tuple

from .http_client import RobotsCache, ThrottledFetcher
from .utils import safe_filename
from urllib.parse import urlparse


def is_html_content(content_type: str) -> bool:
    return "text/html" in (content_type or "").lower()


def screen_resource(
    fetcher: ThrottledFetcher, robots: RobotsCache, url: str
) -> Tuple[str, str]:
    """Return (status, reason) for a resource URL."""
    if not robots.allowed(url):
        return "manual_required", "robots_disallowed"
    status, content_type, _ = fetcher.head_info(url)
    if status is None or status >= 400:
        return "unavailable", f"status={status}"
    if is_html_content(content_type):
        return "unavailable", f"content_type={content_type}"
    return "downloadable", ""


def repo_zip_name(repo_url: str) -> str:
    repo_name = repo_url.rstrip("/").split("/")[-1] or "code"
    return f"{safe_filename(repo_name)}.zip"


def github_zip_urls(repo_url: str) -> list[str]:
    parsed = urlparse(repo_url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return []
    owner, repo = parts[0], parts[1]
    return [
        f"https://codeload.github.com/{owner}/{repo}/zip/HEAD",
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/main",
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/master",
    ]


def find_working_zip_url(
    fetcher: ThrottledFetcher, robots: RobotsCache, repo_urls: Sequence[str]
) -> Tuple[Optional[str], Optional[str], str]:
    saw_manual = False
    for repo_url in repo_urls:
        for zip_url in github_zip_urls(repo_url):
            status, _ = screen_resource(fetcher, robots, zip_url)
            if status == "downloadable":
                return zip_url, repo_url, "downloadable"
            if status == "manual_required":
                saw_manual = True
                continue
        if saw_manual:
            return None, repo_url, "manual_required"
    return None, repo_urls[0] if repo_urls else None, "manual_required"
