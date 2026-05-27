"""Core scanning logic.

This scanner is built for edge discovery, not blind doc compliance. It looks for
markets where the public/displayed price, executable order-book price, timing,
rule text, and domain context disagree in a potentially profitable way.

The base thesis is still the same: if a market resolves to a split / Unknown /
50-50 style outcome, any share bought below $0.50 can be profitable. But the
code treats that as a hypothesis to validate per market, not as a universal rule.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

from .client import Market, PolymarketClient, TopOfBookQuote

log = logging.getLogger(__name__)

_H2H_RE = re.compile(
    r"\b(?:vs\.?|v\.)\b|\bbeat\b|\bdefeat\b|\bwin(?:s)?\s+(?:against|over)\b",
    re.IGNORECASE,
)

_RULE_EDGE_RE = re.compile(
    r"\b(forfeit|no[-\s]?show|no\s+contest|walkover|withdraw(?:al|n)?|retire(?:ment|d)?|"
    r"cancel(?:led|ed|lation)?|postpone(?:d|ment)?|abandon(?:ed)?|void|unknown|50/50|fifty)\b",
    re.IGNORECASE,
)

_RULE_DANGER_RE = re.compile(
    r"\b(refund|voided|market\s+will\s+be\s+cancel(?:led|ed)|all\s+bets\s+void|"
    r"not\s+resolve\s+50/50)\b",
    re.IGNORECASE,
)


@dataclass
class ScanConfig:
    # Final alert threshold. If CLOB probing is enabled, this is applied to the
    # executable BUY price. Otherwise it applies to the Gamma screen price.
    max_underdog_price: float = 0.40

    # Broad first-pass screen. Keep this near 0.49 to catch display/orderbook
    # mismatches, then tighten after executable-price enrichment.
    max_screen_price: float = 0.49

    min_liquidity: float = 500.0
    min_volume: float = 100.0
    imminent_window: timedelta = timedelta(hours=6)
    stale_grace: timedelta = timedelta(hours=48)

    forfeit_prone_keywords: tuple[str, ...] = (
        "cs2", "cs:go", "counter-strike", "csgo",
        "dota", "league of legends", "valorant", "rocket league",
        "overwatch", "starcraft", "esports",
        "tennis", "boxing", "mma", "ufc",
    )
    team_watchlist: tuple[str, ...] = ()
    scan_interval: timedelta = timedelta(minutes=2)

    # Execution sanity. Gamma/outcomePrices are useful as a radar, but the CLOB
    # BUY price is what you can actually lift. Keep fallback on while researching;
    # turn require_clob_price on once deployment is stable.
    use_clob_prices: bool = True
    require_clob_price: bool = False
    max_clob_probes_per_scan: int = 80

    # Conservative manual buffers. fee_bps is intentionally user-set because
    # fee-enabled categories change; slippage_buffer_bps lets you discount edge.
    fee_bps: float = 0.0
    slippage_buffer_bps: float = 0.0


@dataclass
class Opportunity:
    market: Market
    underdog_price: float
    underdog_outcome: str
    edge_pct: float
    reasons: list[str]
    detected_at: datetime
    screen_price: float | None = None
    price_source: str = "gamma"
    underdog_token_id: str | None = None
    best_ask: float | None = None
    best_bid: float | None = None
    spread: float | None = None
    net_edge_pct: float | None = None
    score: int = 0
    score_reasons: list[str] | None = None

    def summary(self) -> str:
        when = self.market.end_date.isoformat() if self.market.end_date else "unknown"
        net = self.net_edge_pct if self.net_edge_pct is not None else self.edge_pct
        score_bits = f" score={self.score}/100" if self.score else ""
        source_bits = f" source={self.price_source}"
        if self.best_bid is not None or self.best_ask is not None:
            source_bits += f" bid={self.best_bid if self.best_bid is not None else '—'} ask={self.best_ask if self.best_ask is not None else '—'}"
        return (
            f"[{net:+.1%} net edge{score_bits}] {self.market.question}\n"
            f"  underdog: {self.underdog_outcome} @ {self.underdog_price:.3f}"
            f"  | screen={self.screen_price if self.screen_price is not None else '—'}{source_bits}\n"
            f"  liq=${self.market.liquidity:,.0f} vol=${self.market.volume:,.0f}\n"
            f"  ends: {when}\n"
            f"  why: {', '.join(self.reasons)}\n"
            f"  {self.market.url}"
        )


def _classify(market: Market, cfg: ScanConfig, now: datetime) -> list[str]:
    """Return reasons this market deserves manual edge review."""
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
            timing_reason = f"past_end:{int(-delta.total_seconds() // 60)}m_still_open"

    if not timing_reason:
        return []

    reasons = list(domain_reasons)
    reasons.append(timing_reason)
    if is_h2h:
        reasons.append("h2h")

    rule_text = market.rule_text
    if _RULE_EDGE_RE.search(rule_text):
        reasons.append("rules:edge-keyword")
    if _RULE_DANGER_RE.search(rule_text):
        reasons.append("rules:danger-keyword")
    if market.has_clob_tokens:
        reasons.append("clob_tokens")
    else:
        reasons.append("no_clob_tokens")
    return reasons


def _net_edge(price: float, cfg: ScanConfig) -> float:
    # Conservative simple model: treat fee/slippage as a haircut against payout.
    haircut = price * ((cfg.fee_bps + cfg.slippage_buffer_bps) / 10_000)
    return ((0.50 - haircut) / price) - 1.0


def _score(reasons: list[str], price: float, screen_price: float | None, *, best_ask: float | None,
           best_bid: float | None, net_edge_pct: float, cfg: ScanConfig) -> tuple[int, list[str]]:
    score = 0
    why: list[str] = []

    if any(r.startswith("past_end:") for r in reasons):
        score += 30; why.append("stale-open")
    if any(r.startswith("starts_in:") for r in reasons):
        score += 12; why.append("imminent")
    if any(r.startswith("watchlist:") for r in reasons):
        score += 12; why.append("watchlist")
    if any(r.startswith("category:") for r in reasons):
        score += 8; why.append("forfeit-domain")
    if "rules:edge-keyword" in reasons:
        score += 10; why.append("rule-keyword")
    if "rules:danger-keyword" in reasons:
        score -= 12; why.append("rule-danger")
    if "h2h" in reasons:
        score += 5; why.append("h2h")
    if "clob_tokens" in reasons:
        score += 4; why.append("clob-tokenized")
    if best_ask is not None:
        score += 12; why.append("executable-ask")
    if best_bid is not None and best_ask is not None and best_ask > best_bid:
        spread = best_ask - best_bid
        if spread <= 0.03:
            score += 8; why.append("tight-spread")
        elif spread <= 0.08:
            score += 3; why.append("ok-spread")
        else:
            score -= 8; why.append("wide-spread")
    if screen_price is not None and best_ask is not None and best_ask < screen_price:
        score += 8; why.append("ask-better-than-screen")
    if price <= 0.25:
        score += 8; why.append("cheap-underdog")
    elif price <= 0.35:
        score += 4; why.append("sub-35c")
    if net_edge_pct >= 1.0:
        score += 8; why.append("100%+net-edge")
    elif net_edge_pct >= 0.35:
        score += 4; why.append("35%+net-edge")

    return max(0, min(100, score)), why


def evaluate_market(
    market: Market,
    cfg: ScanConfig,
    now: datetime | None = None,
    *,
    execution_quote: TopOfBookQuote | None = None,
    bid_quote: TopOfBookQuote | None = None,
) -> Opportunity | None:
    """Return an Opportunity if the market clears all thresholds, else None."""
    now = now or datetime.now(timezone.utc)

    if not market.accepting_orders or market.closed:
        return None
    if market.liquidity < cfg.min_liquidity or market.volume < cfg.min_volume:
        return None

    screen_price = market.underdog_price
    if screen_price is None or screen_price <= 0 or screen_price > cfg.max_screen_price:
        return None

    reasons = _classify(market, cfg, now)
    if not reasons:
        return None

    best_ask = execution_quote.price if execution_quote else None
    best_bid = bid_quote.price if bid_quote else None
    spread = round(best_ask - best_bid, 6) if best_ask is not None and best_bid is not None else None

    if cfg.require_clob_price and best_ask is None:
        return None

    price = best_ask if best_ask is not None else screen_price
    price_source = execution_quote.source if execution_quote and execution_quote.price is not None else "gamma_screen"
    if execution_quote and execution_quote.price is None:
        reasons.append("clob_price_unavailable")
    if best_ask is not None:
        reasons.append("exec_ask")
    elif not cfg.require_clob_price:
        reasons.append("screen_price_fallback")

    if price <= 0 or price > cfg.max_underdog_price:
        return None

    gross = (0.50 / price) - 1.0
    net = _net_edge(price, cfg)
    score, score_reasons = _score(
        reasons, price, screen_price, best_ask=best_ask, best_bid=best_bid,
        net_edge_pct=net, cfg=cfg,
    )

    return Opportunity(
        market=market,
        underdog_price=price,
        underdog_outcome=market.underdog_outcome or "?",
        edge_pct=gross,
        reasons=reasons,
        detected_at=now,
        screen_price=screen_price,
        price_source=price_source,
        underdog_token_id=market.underdog_token_id,
        best_ask=best_ask,
        best_bid=best_bid,
        spread=spread,
        net_edge_pct=net,
        score=score,
        score_reasons=score_reasons,
    )


def evaluate_markets(
    markets: Iterable[Market],
    cfg: ScanConfig,
    now: datetime | None = None,
    client: PolymarketClient | None = None,
) -> list[Opportunity]:
    """Evaluate a market snapshot, optionally enriching candidates with CLOB prices."""
    now = now or datetime.now(timezone.utc)
    raw_candidates: list[Market] = []
    for market in markets:
        # First pass without CLOB. This screens broadly and avoids probing every
        # Polymarket market every cycle.
        opp = evaluate_market(market, cfg, now)
        if opp is not None:
            raw_candidates.append(market)

    ask_quotes: dict[str, TopOfBookQuote] = {}
    bid_quotes: dict[str, TopOfBookQuote] = {}
    if cfg.use_clob_prices and client is not None:
        token_ids = [m.underdog_token_id for m in raw_candidates[:cfg.max_clob_probes_per_scan] if m.underdog_token_id]
        try:
            ask_quotes = client.get_best_prices_batch(token_ids, side="BUY")
            bid_quotes = client.get_best_prices_batch(token_ids, side="SELL")
        except Exception:  # noqa: BLE001 - CLOB probing is a ranking enhancer, not a scanner killer
            log.exception("clob price enrichment failed")

    opportunities: list[Opportunity] = []
    for market in raw_candidates:
        token_id = market.underdog_token_id
        opp = evaluate_market(
            market,
            cfg,
            now,
            execution_quote=ask_quotes.get(token_id or ""),
            bid_quote=bid_quotes.get(token_id or ""),
        )
        if opp:
            opportunities.append(opp)
    opportunities.sort(key=lambda o: (o.score, o.net_edge_pct if o.net_edge_pct is not None else o.edge_pct), reverse=True)
    return opportunities


def scan_once(client: PolymarketClient, cfg: ScanConfig) -> list[Opportunity]:
    now = datetime.now(timezone.utc)
    markets = list(client.iter_active_markets())
    return evaluate_markets(markets, cfg, now, client=client)


def run_forever(
    client: PolymarketClient,
    cfg: ScanConfig,
    on_opportunity: Callable[[Opportunity], None],
    max_iterations: int | None = None,
    stop_event: threading.Event | None = None,
    on_scan_complete: Callable[[list[Opportunity]], None] | None = None,
    on_markets_scanned: Callable[[list[Market]], None] | None = None,
) -> None:
    """Poll continuously.

    `on_opportunity` fires once per new alert (deduped by market id + cooldown).
    `on_scan_complete` receives the current opportunity list.
    `on_markets_scanned` receives the raw market snapshot from the same scan,
    avoiding a second full Gamma crawl inside the web runner.
    """
    seen: dict[str, datetime] = {}
    cooldown = timedelta(minutes=30)

    i = 0
    while max_iterations is None or i < max_iterations:
        if stop_event is not None and stop_event.is_set():
            return
        i += 1
        start = time.monotonic()
        try:
            now = datetime.now(timezone.utc)
            markets = list(client.iter_active_markets())
            if on_markets_scanned is not None:
                on_markets_scanned(markets)
            opps = evaluate_markets(markets, cfg, now, client=client)
            log.info("scan #%d: markets=%d opportunities=%d", i, len(markets), len(opps))
            if on_scan_complete is not None:
                on_scan_complete(opps)
            alert_now = datetime.now(timezone.utc)
            for opp in opps:
                last = seen.get(opp.market.id)
                if last and alert_now - last < cooldown:
                    continue
                seen[opp.market.id] = alert_now
                on_opportunity(opp)
        except Exception:  # noqa: BLE001 - keep the loop alive across any failure
            log.exception("scan iteration failed")

        if max_iterations is not None and i >= max_iterations:
            break

        elapsed = time.monotonic() - start
        sleep_for = max(5.0, cfg.scan_interval.total_seconds() - elapsed)
        if stop_event is not None:
            if stop_event.wait(sleep_for):
                return
        else:
            time.sleep(sleep_for)
