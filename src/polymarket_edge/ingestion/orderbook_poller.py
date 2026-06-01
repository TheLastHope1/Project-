from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from polymarket_edge.clients.clob import CLOBClient, NormalizedOrderbook
from polymarket_edge.config import get_settings
from polymarket_edge.db.models import OrderbookSnapshot, Token
from polymarket_edge.logging import get_logger

log = get_logger(__name__)


@dataclass
class PollSummary:
    tokens_loaded: int = 0
    snapshots_saved: int = 0
    failures: int = 0


def active_token_ids(session: Session, limit: int | None = None) -> list[str]:
    stmt = select(Token.token_id).order_by(desc(Token.updated_at))
    if limit:
        stmt = stmt.limit(limit)
    return [str(row[0]) for row in session.execute(stmt).all()]


def save_orderbook_snapshot(session: Session, book: NormalizedOrderbook) -> OrderbookSnapshot:
    snapshot = OrderbookSnapshot(
        token_id=book.token_id,
        timestamp=book.timestamp or datetime.now(UTC),
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        mid=book.mid,
        spread=book.spread,
        bid_depth=book.bids,
        ask_depth=book.asks,
        raw_json=book.raw_json,
    )
    session.add(snapshot)
    return snapshot


async def poll_orderbooks_once(session: Session, max_tokens: int | None = None) -> PollSummary:
    settings = get_settings()
    token_ids = active_token_ids(session, max_tokens or settings.MAX_TOKENS)
    summary = PollSummary(tokens_loaded=len(token_ids))
    async with CLOBClient() as clob:
        books = await clob.get_many_orderbooks(token_ids, concurrency=10)
    for token_id in token_ids:
        book = books.get(token_id)
        if book is None:
            summary.failures += 1
            continue
        save_orderbook_snapshot(session, book)
        summary.snapshots_saved += 1
    return summary


async def poll_orderbooks_loop(session_factory, interval: int = 30, max_tokens: int | None = None) -> None:
    while True:
        with session_factory() as session:
            summary = await poll_orderbooks_once(session, max_tokens=max_tokens)
            session.commit()
            log.info("orderbooks_polled", **summary.__dict__)
        await asyncio.sleep(interval)

