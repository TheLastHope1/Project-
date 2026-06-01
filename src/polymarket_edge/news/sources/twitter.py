"""X / Twitter recent-search source (optional, key-gated).

Activates only when ``X_BEARER_TOKEN`` is set. Uses the v2 recent-search
endpoint, which surfaces the fastest breaking signals. The bearer token is
sent in the Authorization header only.
"""
from __future__ import annotations

from datetime import UTC, datetime

from dateutil import parser as dtparser

from polymarket_edge.clients.base import APIClient
from polymarket_edge.config import Settings
from polymarket_edge.logging import get_logger
from polymarket_edge.news.models import RawNewsItem

log = get_logger(__name__)

_X_BASE = "https://api.twitter.com"
_DEFAULT_QUERY = "(breaking OR breaking news) -is:retweet lang:en"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = dtparser.parse(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


async def fetch(settings: Settings, query_terms: list[str]) -> list[RawNewsItem]:
    if not settings.X_BEARER_TOKEN:
        return []
    if query_terms:
        query = "(" + " OR ".join(query_terms) + ") -is:retweet lang:en"
    else:
        query = _DEFAULT_QUERY

    headers = {"Authorization": f"Bearer {settings.X_BEARER_TOKEN}"}
    params = {
        "query": query,
        "max_results": str(min(100, max(10, settings.NEWS_MAX_ITEMS_PER_SOURCE))),
        "tweet.fields": "created_at,lang,public_metrics",
    }
    async with APIClient(_X_BASE) as client:
        data = await client.get_json("/2/tweets/search/recent", params=params, headers=headers)

    if not isinstance(data, dict):
        return []
    tweets = data.get("data")
    if not isinstance(tweets, list):
        return []

    items: list[RawNewsItem] = []
    for tweet in tweets:
        if not isinstance(tweet, dict):
            continue
        text = (tweet.get("text") or "").strip()
        if not text:
            continue
        tweet_id = tweet.get("id")
        url = f"https://x.com/i/web/status/{tweet_id}" if tweet_id else None
        items.append(
            RawNewsItem(
                source="twitter",
                title=text[:280],
                url=url,
                summary=None,
                source_name="x.com",
                published_at=_parse_dt(tweet.get("created_at")),
                language=(tweet.get("lang") or "en"),
                raw={"public_metrics": tweet.get("public_metrics")},
            )
        )
    return items
