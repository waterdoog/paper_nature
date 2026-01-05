import os
from typing import Dict, List
from urllib.parse import urlparse

from .http_client import RobotsCache, ThrottledFetcher
from .models import JournalConfig, ScreeningResult
from .screening import repo_zip_name
from .storage import (
    build_metadata_record,
    cleanup_article_dir,
    ensure_article_dirs,
    write_metadata_json,
)
from .utils import safe_filename


def download_candidates(
    journal: JournalConfig,
    candidates: List[ScreeningResult],
    limit: int,
    base_dir: str,
    fetcher: ThrottledFetcher,
    robots: RobotsCache,
    dry_run: bool = False,
) -> List[Dict[str, object]]:
    """Download files for screened candidates and write metadata."""
    records: List[Dict[str, object]] = []
    category_dir = os.path.join(base_dir, journal.category)

    for result in candidates:
        if len(records) >= limit:
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
                    print(
                        f"[manual] reason=robots_disallowed kind=pdf url={article.url} resource={article.pdf_url}"
                    )
            else:
                manual_required.append("pdf")
                print(
                    f"[manual] reason=manual_required kind=pdf url={article.url} resource={article.pdf_url}"
                )

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
                print(
                    f"[manual] reason=manual_required kind=code url={article.url} repo={result.code_repo}"
                )

            for resource in article.esm_resources:
                if resource.category == "peer_review" and review_status != "downloadable":
                    continue
                if not robots.allowed(resource.url):
                    manual_required.append(resource.category)
                    continue
                target_dir = article_paths["data"] if resource.category == "data" else article_paths["supp"]
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

        record = build_metadata_record(
            article=article,
            used_repo=used_repo,
            pdf_status=pdf_status,
            review_status=review_status,
            code_status=code_status,
            manual_required=manual_required,
            article_paths=article_paths,
            pdf_path=pdf_path,
            code_zip_path=code_zip_path,
            supp_paths=supp_paths,
            data_paths=data_paths,
            peer_review_path=peer_review_path,
            peer_review_name=peer_review_name,
            esm_mapping=esm_mapping,
            esm_items=esm_items,
            dry_run=dry_run,
        )
        write_metadata_json(metadata_path, record)
        records.append(record)

    return records
