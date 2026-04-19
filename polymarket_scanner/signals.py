"""Live signal detection layered on top of the scanner's price snapshots.

The forfeit-edge scanner only sees a price snapshot every few minutes. News
(team withdraws, scheduling conflict published, UMA proposal hits the chain)
usually moves the market before the scanner alerts. This module watches
price history between scans and flags:

  - price_anomaly : a forfeit-prone market's underdog side jumps >= 20%
                    in one scan interval, or liquidity drops sharply. Usually
                    means someone knows something.
  - stale_open    : the market's scheduled end passed hours ago but it's
                    still taking orders - strongest forfeit tell.

Interface is deliberately simple: feed each scan's market list into
SignalWatcher.observe() and it emits Signal objects into the AppState.

Future signal sources (UMA on-chain, whale trades, tournament scraping)
should expose the same .observe() or .poll() method and plug into the same
AppState sink.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .client import Market
from .scanner import ScanConfig, _H2H_RE
from .state import AppState, Signal

log = logging.getLogger(__name__)


@dataclass
class _MarketHistory:
    last_underdog_price: float
    last_liquidity: float
    last_seen_at: datetime


class PriceAnomalyWatcher:
    """Detects sudden price or liquidity moves on forfeit-prone markets."""

    def __init__(
        self,
        state: AppState,
        cfg: ScanConfig,
        price_move_threshold: float = 0.20,   # 20% relative jump
        liquidity_drop_threshold: float = 0.40,  # 40% drop
        cooldown: timedelta = timedelta(minutes=20),
    ):
        self.state = state
        self.cfg = cfg
        self.price_move_threshold = price_move_threshold
        self.liquidity_drop_threshold = liquidity_drop_threshold
        self.cooldown = cooldown
        self._history: dict[str, _MarketHistory] = {}
        self._last_alerted: dict[str, datetime] = {}

    def _is_forfeit_prone(self, market: Market) -> bool:
        haystack = " ".join(
            s.lower() for s in (market.question, market.category or "", market.event_title or "") if s
        )
        if not any(re.search(rf"\b{re.escape(kw)}\b", haystack)
                   for kw in self.cfg.forfeit_prone_keywords):
            return False
        if not _H2H_RE.search(market.question or "") and not any(
            t.lower() in haystack for t in self.cfg.team_watchlist
        ):
            return False
        return True

    def _recent_cooldown_hit(self, market_id: str, now: datetime) -> bool:
        last = self._last_alerted.get(market_id)
        return last is not None and now - last < self.cooldown

    def observe(self, markets: Iterable[Market]) -> None:
        now = datetime.now(timezone.utc)
        for market in markets:
            if not self._is_forfeit_prone(market):
                continue
            price = market.underdog_price
            if price is None:
                continue

            prev = self._history.get(market.id)
            self._history[market.id] = _MarketHistory(
                last_underdog_price=price,
                last_liquidity=market.liquidity,
                last_seen_at=now,
            )
            if prev is None:
                continue

            if self._recent_cooldown_hit(market.id, now):
                continue

            # Price anomaly: relative change beyond threshold.
            if prev.last_underdog_price > 0:
                rel = (price - prev.last_underdog_price) / prev.last_underdog_price
                if abs(rel) >= self.price_move_threshold:
                    direction = "up" if rel > 0 else "down"
                    self._last_alerted[market.id] = now
                    self.state.add_signal(Signal(
                        kind="price_anomaly",
                        market_id=market.id,
                        question=market.question,
                        url=market.url,
                        detail=(
                            f"underdog price moved {direction} {abs(rel):.0%} "
                            f"({prev.last_underdog_price:.3f} -> {price:.3f})"
                        ),
                        severity="alert" if abs(rel) >= 0.40 else "warn",
                        detected_at=now,
                    ))
                    continue

            # Liquidity drop: often precedes a resolution / market pause.
            if prev.last_liquidity > 0:
                liq_rel = (market.liquidity - prev.last_liquidity) / prev.last_liquidity
                if liq_rel <= -self.liquidity_drop_threshold:
                    self._last_alerted[market.id] = now
                    self.state.add_signal(Signal(
                        kind="liquidity_drop",
                        market_id=market.id,
                        question=market.question,
                        url=market.url,
                        detail=(
                            f"liquidity dropped {abs(liq_rel):.0%} "
                            f"(${prev.last_liquidity:,.0f} -> ${market.liquidity:,.0f})"
                        ),
                        severity="warn",
                        detected_at=now,
                    ))

    def observe_stale(self, markets: Iterable[Market]) -> None:
        """Emit a `stale_open` signal for markets past their end time.

        Complementary to the scanner's own past_end reason - this surfaces the
        tell even when the underdog price is above the edge threshold.
        """
        now = datetime.now(timezone.utc)
        for market in markets:
            if not self._is_forfeit_prone(market):
                continue
            if not market.end_date or not market.accepting_orders:
                continue
            delta = market.end_date - now
            if delta >= timedelta(0) or delta < -self.cfg.stale_grace:
                continue
            if self._recent_cooldown_hit(f"stale:{market.id}", now):
                continue
            self._last_alerted[f"stale:{market.id}"] = now
            self.state.add_signal(Signal(
                kind="stale_open",
                market_id=market.id,
                question=market.question,
                url=market.url,
                detail=(
                    f"scheduled end was {int(-delta.total_seconds() // 60)}m ago "
                    f"but market is still taking orders"
                ),
                severity="alert",
                detected_at=now,
            ))
