import csv
import json
import os
import shutil
from typing import Dict, List, Optional, Sequence

from .models import ArticleData


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
        if os.path.exists(os.path.join(entry.path, "metadata.json")):
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


def collect_existing_records(base_dir: str) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    if not os.path.isdir(base_dir):
        return records
    for root, _, files in os.walk(base_dir):
        if "metadata.json" not in files:
            continue
        records.append(load_metadata_for_dir(root))
    return records


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


def build_metadata_record(
    article: ArticleData,
    used_repo: str,
    pdf_status: str,
    review_status: str,
    code_status: str,
    manual_required: List[str],
    article_paths: Dict[str, str],
    pdf_path: str,
    code_zip_path: str,
    supp_paths: List[str],
    data_paths: List[str],
    peer_review_path: str,
    peer_review_name: str,
    esm_mapping: Dict[str, str],
    esm_items: List[Dict[str, object]],
    dry_run: bool,
) -> Dict[str, object]:
    return {
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
