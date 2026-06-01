"""Fetch live news from enabled sources, dedup, and persist.

Idempotent: re-running within a short window inserts only genuinely new
items (dedup by content hash). Items older than the configured lookback are
dropped unless they carry no timestamp (kept, since some feeds omit dates).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from polymarket_edge.config import Settings, get_settings
from polymarket_edge.db.models import NewsItem
from polymarket_edge.logging import get_logger
from polymarket_edge.news.entities import extract
from polymarket_edge.news.models import RawNewsItem
from polymarket_edge.news.sources import fetch_all

log = get_logger(__name__)


@dataclass
class IngestSummary:
    fetched: int = 0
    inserted: int = 0
    duplicates: int = 0
    stale_skipped: int = 0
    by_source: dict[str, int] = field(default_factory=dict)


def _within_lookback(item: RawNewsItem, cutoff: datetime) -> bool:
    if item.published_at is None:
        return True  # undated feeds: keep, let downstream recency weighting decide
    return item.published_at >= cutoff


def persist_items(session: Session, items: list[RawNewsItem], cutoff: datetime) -> IngestSummary:
    summary = IngestSummary(fetched=len(items))
    # Existing hashes in this batch's id space; also guard intra-batch dups.
    seen_hashes: set[str] = set()
    for item in items:
        summary.by_source[item.source] = summary.by_source.get(item.source, 0) + 1
        if not _within_lookback(item, cutoff):
            summary.stale_skipped += 1
            continue
        digest = item.dedup_hash
        if digest in seen_hashes:
            summary.duplicates += 1
            continue
        seen_hashes.add(digest)
        existing = session.scalar(select(NewsItem.id).where(NewsItem.dedup_hash == digest))
        if existing is not None:
            summary.duplicates += 1
            continue
        ex = extract(item.text)
        session.add(
            NewsItem(
                dedup_hash=digest,
                source=item.source,
                source_name=item.source_name,
                url=item.url,
                title=item.title,
                summary=item.summary,
                language=item.language,
                published_at=item.published_at,
                fetched_at=datetime.now(UTC),
                entities=ex.entities,
                raw_json=item.raw or {},
            )
        )
        summary.inserted += 1
    return summary


async def ingest_news(
    session: Session,
    settings: Settings | None = None,
    query_terms: list[str] | None = None,
) -> IngestSummary:
    settings = settings or get_settings()
    cutoff = datetime.now(UTC) - timedelta(hours=settings.NEWS_LOOKBACK_HOURS)
    items = await fetch_all(settings, query_terms)
    summary = persist_items(session, items, cutoff)
    log.info(
        "news_ingested",
        fetched=summary.fetched,
        inserted=summary.inserted,
        duplicates=summary.duplicates,
        stale_skipped=summary.stale_skipped,
        by_source=summary.by_source,
    )
    return summary
