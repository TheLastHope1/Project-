"""Normalized in-memory representation of a news item before persistence.

Every source client returns ``RawNewsItem`` objects so the ingest layer only
deals with one shape. ``dedup_hash`` collapses the same story arriving from
multiple feeds (e.g. Google News + GDELT both surfacing a Reuters piece) into
one stored row.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from urllib.parse import urlsplit, urlunsplit

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")


def clean_html(text: str | None) -> str | None:
    """Strip HTML tags + unescape entities (RSS descriptions are HTML)."""
    if not text:
        return None
    stripped = _TAG_RE.sub(" ", text)
    stripped = unescape(stripped)
    stripped = _WS_RE.sub(" ", stripped).strip()
    return stripped or None
# Google News appends " - Publisher" to titles; strip it for cleaner dedup/NLP.
_TRAILING_SOURCE_RE = re.compile(r"\s+-\s+[^-]+$")
_TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "oc=", "ocid")


def normalize_title(title: str) -> str:
    title = _WS_RE.sub(" ", (title or "").strip())
    return _TRAILING_SOURCE_RE.sub("", title)


def canonical_url(url: str | None) -> str:
    """Strip scheme, fragment, and tracking query params for stable hashing."""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    query = parts.query
    if any(token in query for token in _TRACKING_PARAMS):
        query = ""
    host = parts.netloc.lower()
    path = parts.path.rstrip("/")
    return urlunsplit(("", host, path, query, "")).lstrip("/").lower()


@dataclass
class RawNewsItem:
    source: str                      # rss | gdelt | newsapi | twitter
    title: str
    url: str | None = None
    summary: str | None = None
    source_name: str | None = None   # e.g. "Reuters"
    published_at: datetime | None = None
    language: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def dedup_hash(self) -> str:
        norm = normalize_title(self.title).lower()
        basis = f"{norm}|{canonical_url(self.url)}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    @property
    def text(self) -> str:
        """Title + summary, used for entity extraction and LLM context."""
        parts = [normalize_title(self.title)]
        if self.summary:
            parts.append(self.summary)
        return "\n".join(parts)
