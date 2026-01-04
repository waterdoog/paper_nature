#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import sys
import time
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - runtime requirement
    print("Missing dependency: beautifulsoup4. Install with `pip install -r requirements.txt`.")
    sys.exit(1)


DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NatureCrawler/1.0"


@dataclass
class JournalConfig:
    name: str
    slug: str
    category: str
    list_url_template: str


@dataclass
class ArticleData:
    journal: str
    category: str
    url: str
    title: str
    published_date: str
    doi: Optional[str]
    github_repos: List[str] = field(default_factory=list)
    pdf_url: Optional[str] = None
    esm_resources: List["ESMResource"] = field(default_factory=list)


@dataclass
class ESMResource:
    url: str
    link_text: str
    filename: str
    category: str


@dataclass
class ScreeningResult:
    article: ArticleData
    code_zip_url: Optional[str]
    code_repo: str
    peer_review_resource: ESMResource
    pdf_status: str
    peer_review_status: str
    code_status: str


class RobotsCache:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self.cache: Dict[str, RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self.cache:
            rp = RobotFileParser()
            rp.set_url(urljoin(base, "/robots.txt"))
            try:
                rp.read()
            except Exception:
                # Fail closed to avoid violating robots.txt unintentionally.
                return False
            self.cache[base] = rp
        return self.cache[base].can_fetch(self.user_agent, url)


class ThrottledFetcher:
    def __init__(self, user_agent: str, delay: float, timeout: int, retries: int):
        self.user_agent = user_agent
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self._last_request = 0.0

    def _sleep_if_needed(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def fetch_text(self, url: str) -> str:
        content = self._request(url)
        return content.decode("utf-8", errors="ignore")

    def download_file(self, url: str, dest_path: str, label: Optional[str] = None) -> None:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        if not label:
            label = os.path.basename(dest_path) or url
        content = self._request(url, stream=True, dest_path=dest_path, label=label)
        if content is None:
            return

    def head_info(self, url: str) -> Tuple[Optional[int], str, Optional[int]]:
        headers = {"User-Agent": self.user_agent}
        self._sleep_if_needed()
        req = Request(url, headers=headers, method="HEAD")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                self._last_request = time.time()
                content_type = resp.headers.get("Content-Type") or ""
                length = resp.headers.get("Content-Length")
                size = int(length) if length and length.isdigit() else None
                return resp.status, content_type, size
        except Exception:
            return None, "", None

    def _request(
        self,
        url: str,
        stream: bool = False,
        dest_path: Optional[str] = None,
        label: str = "",
    ) -> bytes:
        headers = {"User-Agent": self.user_agent}
        for attempt in range(self.retries):
            self._sleep_if_needed()
            req = Request(url, headers=headers, method="GET")
            try:
                with urlopen(req, timeout=self.timeout) as resp:
                    self._last_request = time.time()
                    if stream and dest_path:
                        content_type = (resp.headers.get("Content-Type") or "").lower()
                        ext = os.path.splitext(dest_path)[1].lower()
                        if "text/html" in content_type and ext not in (".html", ".htm"):
                            raise ValueError(
                                f"Unexpected Content-Type {content_type} for {dest_path}"
                            )
                        total_size = resp.headers.get("Content-Length")
                        total_size = int(total_size) if total_size and total_size.isdigit() else None
                        if total_size is None:
                            total_size = self._head_content_length(url)
                        downloaded = 0
                        next_percent = 5
                        last_log_time = time.time()
                        last_line_len = 0

                        def write_progress(message: str) -> None:
                            nonlocal last_line_len
                            sys.stdout.write(
                                "\r" + message + (" " * max(0, last_line_len - len(message)))
                            )
                            sys.stdout.flush()
                            last_line_len = len(message)

                        if total_size:
                            write_progress(f"[download] {label} 0% (0/{total_size} bytes)")
                        with open(dest_path, "wb") as handle:
                            while True:
                                chunk = resp.read(8192)
                                if not chunk:
                                    break
                                handle.write(chunk)
                                downloaded += len(chunk)
                                if total_size:
                                    percent = int(downloaded * 100 / total_size)
                                    if percent >= next_percent:
                                        write_progress(
                                            f"[download] {label} {percent}% ({downloaded}/{total_size} bytes)"
                                        )
                                        next_percent = percent + 5
                                        last_log_time = time.time()
                                if time.time() - last_log_time >= 10 and total_size:
                                    percent = int(downloaded * 100 / total_size)
                                    write_progress(
                                        f"[download] {label} {percent}% ({downloaded}/{total_size} bytes)"
                                    )
                                    next_percent = max(next_percent, percent + 5)
                                    last_log_time = time.time()
                        if total_size is None:
                            total_size = downloaded
                        if last_line_len:
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                        print(f"[download] Done {label} ({total_size}/{total_size} bytes)")
                        return b""
                    return resp.read()
            except (HTTPError, URLError) as exc:
                if attempt + 1 == self.retries:
                    raise exc
                time.sleep(self.delay * (2 ** attempt))
        raise RuntimeError(f"Failed to fetch {url}")

    def _head_content_length(self, url: str) -> Optional[int]:
        headers = {"User-Agent": self.user_agent}
        self._sleep_if_needed()
        req = Request(url, headers=headers, method="HEAD")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                self._last_request = time.time()
                length = resp.headers.get("Content-Length")
                return int(length) if length and length.isdigit() else None
        except Exception:
            return None


def safe_filename(value: str, max_len: int = 180) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    cleaned = cleaned.strip("._-")
    return cleaned[:max_len] if cleaned else "unknown"


def parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_html_content(content_type: str) -> bool:
    return "text/html" in (content_type or "").lower()


def screen_resource(
    fetcher: ThrottledFetcher, robots: RobotsCache, url: str, kind: str, article_url: str
) -> Tuple[str, str]:
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


def find_working_zip_url(
    fetcher: ThrottledFetcher, robots: RobotsCache, repo_urls: Sequence[str], article_url: str
) -> Tuple[Optional[str], Optional[str], str]:
    saw_manual = False
    for repo_url in repo_urls:
        for zip_url in github_zip_urls(repo_url):
            status, reason = screen_resource(fetcher, robots, zip_url, "code_zip", article_url)
            if status == "downloadable":
                return zip_url, repo_url, "downloadable"
            if status == "manual_required":
                saw_manual = True
                continue
        if saw_manual:
            return None, repo_url, "manual_required"
    return None, repo_urls[0] if repo_urls else None, "manual_required"


def extract_jsonld_metadata(soup: BeautifulSoup) -> Dict[str, str]:
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


def extract_article_data(journal: JournalConfig, url: str, html: str) -> ArticleData:
    soup = BeautifulSoup(html, "html.parser")
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
            if "download pdf" in text or (href.lower().endswith(".pdf") and "supplementary" not in href.lower()):
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


def extract_section_by_heading(soup: BeautifulSoup, heading_text: str) -> Optional[BeautifulSoup]:
    for heading in soup.find_all(["h2", "h3"]):
        if heading_text.lower() in heading.get_text(strip=True).lower():
            return heading.find_parent()
    return None


def extract_github_links(soup: BeautifulSoup) -> List[str]:
    github_links: List[str] = []
    section = extract_section_by_heading(soup, "Code availability")
    if section:
        github_links.extend([a["href"] for a in section.select("a[href]") if "github.com" in a["href"]])
        raw_text = section.get_text(" ", strip=True)
        github_links.extend(
            re.findall(r"https?://github\\.com/[\\w.-]+/[\\w.-]+(?:/[^\\s<>()\"]*)?", raw_text)
        )
        if not github_links:
            return []
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
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned


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
    if ext:
        if not base.lower().endswith(ext.lower()):
            base = f"{base}{ext}"
    elif not os.path.splitext(base)[1]:
        base = f"{base}.pdf"
    return base or "supplementary.pdf"


def extract_esm_resources(soup: BeautifulSoup, base_url: str) -> List[ESMResource]:
    """
    从HTML页面中提取补充材料资源（ESM）
    
    该函数从解析后的HTML页面中提取所有补充材料链接，包括但不限于PDF、ZIP、DOCX等格式的文件。
    特别优化了对Nature期刊补充材料的识别，通过关键词匹配和文件扩展名过滤来确保捕获所有相关资源。
    
    参数:
        soup (BeautifulSoup): 解析后的HTML页面内容
        base_url (str): 基础URL，用于将相对链接转换为绝对链接
    
    返回:
        List[ESMResource]: 提取到的补充材料资源列表，包含URL、链接文本、文件名和资源类别
    """
    # 初始化资源列表和已处理URL集合
    resources: List[ESMResource] = []
    seen_urls = set()
    
    # 遍历页面中所有带href属性的<a>标签
    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        # 跳过空链接
        if not href:
            continue
            
        # 将相对链接转换为绝对链接
        full_url = urljoin(base_url, href)
        if not full_url.startswith("http"):
            continue
        parsed_url = urlparse(full_url)
        if parsed_url.netloc.lower() != "static-content.springer.com":
            continue
        if not os.path.splitext(parsed_url.path)[1]:
            continue
        
        # 放宽过滤条件以包含Nature的补充材料
        # Nature使用多种域名，包括nature.com、springer.com等
        # 允许包含常见补充材料指示符的链接
        if any(indicator in full_url.lower() for indicator in [
            "supplementary", "supplement", "esm", "static-content.springer.com", 
            ".pdf", ".zip", ".docx", ".xlsx", ".csv"
        ]) or "MOESM" in full_url.upper():
            # 跳过已处理的URL，避免重复
            if full_url in seen_urls:
                continue
                
            # 规范化链接文本，用于生成文件名和分类
            link_text = normalize_link_text(anchor.get_text(" ", strip=True))
            # 跳过无文本的链接
            if not link_text:
                continue
                
            # 根据链接文本推断资源类别
            category = infer_category_from_text(link_text)
            
            # 为同行评审文件设置固定文件名
            if category == "peer_review":
                filename = "Peer_Review_File.pdf"
            else:
                # 为其他资源生成规范化的文件名
                filename = human_name_to_filename(link_text, full_url)
                
            # 添加资源到列表并标记URL为已处理
            resources.append(ESMResource(url=full_url, link_text=link_text, filename=filename, category=category))
            seen_urls.add(full_url)

    # 处理重复文件名，确保每个文件名唯一
    used_names = set()
    for resource in resources:
        filename = resource.filename
        # 如果文件名已存在，添加数字后缀确保唯一性
        if filename in used_names:
            base, ext = os.path.splitext(filename)
            counter = 2
            # 查找可用的文件名（添加_2, _3等后缀）
            while f"{base}_{counter}{ext}" in used_names:
                counter += 1
            filename = f"{base}_{counter}{ext}"
            resource.filename = filename
        # 标记文件名为已使用
        used_names.add(filename)
        
    # 返回处理后的资源列表
    return resources


def parse_listing(html: str, base_url: str) -> List[Tuple[str, datetime]]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
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


def github_zip_urls(repo_url: str) -> List[str]:
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


def ensure_article_dirs(base_dir: str, category: str, article_slug: str) -> Dict[str, str]:
    article_dir = os.path.join(base_dir, category, article_slug)
    paths = {
        "article": article_dir,
        "pdf": os.path.join(article_dir, "pdf_papers"),
        "code": os.path.join(article_dir, "code"),
        "supp": os.path.join(article_dir, "supplementary_materials"),
        "data": os.path.join(article_dir, "data"),
    }
    for path in paths.values():
        os.makedirs(path, exist_ok=True)
    return paths


def write_metadata_json(meta_path: str, record: Dict[str, object]) -> None:
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=True, indent=2)


def cleanup_article_dir(path: str) -> None:
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def list_existing_article_dirs(category_dir: str) -> List[str]:
    if not os.path.isdir(category_dir):
        return []
    dirs = []
    for entry in os.scandir(category_dir):
        if not entry.is_dir():
            continue
        meta_path = os.path.join(entry.path, "metadata.json")
        if os.path.exists(meta_path):
            dirs.append(entry.path)
    return sorted(dirs)


def load_metadata_for_dir(article_dir: str) -> Dict[str, object]:
    meta_path = os.path.join(article_dir, "metadata.json")
    record: Dict[str, object] = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                record = json.load(handle)
        except Exception:
            record = {}
    output = record.get("output", {}) if isinstance(record.get("output"), dict) else {}
    output.setdefault("article_dir", article_dir)
    output.setdefault("pdf", os.path.join("pdf_papers", "paper.pdf"))
    output.setdefault(
        "peer_review_file", os.path.join("supplementary_materials", "Peer_Review_File.pdf")
    )
    if not output.get("code_zip"):
        code_dir = os.path.join(article_dir, "code")
        if os.path.isdir(code_dir):
            for entry in os.scandir(code_dir):
                if entry.is_file() and entry.name.lower().endswith(".zip"):
                    output["code_zip"] = os.path.join("code", entry.name)
                    break
    record["output"] = output
    if "category" not in record:
        record["category"] = os.path.basename(os.path.dirname(article_dir))
    return record


def resolve_output_path(article_dir: str, relative_path: str, fallback: Optional[str] = None) -> str:
    if relative_path:
        return os.path.join(article_dir, relative_path)
    return os.path.join(article_dir, fallback) if fallback else ""


def write_summary_csv(base_dir: str, records: Sequence[Dict[str, object]]) -> None:
    summary_path = os.path.join(base_dir, "summary.csv")
    fieldnames = [
        "category",
        "article_slug",
        "title",
        "url",
        "pdf_path",
        "review_path",
        "code_path",
    ]
    with open(summary_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            output = record.get("output", {})
            article_dir = output.get("article_dir", "")
            if not article_dir:
                continue
            pdf_path = resolve_output_path(
                article_dir, output.get("pdf", ""), os.path.join("pdf_papers", "paper.pdf")
            )
            review_path = resolve_output_path(
                article_dir,
                output.get("peer_review_file", ""),
                os.path.join("supplementary_materials", "Peer_Review_File.pdf"),
            )
            code_path = resolve_output_path(article_dir, output.get("code_zip", ""))
            if not (os.path.exists(pdf_path) and os.path.exists(review_path) and os.path.exists(code_path)):
                continue
            writer.writerow(
                {
                    "category": record.get("category", ""),
                    "article_slug": os.path.basename(article_dir),
                    "title": record.get("title", ""),
                    "url": record.get("url", ""),
                    "pdf_path": pdf_path,
                    "review_path": review_path,
                    "code_path": code_path,
                }
            )


def download_github_zip(
    fetcher: ThrottledFetcher,
    repo_urls: Sequence[str],
    dest_dir: str,
    label_prefix: str = "",
) -> Tuple[bool, Optional[str], Optional[str]]:
    for repo_url in repo_urls:
        repo_name = repo_url.rstrip("/").split("/")[-1]
        if not repo_name:
            continue
        zip_name = f"{safe_filename(repo_name)}.zip"
        dest_path = os.path.join(dest_dir, zip_name)
        display_label = f"{label_prefix} {zip_name}".strip()
        for zip_url in github_zip_urls(repo_url):
            try:
                fetcher.download_file(zip_url, dest_path, label=display_label)
                return True, dest_path, repo_url
            except Exception:
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except OSError:
                        pass
                continue
    return False, None, None


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
    collected: List[Dict[str, object]] = []
    candidates: List[ScreeningResult] = []
    pages = 0
    base_url = "https://www.nature.com"
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
            if not robots.allowed(article_url):
                print(f"[skip] reason=robots_disallowed url={article_url}")
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
                continue
            if not article.pdf_url:
                print(f"[skip] reason=missing_pdf_link url={article_url}")
                continue
            peer_review_resource = next(
                (res for res in article.esm_resources if res.category == "peer_review"), None
            )
            if not peer_review_resource:
                print(f"[skip] reason=missing_peer_review_file url={article_url}")
                continue

            pdf_status, pdf_reason = screen_resource(fetcher, robots, article.pdf_url, "pdf", article_url)
            if pdf_status == "unavailable":
                print(f"[skip] reason=pdf_unavailable {pdf_reason} url={article_url}")
                continue
            if pdf_status == "manual_required":
                print(f"[manual] reason=robots_disallowed kind=pdf url={article_url} resource={article.pdf_url}")

            review_status, review_reason = screen_resource(
                fetcher, robots, peer_review_resource.url, "peer_review", article_url
            )
            if review_status == "unavailable":
                print(f"[skip] reason=peer_review_unavailable {review_reason} url={article_url}")
                continue
            if review_status == "manual_required":
                print(
                    f"[manual] reason=robots_disallowed kind=peer_review url={article_url} resource={peer_review_resource.url}"
                )

            code_zip_url, code_repo, code_status = find_working_zip_url(
                fetcher, robots, article.github_repos, article_url
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

    for result in candidates:
        if len(collected) >= n_per_journal:
            break

        article = result.article
        peer_review_name = result.peer_review_resource.filename

        article_slug = safe_filename(urlparse(article.url).path.strip("/").split("/")[-1])
        article_dir_exists = os.path.exists(os.path.join(category_dir, article_slug))
        article_paths = ensure_article_dirs(base_dir, journal.category, article_slug)
        pdf_path = os.path.join(article_paths["pdf"], "paper.pdf")
        metadata_path = os.path.join(article_paths["article"], "metadata.json")

        code_zip_path = ""
        used_repo = result.code_repo
        supp_paths: List[str] = []
        data_paths: List[str] = []
        peer_review_path = ""
        manual_required: List[str] = []

        pdf_status = result.pdf_status
        review_status = result.peer_review_status
        code_status = result.code_status
        peer_review_expected_path = os.path.join(article_paths["supp"], peer_review_name)
        if os.path.exists(peer_review_expected_path):
            peer_review_path = peer_review_expected_path
            review_status = "present"
        elif review_status == "manual_required":
            manual_required.append("peer_review")

        if not dry_run:
            if os.path.exists(pdf_path):
                pdf_status = "present"
            elif pdf_status == "downloadable":
                if robots.allowed(article.pdf_url):
                    try:
                        fetcher.download_file(
                            article.pdf_url, pdf_path, label=f"{article_slug} paper.pdf"
                        )
                        pdf_status = "downloaded"
                    except Exception as exc:
                        print(f"[error] PDF download failed {article.pdf_url}: {exc}")
                        if not article_dir_exists:
                            cleanup_article_dir(article_paths["article"])
                        continue
                else:
                    pdf_status = "manual_required"
                    manual_required.append("pdf")
                    print(f"[manual] reason=robots_disallowed kind=pdf url={article.url} resource={article.pdf_url}")
            else:
                manual_required.append("pdf")
                print(f"[manual] reason=manual_required kind=pdf url={article.url} resource={article.pdf_url}")

            zip_name = repo_zip_name(result.code_repo)
            code_zip_path = os.path.join(article_paths["code"], zip_name)
            if os.path.exists(code_zip_path):
                code_status = "present"
            elif code_status == "downloadable" and result.code_zip_url:
                try:
                    fetcher.download_file(
                        result.code_zip_url, code_zip_path, label=f"{article_slug} {zip_name}"
                    )
                    code_status = "downloaded"
                except Exception as exc:
                    print(f"[error] GitHub zip download failed for {result.code_repo}: {exc}")
                    if not article_dir_exists:
                        cleanup_article_dir(article_paths["article"])
                    continue
            else:
                code_status = "manual_required"
                manual_required.append("code")
                print(f"[manual] reason=manual_required kind=code url={article.url} repo={result.code_repo}")

            for resource in article.esm_resources:
                if resource.category == "peer_review" and review_status != "downloadable":
                    continue
                if not robots.allowed(resource.url):
                    manual_required.append(resource.category)
                    continue
                if resource.category == "data":
                    target_dir = article_paths["data"]
                else:
                    target_dir = article_paths["supp"]
                dest_path = os.path.join(target_dir, resource.filename)
                if os.path.exists(dest_path):
                    if resource.category == "data":
                        data_paths.append(dest_path)
                    elif resource.category == "peer_review" and resource.filename == "Peer_Review_File.pdf":
                        peer_review_path = dest_path
                        supp_paths.append(dest_path)
                    else:
                        supp_paths.append(dest_path)
                    continue
                try:
                    fetcher.download_file(
                        resource.url, dest_path, label=f"{article_slug} {resource.filename}"
                    )
                    if resource.category == "data":
                        data_paths.append(dest_path)
                    elif resource.category == "peer_review" and resource.filename == "Peer_Review_File.pdf":
                        peer_review_path = dest_path
                        supp_paths.append(dest_path)
                    else:
                        supp_paths.append(dest_path)
                except Exception as exc:
                    print(f"[error] Failed to download {resource.filename} from {resource.url}: {exc}")
                    continue

            if not peer_review_path and review_status != "manual_required":
                print(f"[error] Missing Peer Review file for {article.url}")
                if not article_dir_exists:
                    cleanup_article_dir(article_paths["article"])
                continue

        esm_mapping = {res.url: res.filename for res in article.esm_resources}
        esm_items = [
            {
                "url": res.url,
                "link_text": res.link_text,
                "filename": res.filename,
                "category": res.category,
            }
            for res in article.esm_resources
        ]

        record = {
            "journal": article.journal,
            "category": article.category,
            "title": article.title,
            "url": article.url,
            "published_date": article.published_date,
            "doi": article.doi or "",
            "github_repos": article.github_repos,
            "used_github_repo": used_repo or "",
            "pdf_url": article.pdf_url,
            "status": {
                "pdf": pdf_status,
                "peer_review": review_status,
                "code": code_status,
            },
            "manual_required": sorted(set(manual_required)),
            "output": {
                "article_dir": article_paths["article"],
                "pdf": "pdf_papers/paper.pdf" if not dry_run else "",
                "code_zip": (
                    os.path.join("code", os.path.basename(code_zip_path))
                    if not dry_run and code_zip_path
                    else ""
                ),
                "supplementary_files": [
                    os.path.join("supplementary_materials", os.path.basename(path))
                    for path in supp_paths
                    if path
                ]
                if not dry_run
                else [],
                "data_files": [
                    os.path.join("data", os.path.basename(path)) for path in data_paths if path
                ]
                if not dry_run
                else [],
                "peer_review_file": (
                    os.path.join(
                        "supplementary_materials",
                        os.path.basename(peer_review_path or peer_review_name),
                    )
                    if (peer_review_path or peer_review_name)
                    else ""
                ),
            },
            "esm_mapping": esm_mapping,
            "esm_resources": esm_items,
        }
        write_metadata_json(metadata_path, record)
        collected.append(record)

    return collected


def build_journals() -> List[JournalConfig]:
    return [
        JournalConfig(
            name="Nature Human Behaviour",
            slug="nathumbehav",
            category="social_sci",
            list_url_template=(
                "https://www.nature.com/nathumbehav/research-articles"
                "?searchType=journalSearch&sort=PubDate&page={page}"
            ),
        ),
        JournalConfig(
            name="Palgrave Communications",
            slug="palcomms",
            category="natural_sci",
            list_url_template=(
                "https://www.nature.com/palcomms/research-articles"
                "?searchType=journalSearch&sort=PubDate&page={page}"
            ),
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Nature journal crawler for 2023-2026 papers with GitHub code.")
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
    args = parser.parse_args()

    journals = build_journals()
    robots = RobotsCache(args.user_agent)
    fetcher = ThrottledFetcher(args.user_agent, args.delay, args.timeout, args.retries)

    total = 0
    all_records: List[Dict[str, object]] = []
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
        all_records.extend(records)

    print(f"[done] Total collected: {total}")
    write_summary_csv(args.output_dir, all_records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
