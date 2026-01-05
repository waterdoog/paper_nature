import os
import sys
import time
from typing import Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser


class RobotsCache:
    """Robots.txt cache with a strict default to avoid accidental violations."""

    def __init__(self, user_agent: str) -> None:
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
                return False
            self.cache[base] = rp
        return self.cache[base].can_fetch(self.user_agent, url)


class ThrottledFetcher:
    """HTTP helper with polite throttling and progress logs for downloads."""

    def __init__(self, user_agent: str, delay: float, timeout: int, retries: int) -> None:
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
        self._request(url, stream=True, dest_path=dest_path, label=label)

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
