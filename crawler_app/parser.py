import json
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .models import ArticleData, ESMResource, JournalConfig
from .utils import safe_filename, parse_date


def _soup(html: str):
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: beautifulsoup4. Install with `pip install -r requirements.txt`."
        ) from exc
    return BeautifulSoup(html, "html.parser")


def parse_listing(html: str, base_url: str) -> List[Tuple[str, "datetime"]]:
    """Parse the journal listing page into (article_url, published_date)."""
    soup = _soup(html)
    results: List[Tuple[str, "datetime"]] = []
    for card in soup.select("article.c-card"):
        link = card.select_one("a.c-card__link")
        time_tag = card.select_one("time")
        if not link or not time_tag:
            continue
        href = link.get("href")
        date_value = time_tag.get("datetime") or time_tag.get_text(strip=True)
        parsed_date = parse_date(date_value)
        if not href or not parsed_date:
            continue
        results.append((urljoin(base_url, href), parsed_date))
    return results


def extract_article_data(journal: JournalConfig, url: str, html: str) -> ArticleData:
    """Extract metadata and resource links from an article page."""
    soup = _soup(html)
    title_tag = soup.find("meta", {"name": "dc.title"})
    title = title_tag.get("content") if title_tag else None
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else "unknown"

    jsonld = extract_jsonld_metadata(soup)
    published_date = jsonld.get("datePublished") if jsonld else None
    doi = jsonld.get("identifier") if jsonld else None
    if isinstance(doi, dict):
        doi = doi.get("value")

    if not published_date:
        date_tag = soup.find("meta", {"name": "citation_online_date"})
        published_date = date_tag.get("content") if date_tag else None

    pdf_url = None
    pdf_meta = soup.find("meta", {"name": "citation_pdf_url"})
    if pdf_meta and pdf_meta.get("content"):
        pdf_url = pdf_meta.get("content")
        if pdf_url and not pdf_url.startswith("http"):
            pdf_url = urljoin(url, pdf_url)
    if not pdf_url:
        for anchor in soup.select("a[href]"):
            text = anchor.get_text(" ", strip=True).lower()
            href = anchor.get("href")
            if not href:
                continue
            if "download pdf" in text or (
                href.lower().endswith(".pdf") and "supplementary" not in href.lower()
            ):
                pdf_url = urljoin(url, href)
                break

    github_links = extract_github_links(soup)
    esm_resources = extract_esm_resources(soup, url)

    return ArticleData(
        journal=journal.name,
        category=journal.category,
        url=url,
        title=title,
        published_date=published_date or "",
        doi=doi,
        github_repos=github_links,
        pdf_url=pdf_url,
        esm_resources=esm_resources,
    )


def extract_jsonld_metadata(soup) -> Dict[str, str]:
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") in ("ScholarlyArticle", "Article"):
            return data
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") in ("ScholarlyArticle", "Article"):
                    return item
    return {}


def extract_section_by_heading(soup, heading_text: str):
    for heading in soup.find_all(["h2", "h3"]):
        if heading_text.lower() in heading.get_text(strip=True).lower():
            return heading.find_parent()
    return None


def extract_github_links(soup) -> List[str]:
    """Return normalized GitHub repository URLs."""
    github_links: List[str] = []
    section = extract_section_by_heading(soup, "Code availability")
    if section:
        github_links.extend([a["href"] for a in section.select("a[href]") if "github.com" in a["href"]])
        raw_text = section.get_text(" ", strip=True)
    else:
        github_links.extend([a["href"] for a in soup.select("a[href]") if "github.com" in a["href"]])
        raw_text = soup.get_text(" ", strip=True)

    github_links.extend(
        re.findall(r"https?://github\\.com/[\\w.-]+/[\\w.-]+(?:/[^\\s<>()\"]*)?", raw_text)
    )

    normalized = []
    seen = set()
    for link in github_links:
        repo = normalize_github_repo(link)
        if repo and repo not in seen:
            seen.add(repo)
            normalized.append(repo)
    return normalized


def normalize_github_repo(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.netloc.lower() not in ("github.com", "www.github.com"):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1].replace(".git", "")
    return f"https://github.com/{owner}/{repo}"


def normalize_link_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def infer_category_from_text(text: str) -> str:
    lowered = text.lower()
    if "peer review" in lowered or "peer-review" in lowered:
        return "peer_review"
    if "data" in lowered:
        return "data"
    return "supplementary"


def human_name_to_filename(text: str, url: str) -> str:
    cleaned = normalize_link_text(text)
    if not cleaned:
        cleaned = os.path.basename(urlparse(url).path)
    base = safe_filename(cleaned.replace(" ", "_"))
    ext = os.path.splitext(urlparse(url).path)[1]
    if ext and not base.lower().endswith(ext.lower()):
        base = f"{base}{ext}"
    elif not os.path.splitext(base)[1]:
        base = f"{base}.pdf"
    return base or "supplementary.pdf"


def extract_esm_resources(soup, base_url: str) -> List[ESMResource]:
    """Extract explicit ESM resource links from the article page."""
    resources: List[ESMResource] = []
    seen_urls = set()
    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if not href:
            continue
        full_url = urljoin(base_url, href)
        if not full_url.startswith("http"):
            continue
        parsed_url = urlparse(full_url)
        if parsed_url.netloc.lower() != "static-content.springer.com":
            continue
        if not os.path.splitext(parsed_url.path)[1]:
            continue
        if full_url in seen_urls:
            continue
        link_text = normalize_link_text(anchor.get_text(" ", strip=True))
        if not link_text:
            continue
        category = infer_category_from_text(link_text)
        if category == "peer_review":
            filename = "Peer_Review_File.pdf"
        else:
            filename = human_name_to_filename(link_text, full_url)
        resources.append(ESMResource(url=full_url, link_text=link_text, filename=filename, category=category))
        seen_urls.add(full_url)

    used_names = set()
    for resource in resources:
        filename = resource.filename
        if filename in used_names:
            base, ext = os.path.splitext(filename)
            counter = 2
            while f"{base}_{counter}{ext}" in used_names:
                counter += 1
            filename = f"{base}_{counter}{ext}"
            resource.filename = filename
        used_names.add(filename)
    return resources
