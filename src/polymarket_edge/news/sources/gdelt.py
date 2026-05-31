"""Keyless GDELT 2.1 DOC API source.

GDELT indexes worldwide news in near real time and is fully keyless. The DOC
API ``ArtList`` mode returns recent articles matching a query, sorted newest
first -- ideal for breaking-news sweeps.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

from polymarket_edge.config import Settings
from polymarket_edge.logging import get_logger
from polymarket_edge.news.models import RawNewsItem

log = get_logger(__name__)

_GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
# GDELT requires a non-empty query; this default casts a wide breaking net.
_DEFAULT_QUERY = "(breaking OR election OR war OR crypto OR economy OR ruling)"
# GDELT enforces ~1 request / 5s and answers 429 with a plain-text body.
_RATE_LIMIT_BACKOFF_SECONDS = 6.0
_MAX_ATTEMPTS = 2


async def _fetch_json(params: dict, timeout: float) -> dict | None:
    """GET GDELT with a 429-aware delayed retry. GDELT returns plain text on
    rate-limit, so we must inspect status and content-type explicitly."""
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "polymarket-edge/0.1"}) as client:
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = await client.get(_GDELT_URL, params=params)
            except httpx.HTTPError as exc:
                log.warning("gdelt_request_error", error=str(exc))
                return None
            if resp.status_code == 429:
                if attempt + 1 < _MAX_ATTEMPTS:
                    log.info("gdelt_rate_limited_retrying", wait=_RATE_LIMIT_BACKOFF_SECONDS)
                    await asyncio.sleep(_RATE_LIMIT_BACKOFF_SECONDS)
                    continue
                log.warning("gdelt_rate_limited")
                return None
            if resp.status_code != 200:
                log.warning("gdelt_status_error", status=resp.status_code)
                return None
            try:
                return resp.json()
            except ValueError:
                log.warning("gdelt_non_json_response", head=resp.text[:80])
                return None
    return None


def _parse_seendate(value: str | None) -> datetime | None:
    # GDELT format: "20260531T083000Z"
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


async def fetch(settings: Settings, query_terms: list[str]) -> list[RawNewsItem]:
    if query_terms:
        # OR-join configured terms, quoting multi-word phrases.
        parts = [f'"{t}"' if " " in t else t for t in query_terms]
        query = "(" + " OR ".join(parts) + ")"
    else:
        query = _DEFAULT_QUERY

    timespan_hours = max(1, int(settings.NEWS_LOOKBACK_HOURS))
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": min(250, settings.NEWS_MAX_ITEMS_PER_SOURCE),
        "sort": "DateDesc",
        "timespan": f"{timespan_hours}h",
    }
    data = await _fetch_json(params, timeout=settings.REQUEST_TIMEOUT_SECONDS)

    if not isinstance(data, dict):
        return []
    articles = data.get("articles")
    if not isinstance(articles, list):
        return []

    items: list[RawNewsItem] = []
    for art in articles:
        if not isinstance(art, dict):
            continue
        title = (art.get("title") or "").strip()
        if not title:
            continue
        items.append(
            RawNewsItem(
                source="gdelt",
                title=title,
                url=(art.get("url") or "").strip() or None,
                summary=None,
                source_name=(art.get("domain") or "").strip() or None,
                published_at=_parse_seendate(art.get("seendate")),
                language=(art.get("language") or "").strip().lower() or None,
                raw={"domain": art.get("domain"), "sourcecountry": art.get("sourcecountry")},
            )
        )
    return items
