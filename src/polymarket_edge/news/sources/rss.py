"""Keyless RSS source: Google News (top headlines + per-term search).

Google News RSS is the robust, keyless backbone -- it aggregates thousands of
outlets and exposes a search endpoint, so we get both broad breaking-news
coverage and targeted topic queries without an API key.
"""
from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET  # noqa: N817

from dateutil import parser as dtparser

from polymarket_edge.clients.base import APIClient
from polymarket_edge.config import Settings
from polymarket_edge.logging import get_logger
from polymarket_edge.news.models import RawNewsItem, clean_html

log = get_logger(__name__)

_GOOGLE_NEWS_BASE = "https://news.google.com"
_LOCALE = "hl=en-US&gl=US&ceid=US:en"
# Broad buckets that map onto the categories Polymarket runs markets in.
_DEFAULT_TOPICS = ("politics", "world", "crypto", "finance", "technology")


def _parse_pubdate(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = dtparser.parse(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def _parse_feed(xml_text: str) -> list[RawNewsItem]:
    items: list[RawNewsItem] = []
    try:
        root = ET.fromstring(xml_text)  # noqa: S314 -- trusted Google News feed over HTTPS
    except ET.ParseError as exc:
        log.warning("rss_parse_error", error=str(exc))
        return items
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        link = (item.findtext("link") or "").strip() or None
        description = clean_html(item.findtext("description"))
        # Google News descriptions often just echo the title wrapped in HTML.
        if description and description.lower().startswith(title.lower()[:40]):
            description = None
        pub = _parse_pubdate(item.findtext("pubDate"))
        source_el = item.find("source")
        source_name = source_el.text.strip() if source_el is not None and source_el.text else None
        items.append(
            RawNewsItem(
                source="rss",
                title=title,
                url=link,
                summary=description,
                source_name=source_name,
                published_at=pub,
                language="en",
                raw={"feed": "google_news"},
            )
        )
    return items


async def fetch(settings: Settings, query_terms: list[str]) -> list[RawNewsItem]:
    topics = list(query_terms) if query_terms else list(_DEFAULT_TOPICS)
    paths = [f"/rss?{_LOCALE}"]  # top headlines
    paths += [f"/rss/search?q={quote_plus(term)}&{_LOCALE}" for term in topics]

    collected: list[RawNewsItem] = []
    async with APIClient(_GOOGLE_NEWS_BASE) as client:
        for path in paths:
            xml_text = await client.get_text(path)
            if xml_text:
                collected.extend(_parse_feed(xml_text))
            if len(collected) >= settings.NEWS_MAX_ITEMS_PER_SOURCE * 2:
                break
    return collected[: settings.NEWS_MAX_ITEMS_PER_SOURCE * 2]
