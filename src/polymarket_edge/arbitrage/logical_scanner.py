"""Structural (logical) arbitrage across threshold-ladder markets.

Polymarket groups related threshold markets under one *event*, e.g. an event
"What price will Bitcoin reach in 2026?" contains sibling markets
"Will BTC reach $80k?", "$90k?", "$100k?". These are logically linked:

    P(X >= $100k) <= P(X >= $90k) <= P(X >= $80k)        (ABOVE ladders)
    P(X <= $80k)  <= P(X <= $90k) <= P(X <= $100k)       (BELOW ladders)

The YES price of a *stronger* condition can never exceed the YES price of a
*weaker* one when both resolve off the same underlying at the same time. When
the live order book violates that ordering, there is a model-free edge:

  * LOCKED  -- a risk-free pair trade: SELL the (overpriced) stronger YES at
               its bid and BUY the (underpriced) weaker YES at its ask. If
               ``strong_bid - weak_ask - fee > 0`` you collect a net credit
               now and the settlement payoff is non-negative in every state
               of the world, so it can never lose.
  * MONOTONICITY -- a softer signal: the mid prices are out of order by more
               than a configured tolerance, but not by enough to lock in.
               Flagged for review, not as risk-free.

Grouping is by ``event_id`` (robust -- it is Polymarket's own grouping), plus
matching resolution direction and end date so the subset implication actually
holds. This is intentionally model-free: no probability estimate is needed,
only the logical ordering of thresholds.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from polymarket_edge.config import get_settings
from polymarket_edge.db.models import Market, OrderbookSnapshot, Token

# Words that signal the resolution direction. "reach"/"hit"/"exceed" are
# ABOVE: the market resolves YES when the underlying gets to at least X.
# Matched on word boundaries (see _ABOVE_RE) so "over" does not match inside
# "Governor" and "hit" does not match inside "Whitman".
_ABOVE_WORDS = (
    "above", "over", "greater than", "at least", "reach", "reaches", "hit",
    "hits", "exceed", "exceeds", "or more", "or higher", "or above",
)
_BELOW_WORDS = (
    "below", "under", "less than", "at most", "beneath", "or less",
    "or lower", "or below", "dip to", "fall to",
)
_ABOVE_SYMBOLS = (">=", "≥")
_BELOW_SYMBOLS = ("<=", "≤")

_ABOVE_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in _ABOVE_WORDS) + r")\b", re.I)
_BELOW_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in _BELOW_WORDS) + r")\b", re.I)

_MULTIPLIER = {"k": 1e3, "m": 1e6, "b": 1e9}
# A number with optional $, thousands separators, decimals, and an *attached*
# k/m/b magnitude suffix. The suffix must immediately follow the digits and not
# be the first letter of a following word, so "$100,000 by 2026" does not read
# the "b" of "by" as billions.
_NUMBER_RE = re.compile(r"(\$)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)([kKmMbB])?(?![A-Za-z0-9])")


@dataclass(frozen=True)
class LogicalArbitrage:
    event_id: str | None
    direction: str            # "ABOVE" | "BELOW"
    arb_type: str             # "LOCKED" | "MONOTONICITY"
    strong_market_id: str
    weak_market_id: str
    strong_threshold: float
    weak_threshold: float
    strong_question: str | None
    weak_question: str | None
    strong_yes_token: str
    weak_yes_token: str
    strong_bid: float | None   # price to SELL the stronger YES
    weak_ask: float | None     # price to BUY the weaker YES
    strong_mid: float | None
    weak_mid: float | None
    fee: float
    margin: float              # LOCKED: strong_bid-weak_ask-fee; else mid gap
    executable_size: float
    estimated_profit: float
    requires_review: bool
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_threshold(question: str | None) -> float | None:
    """Extract the dollar/level threshold from a market question.

    Prefers numbers carrying a ``$`` prefix or a k/m/b magnitude suffix. Bare
    4-digit years (1900-2100 with no ``$``/suffix/decimal) are ignored
    entirely -- "...win the election in 2026?" is not a threshold market, so
    it must return None rather than treating the year as a level.
    """
    if not question:
        return None
    best: float | None = None
    best_rank = -1
    for prefix, digits, suffix in _NUMBER_RE.findall(question):
        try:
            value = float(digits.replace(",", ""))
        except ValueError:
            continue
        if suffix:
            value *= _MULTIPLIER[suffix.lower()]
        has_marker = bool(prefix) or bool(suffix)
        is_yearlike = 1900 <= value <= 2100 and not has_marker and "." not in digits
        if is_yearlike:
            continue  # never treat a bare year as a threshold level
        # $-prefixed or magnitude-suffixed numbers are the most likely level.
        rank = 2 if has_marker else 1
        if rank > best_rank:
            best_rank = rank
            best = value
    return best


def parse_direction(question: str | None) -> str | None:
    """Return "ABOVE", "BELOW", or None for a threshold question.

    Uses word-boundary matching so direction words are not matched inside
    unrelated words (e.g. "over" inside "Governor").
    """
    if not question:
        return None
    # Check BELOW first: "at most"/"or less" are less ambiguous than ABOVE.
    if _BELOW_RE.search(question) or any(sym in question for sym in _BELOW_SYMBOLS):
        return "BELOW"
    if _ABOVE_RE.search(question) or any(sym in question for sym in _ABOVE_SYMBOLS):
        return "ABOVE"
    return None


def _latest_snapshots(session: Session) -> dict[str, OrderbookSnapshot]:
    subq = (
        select(OrderbookSnapshot.token_id, func.max(OrderbookSnapshot.timestamp).label("max_ts"))
        .group_by(OrderbookSnapshot.token_id)
        .subquery()
    )
    rows = session.execute(
        select(OrderbookSnapshot).join(
            subq,
            (OrderbookSnapshot.token_id == subq.c.token_id)
            & (OrderbookSnapshot.timestamp == subq.c.max_ts),
        )
    ).scalars()
    return {row.token_id: row for row in rows}


def _yes_token_by_market(session: Session) -> dict[str, Token]:
    out: dict[str, Token] = {}
    for token in session.execute(select(Token)).scalars():
        if (token.outcome or "").strip().lower() == "yes":
            out[token.market_id] = token
    return out


def _depth(levels: list[dict[str, float]] | None) -> float:
    if not levels:
        return 0.0
    return sum(float(level.get("size", 0) or 0) for level in levels)


def _end_key(market: Market) -> date | None:
    return market.end_date.date() if market.end_date else None


@dataclass
class _Leg:
    market: Market
    threshold: float
    yes_token: str
    snapshot: OrderbookSnapshot


def scan_logical_arbitrage(
    session: Session,
    fee: float | None = None,
    monotonicity_tolerance: float | None = None,
    max_results: int = 100,
) -> list[LogicalArbitrage]:
    """Detect structural arbitrage across threshold-ladder markets.

    ``monotonicity_tolerance`` controls how far mid prices must be out of
    order before a non-lockable violation is reported (defaults to the
    configured ``MAX_SPREAD``). Results are sorted by margin descending.
    """
    settings = get_settings()
    fee_val = settings.DEFAULT_FEE if fee is None else float(fee)
    tol = settings.MAX_SPREAD if monotonicity_tolerance is None else float(monotonicity_tolerance)

    snapshots = _latest_snapshots(session)
    yes_tokens = _yes_token_by_market(session)

    markets = list(
        session.execute(
            select(Market).where(Market.active.is_(True), Market.closed.is_(False))
        ).scalars()
    )

    # Group comparable legs by (event_id, direction, end-date). Same event +
    # same direction + same resolution date is what makes the subset
    # implication valid.
    groups: dict[tuple[str | None, str, date | None], list[_Leg]] = {}
    for market in markets:
        direction = parse_direction(market.question)
        threshold = parse_threshold(market.question)
        if direction is None or threshold is None:
            continue
        token = yes_tokens.get(market.market_id)
        if token is None:
            continue
        snapshot = snapshots.get(token.token_id)
        if snapshot is None:
            continue
        key = (market.event_id, direction, _end_key(market))
        groups.setdefault(key, []).append(
            _Leg(market=market, threshold=threshold, yes_token=token.token_id, snapshot=snapshot)
        )

    results: list[LogicalArbitrage] = []
    for (event_id, direction, _end), legs in groups.items():
        if len(legs) < 2:
            continue
        for i in range(len(legs)):
            for j in range(i + 1, len(legs)):
                a, b = legs[i], legs[j]
                if a.threshold == b.threshold:
                    continue
                # Determine which leg is the *stronger* condition (lower fair
                # YES price). ABOVE: higher threshold is stronger. BELOW:
                # lower threshold is stronger.
                if direction == "ABOVE":
                    strong, weak = (a, b) if a.threshold > b.threshold else (b, a)
                else:  # BELOW
                    strong, weak = (a, b) if a.threshold < b.threshold else (b, a)

                result = _evaluate_pair(event_id, direction, strong, weak, fee_val, tol)
                if result is not None:
                    results.append(result)

    results.sort(key=lambda r: r.margin, reverse=True)
    return results[:max_results]


def _evaluate_pair(
    event_id: str | None,
    direction: str,
    strong: _Leg,
    weak: _Leg,
    fee_val: float,
    tol: float,
) -> LogicalArbitrage | None:
    """Fair ordering: price(strong YES) <= price(weak YES).

    LOCKED arb: SELL strong YES @ its bid, BUY weak YES @ its ask, when
    ``strong_bid - weak_ask - fee > 0``.
    """
    strong_bid = strong.snapshot.best_bid
    weak_ask = weak.snapshot.best_ask
    strong_mid = strong.snapshot.mid
    weak_mid = weak.snapshot.mid

    locked_margin = None
    if strong_bid is not None and weak_ask is not None:
        locked_margin = float(strong_bid) - float(weak_ask) - fee_val

    if locked_margin is not None and locked_margin > 0:
        size = min(_depth(strong.snapshot.bid_depth), _depth(weak.snapshot.ask_depth))
        return LogicalArbitrage(
            event_id=event_id,
            direction=direction,
            arb_type="LOCKED",
            strong_market_id=strong.market.market_id,
            weak_market_id=weak.market.market_id,
            strong_threshold=strong.threshold,
            weak_threshold=weak.threshold,
            strong_question=strong.market.question,
            weak_question=weak.market.question,
            strong_yes_token=strong.yes_token,
            weak_yes_token=weak.yes_token,
            strong_bid=strong_bid,
            weak_ask=weak_ask,
            strong_mid=strong_mid,
            weak_mid=weak_mid,
            fee=fee_val,
            margin=locked_margin,
            executable_size=size,
            estimated_profit=size * locked_margin,
            requires_review=False,
            confidence=0.9,
            reason=(
                f"stronger condition (>= {strong.threshold:g}) YES bid {strong_bid:.3f} "
                f"exceeds weaker condition (>= {weak.threshold:g}) YES ask {weak_ask:.3f}; "
                "sell strong / buy weak locks a credit with non-negative settlement"
            ),
        )

    # Softer monotonicity violation on mids (not risk-free).
    if strong_mid is not None and weak_mid is not None:
        mid_gap = float(strong_mid) - float(weak_mid)
        if mid_gap > tol:
            return LogicalArbitrage(
                event_id=event_id,
                direction=direction,
                arb_type="MONOTONICITY",
                strong_market_id=strong.market.market_id,
                weak_market_id=weak.market.market_id,
                strong_threshold=strong.threshold,
                weak_threshold=weak.threshold,
                strong_question=strong.market.question,
                weak_question=weak.market.question,
                strong_yes_token=strong.yes_token,
                weak_yes_token=weak.yes_token,
                strong_bid=strong_bid,
                weak_ask=weak_ask,
                strong_mid=strong_mid,
                weak_mid=weak_mid,
                fee=fee_val,
                margin=mid_gap,
                executable_size=0.0,
                estimated_profit=0.0,
                requires_review=True,
                confidence=0.5,
                reason=(
                    f"stronger condition mid {strong_mid:.3f} exceeds weaker condition "
                    f"mid {weak_mid:.3f} by {mid_gap:.3f} (> tolerance {tol:.3f}); "
                    "non-monotonic curve, review for entry"
                ),
            )
    return None
