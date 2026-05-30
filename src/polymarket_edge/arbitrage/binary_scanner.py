from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from polymarket_edge.config import get_settings
from polymarket_edge.db.models import OrderbookSnapshot, Token


@dataclass(frozen=True)
class BinaryArbitrage:
    market_id: str
    yes_token_id: str
    no_token_id: str
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    long_margin: float
    short_margin: float
    executable_size: float
    estimated_profit: float
    side: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _latest_snapshots(session: Session) -> dict[str, OrderbookSnapshot]:
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


def _depth(levels: list[dict[str, float]]) -> float:
    return sum(float(level.get("size", 0)) for level in levels if level.get("size"))


def _find_yes_no(tokens: list[Token]) -> tuple[Token | None, Token | None]:
    yes = next((token for token in tokens if (token.outcome or "").strip().lower() == "yes"), None)
    no = next((token for token in tokens if (token.outcome or "").strip().lower() == "no"), None)
    return yes, no


def scan_binary_arbitrage(session: Session, fee: float | None = None) -> list[BinaryArbitrage]:
    settings = get_settings()
    fee_val = settings.DEFAULT_FEE if fee is None else float(fee)
    snapshots = _latest_snapshots(session)
    tokens_by_market: dict[str, list[Token]] = {}
    for token in session.execute(select(Token)).scalars():
        tokens_by_market.setdefault(token.market_id, []).append(token)

    arbs: list[BinaryArbitrage] = []
    for market_id, tokens in tokens_by_market.items():
        yes, no = _find_yes_no(tokens)
        if yes is None or no is None:
            continue
        yes_snap = snapshots.get(yes.token_id)
        no_snap = snapshots.get(no.token_id)
        if yes_snap is None or no_snap is None:
            continue
        if yes_snap.best_ask is None or no_snap.best_ask is None or yes_snap.best_bid is None or no_snap.best_bid is None:
            continue
        long_margin = 1.0 - yes_snap.best_ask - no_snap.best_ask - fee_val
        short_margin = yes_snap.best_bid + no_snap.best_bid - 1.0 - fee_val
        if long_margin > 0:
            size = min(_depth(yes_snap.ask_depth), _depth(no_snap.ask_depth))
            arbs.append(
                BinaryArbitrage(
                    market_id=market_id,
                    yes_token_id=yes.token_id,
                    no_token_id=no.token_id,
                    yes_bid=yes_snap.best_bid,
                    yes_ask=yes_snap.best_ask,
                    no_bid=no_snap.best_bid,
                    no_ask=no_snap.best_ask,
                    long_margin=long_margin,
                    short_margin=short_margin,
                    executable_size=size,
                    estimated_profit=size * long_margin,
                    side="LONG",
                )
            )
        if short_margin > 0:
            size = min(_depth(yes_snap.bid_depth), _depth(no_snap.bid_depth))
            arbs.append(
                BinaryArbitrage(
                    market_id=market_id,
                    yes_token_id=yes.token_id,
                    no_token_id=no.token_id,
                    yes_bid=yes_snap.best_bid,
                    yes_ask=yes_snap.best_ask,
                    no_bid=no_snap.best_bid,
                    no_ask=no_snap.best_ask,
                    long_margin=long_margin,
                    short_margin=short_margin,
                    executable_size=size,
                    estimated_profit=size * short_margin,
                    side="SHORT",
                )
            )
    return arbs

