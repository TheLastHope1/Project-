from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from polymarket_edge.config import get_settings
from polymarket_edge.db.models import EdgeSnapshot, OrderbookSnapshot, PaperOrder


@dataclass
class PaperTradeSummary:
    edges_considered: int = 0
    orders_created: int = 0
    filled: int = 0


def _latest_books(session: Session) -> dict[str, OrderbookSnapshot]:
    subq = (
        select(OrderbookSnapshot.token_id, func.max(OrderbookSnapshot.timestamp).label("max_ts"))
        .group_by(OrderbookSnapshot.token_id)
        .subquery()
    )
    rows = session.execute(
        select(OrderbookSnapshot)
        .join(subq, (OrderbookSnapshot.token_id == subq.c.token_id) & (OrderbookSnapshot.timestamp == subq.c.max_ts))
    ).scalars()
    return {row.token_id: row for row in rows}


def paper_trade_from_latest_edges(session: Session) -> PaperTradeSummary:
    settings = get_settings()
    books = _latest_books(session)
    edges = list(
        session.execute(
            select(EdgeSnapshot).where(
                EdgeSnapshot.action.in_(("BUY", "SELL")),
                EdgeSnapshot.net_edge > 0,
            )
        ).scalars()
    )
    summary = PaperTradeSummary(edges_considered=len(edges))
    for edge in edges:
        book = books.get(edge.token_id)
        if book is None:
            continue
        if edge.action == "BUY":
            limit_price = book.best_ask
            fill_price = book.best_ask if limit_price is not None and limit_price >= book.best_ask else None
        else:
            limit_price = book.best_bid
            fill_price = book.best_bid if limit_price is not None and limit_price <= book.best_bid else None
        if limit_price is None or limit_price <= 0:
            continue
        size = max(0.0, min(settings.MAX_ORDER_USD / limit_price, (edge.kelly_size or 0.0) * 100.0))
        if size <= 0:
            size = settings.MAX_ORDER_USD / limit_price
        order = PaperOrder(
            market_id=edge.market_id,
            token_id=edge.token_id,
            side=edge.action,
            limit_price=float(limit_price),
            size=float(size),
            edge_score=edge.net_edge,
            status="filled" if fill_price is not None else "open",
            simulated_fill_price=fill_price,
            simulated_pnl=0.0 if fill_price is not None else None,
            raw_json={"edge_snapshot_id": edge.id},
        )
        session.add(order)
        summary.orders_created += 1
        if fill_price is not None:
            summary.filled += 1
    return summary

