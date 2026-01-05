from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class JournalConfig:
    name: str
    slug: str
    category: str
    list_url_template: str


@dataclass
class ESMResource:
    url: str
    link_text: str
    filename: str
    category: str


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
    esm_resources: List[ESMResource] = field(default_factory=list)


@dataclass
class ScreeningResult:
    article: ArticleData
    code_zip_url: Optional[str]
    code_repo: str
    peer_review_resource: ESMResource
    pdf_status: str
    peer_review_status: str
    code_status: str
