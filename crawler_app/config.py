from typing import List

from .models import JournalConfig


DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NatureCrawler/1.0"


def build_journals() -> List[JournalConfig]:
    """Return the configured journal sources."""
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
