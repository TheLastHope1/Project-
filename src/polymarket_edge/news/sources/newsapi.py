"""NewsAPI.org source (optional, key-gated).

Activates only when ``NEWSAPI_KEY`` is set. The key is sent in the
``X-Api-Key`` header (never the query string) so it cannot leak into request
logs or referer headers.
"""
from __future__ import annotations

from datetime import UTC, datetime

from dateutil import parser as dtparser

from polymarket_edge.clients.base import APIClient
from polymarket_edge.config import Settings
from polymarket_edge.logging import get_logger
from polymarket_edge.news.models import RawNewsItem

log = get_logger(__name__)

_NEWSAPI_BASE = "https://newsapi.org"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = dtparser.parse(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


async def fetch(settings: Settings, query_terms: list[str]) -> list[RawNewsItem]:
    if not settings.NEWSAPI_KEY:
        return []
    headers = {"X-Api-Key": settings.NEWSAPI_KEY}
    page_size = min(100, settings.NEWS_MAX_ITEMS_PER_SOURCE)

    if query_terms:
        path = "/v2/everything"
        params = {
            "q": " OR ".join(query_terms),
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": page_size,
        }
    else:
        path = "/v2/top-headlines"
        params = {"language": "en", "pageSize": page_size}

    async with APIClient(_NEWSAPI_BASE) as client:
        data = await client.get_json(path, params=params, headers=headers)

    if not isinstance(data, dict) or data.get("status") != "ok":
        return []
    items: list[RawNewsItem] = []
    for art in data.get("articles", []):
        if not isinstance(art, dict):
            continue
        title = (art.get("title") or "").strip()
        if not title:
            continue
        src = art.get("source") or {}
        items.append(
            RawNewsItem(
                source="newsapi",
                title=title,
                url=(art.get("url") or "").strip() or None,
                summary=(art.get("description") or "").strip() or None,
                source_name=(src.get("name") if isinstance(src, dict) else None),
                published_at=_parse_dt(art.get("publishedAt")),
                language="en",
                raw={"author": art.get("author")},
            )
        )
    return items
