import re
from datetime import datetime
from typing import Optional


def safe_filename(value: str, max_len: int = 180) -> str:
    """Normalize strings to filesystem-friendly ASCII names."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    cleaned = cleaned.strip("._-")
    return cleaned[:max_len] if cleaned else "unknown"


def parse_date(value: str) -> Optional[datetime]:
    """Parse common date formats from Nature listings."""
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
