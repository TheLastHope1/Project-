from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from polymarket_edge.clients.data_api import DataAPIClient
from polymarket_edge.db.models import Trade


@dataclass
class TradesSummary:
    fetched: int = 0
    saved: int = 0
    skipped: int = 0


async def ingest_trades(session: Session, limit: int = 500) -> TradesSummary:
    summary = TradesSummary()
    async with DataAPIClient() as data_api:
        trades = await data_api.get_trades(limit=limit)
        summary.fetched = len(trades)
        for raw in trades:
            norm = data_api.normalize_trade(raw)
            tx_hash = norm.get("tx_hash")
            if tx_hash and session.scalar(select(Trade).where(Trade.tx_hash == tx_hash)):
                summary.skipped += 1
                continue
            session.add(Trade(**norm))
            summary.saved += 1
    return summary

