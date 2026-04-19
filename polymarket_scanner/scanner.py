"""Core scanning logic.

Polymarket's T&Cs resolve forfeited / canceled events as a 50/50 split of the
pot. That means every share pays out $0.50 regardless of which side you hold.
If you can buy the underdog at price P < 0.50, a forfeit resolution yields
profit = (0.50 - P) per share, i.e. edge = (0.50 / P) - 1.

This module identifies markets where:
  1. The implied underdog probability is below `max_underdog_price` (so a
     forfeit split is profitable).
  2. The market looks like it could settle as a forfeit/no-contest:
       - scheduled end time is near or already past while the market is
         still accepting orders (strongest signal - the FaZe/eyeballers case)
       - OR category/tag matches sports where forfeits are common
       - OR the question text mentions teams on a user-configured watchlist.

Signal 1 alone produces a large noisy candidate list. Combining with any of
the signal-2 heuristics cuts the noise to actionable alerts.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

from .client import Market, PolymarketClient

log = logging.getLogger(__name__)

# Head-to-head match pattern: "A vs B", "A v. B", "Will X beat/defeat Y".
# Forfeit-edge only applies to H2H match markets, not outright "will X win
# the whole season" markets.
_H2H_RE = re.compile(
    r"\b(?:vs\.?|v\.)\b|\bbeat\b|\bdefeat\b|\bwin(?:s)?\s+(?:against|over)\b",
    re.IGNORECASE,
)


@dataclass
class ScanConfig:
    # Only flag markets where the underdog trades at or below this price.
    # At P = 0.35 a 50/50 resolution yields ~43% return per share.
    max_underdog_price: float = 0.40

    # Minimum liquidity (USDC) - avoids dead markets where you can't get filled.
    min_liquidity: float = 500.0

    # Minimum 24h volume (USDC) as an additional liveness check.
    min_volume: float = 100.0

    # Event must end within this window (or already have) to be considered
    # "imminent" - i.e. forfeit risk is real rather than theoretical.
    imminent_window: timedelta = timedelta(hours=6)

    # How long past the scheduled end date a market is still flagged. Covers
    # the FaZe/eyeballers pattern: event time passed, market still open.
    stale_grace: timedelta = timedelta(hours=48)

    # Category or event-title substrings likely to produce forfeits. Case
    # insensitive substring match on market.category and market.event_title.
    forfeit_prone_keywords: tuple[str, ...] = (
        "cs2", "cs:go", "counter-strike", "csgo",
        "dota", "league of legends", "valorant", "rocket league",
        "overwatch", "starcraft", "esports",
        "tennis", "boxing", "mma", "ufc",
    )

    # Optional team / entity watchlist - substrings matched against the
    # question text. Useful when you know a team is double-booked.
    team_watchlist: tuple[str, ...] = ()

    # Polling interval between full scans.
    scan_interval: timedelta = timedelta(minutes=2)


@dataclass
class Opportunity:
    market: Market
    underdog_price: float
    underdog_outcome: str
    edge_pct: float
    reasons: list[str]
    detected_at: datetime

    def summary(self) -> str:
        when = self.market.end_date.isoformat() if self.market.end_date else "unknown"
        return (
            f"[{self.edge_pct:+.1%} edge] {self.market.question}\n"
            f"  underdog: {self.underdog_outcome} @ {self.underdog_price:.3f}"
            f"  | liq=${self.market.liquidity:,.0f} vol=${self.market.volume:,.0f}\n"
            f"  ends: {when}\n"
            f"  why: {', '.join(self.reasons)}\n"
            f"  {self.market.url}"
        )


def _classify(market: Market, cfg: ScanConfig, now: datetime) -> list[str]:
    """Return the list of reasons this market is forfeit-prone, or [] if none.

    An alert requires ALL of:
      1. Head-to-head structure (question looks like "A vs B") OR a watchlist
         match. Outright "will X win the season" markets don't forfeit.
      2. A forfeit-prone domain tag (esports / combat-sport keyword) via
         word-boundary match so "mma" doesn't match "Emma" or "Commanders".
      3. A timing signal: event is imminent or already past its end while the
         market is still open. Without this, year-out markets flood the feed.
    """
    haystack = " ".join(
        s.lower() for s in (market.question, market.category or "", market.event_title or "") if s
    )
    question_lc = (market.question or "").lower()

    is_h2h = bool(_H2H_RE.search(market.question or ""))
    watchlist_hits = [t for t in cfg.team_watchlist if t.lower() in question_lc]
    if not is_h2h and not watchlist_hits:
        return []

    domain_reasons: list[str] = []
    for kw in cfg.forfeit_prone_keywords:
        if re.search(rf"\b{re.escape(kw)}\b", haystack):
            domain_reasons.append(f"category:{kw}")
            break
    for team in watchlist_hits:
        domain_reasons.append(f"watchlist:{team}")

    if not domain_reasons:
        return []

    timing_reason = None
    if market.end_date:
        delta = market.end_date - now
        if timedelta(0) <= delta <= cfg.imminent_window:
            timing_reason = f"starts_in:{int(delta.total_seconds() // 60)}m"
        elif -cfg.stale_grace <= delta < timedelta(0):
            # Event time has passed but market is still accepting trades -
            # this is the strongest forfeit/no-show signal.
            timing_reason = f"past_end:{int(-delta.total_seconds() // 60)}m_still_open"

    if not timing_reason:
        return []

    reasons = list(domain_reasons)
    reasons.append(timing_reason)
    if is_h2h:
        reasons.append("h2h")
    return reasons


def evaluate_market(market: Market, cfg: ScanConfig, now: datetime | None = None) -> Opportunity | None:
    """Return an Opportunity if the market clears all thresholds, else None."""
    now = now or datetime.now(timezone.utc)

    if not market.accepting_orders or market.closed:
        return None
    if market.liquidity < cfg.min_liquidity or market.volume < cfg.min_volume:
        return None

    price = market.underdog_price
    if price is None or price <= 0 or price > cfg.max_underdog_price:
        return None

    reasons = _classify(market, cfg, now)
    if not reasons:
        return None

    edge = (0.50 / price) - 1.0
    return Opportunity(
        market=market,
        underdog_price=price,
        underdog_outcome=market.underdog_outcome or "?",
        edge_pct=edge,
        reasons=reasons,
        detected_at=now,
    )


def scan_once(client: PolymarketClient, cfg: ScanConfig) -> list[Opportunity]:
    now = datetime.now(timezone.utc)
    opportunities: list[Opportunity] = []
    for market in client.iter_active_markets():
        opp = evaluate_market(market, cfg, now)
        if opp:
            opportunities.append(opp)
    opportunities.sort(key=lambda o: o.edge_pct, reverse=True)
    return opportunities


def run_forever(
    client: PolymarketClient,
    cfg: ScanConfig,
    on_opportunity: Callable[[Opportunity], None],
    max_iterations: int | None = None,
) -> None:
    """Poll continuously. `on_opportunity` is called once per new alert."""
    seen: dict[str, datetime] = {}
    # Re-alert on the same market after this cooldown (prices move).
    cooldown = timedelta(minutes=30)

    i = 0
    while max_iterations is None or i < max_iterations:
        i += 1
        start = time.monotonic()
        try:
            opps = scan_once(client, cfg)
            log.info("scan #%d: found %d opportunities", i, len(opps))
            now = datetime.now(timezone.utc)
            for opp in opps:
                last = seen.get(opp.market.id)
                if last and now - last < cooldown:
                    continue
                seen[opp.market.id] = now
                on_opportunity(opp)
        except Exception:  # noqa: BLE001 - keep the loop alive across any failure
            log.exception("scan iteration failed")

        elapsed = time.monotonic() - start
        sleep_for = max(5.0, cfg.scan_interval.total_seconds() - elapsed)
        time.sleep(sleep_for)
