from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from polymarket_edge.db.models import Market

_ABOVE_RE = re.compile(r"\b(?:above|over|greater than|at least)\s+\$?([0-9][0-9,]*(?:\.[0-9]+)?)", re.I)


@dataclass(frozen=True)
class LogicalCandidate:
    market_A: str
    market_B: str
    relation: str
    margin: float
    requires_review: bool
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _threshold(question: str | None) -> float | None:
    if not question:
        return None
    match = _ABOVE_RE.search(question)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def scan_logical_arbitrage(session: Session) -> list[LogicalCandidate]:
    markets = list(session.execute(select(Market).where(Market.active.is_(True), Market.closed.is_(False))).scalars())
    candidates: list[LogicalCandidate] = []
    for idx, market_a in enumerate(markets):
        a_threshold = _threshold(market_a.question)
        if a_threshold is None:
            continue
        for market_b in markets[idx + 1 :]:
            b_threshold = _threshold(market_b.question)
            if b_threshold is None or market_a.market_id == market_b.market_id:
                continue
            if a_threshold > b_threshold:
                candidates.append(
                    LogicalCandidate(
                        market_A=market_a.market_id,
                        market_B=market_b.market_id,
                        relation="A subset B",
                        margin=0.0,
                        requires_review=True,
                        confidence=0.55,
                        reason="higher threshold appears to imply lower threshold; price check requires review",
                    )
                )
            elif b_threshold > a_threshold:
                candidates.append(
                    LogicalCandidate(
                        market_A=market_b.market_id,
                        market_B=market_a.market_id,
                        relation="A subset B",
                        margin=0.0,
                        requires_review=True,
                        confidence=0.55,
                        reason="higher threshold appears to imply lower threshold; price check requires review",
                    )
                )
    return candidates[:100]

