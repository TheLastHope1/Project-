"""Pluggable live-news source clients.

Each source exposes ``async fetch(settings, query_terms) -> list[RawNewsItem]``
and degrades to an empty list on any error so one flaky feed never breaks the
pipeline. ``fetch_all`` fans out across the configured + usable sources.
"""
from __future__ import annotations

import asyncio

from polymarket_edge.config import Settings
from polymarket_edge.logging import get_logger
from polymarket_edge.news.models import RawNewsItem
from polymarket_edge.news.sources import gdelt, newsapi, rss, twitter

log = get_logger(__name__)

_FETCHERS = {
    "rss": rss.fetch,
    "gdelt": gdelt.fetch,
    "newsapi": newsapi.fetch,
    "twitter": twitter.fetch,
}


async def fetch_all(settings: Settings, query_terms: list[str] | None = None) -> list[RawNewsItem]:
    sources = settings.enabled_news_sources
    terms = query_terms if query_terms is not None else settings.news_query_terms

    async def _safe(name: str) -> list[RawNewsItem]:
        fetcher = _FETCHERS.get(name)
        if fetcher is None:
            return []
        try:
            items = await fetcher(settings, terms)
            log.info("news_source_fetched", source=name, items=len(items))
            return items
        except Exception as exc:  # noqa: BLE001 -- one source must not break the run
            log.warning("news_source_failed", source=name, error=str(exc))
            return []

    results = await asyncio.gather(*(_safe(name) for name in sources))
    return [item for batch in results for item in batch]
