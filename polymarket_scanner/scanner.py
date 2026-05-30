"""Core scanning logic.

This scanner is built for edge discovery, not blind doc compliance. It looks
for markets where the public/displayed price, executable order-book price,
timing, rule text, and domain context disagree in a potentially profitable
way.

The base thesis is still: if a market resolves 50/50, any share bought below
$0.50 (after fees) is profitable. This module treats that 50/50 outcome as a
*per-market* hypothesis -- the structured rule classifier
(``taxonomy.classify_rules``) returns a class and ``probability_fifty``,
which feed into the expected-value math from ``fees`` so each opportunity
carries its own honest EV instead of a hand-waved haircut.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from .client import Market, OrderBook, PolymarketClient, TopOfBookQuote
from .fees import net_ev_per_share, net_ev_pct, resolve_fee_rate
from .journal import Journal, OpportunitySnapshot, get_default_journal
from .taxonomy import FallbackRuleClass, RuleClassification, classify_rules

log = logging.getLogger(__name__)

_H2H_RE = re.compile(
    r"\b(?:vs\.?|v\.)\b|\bbeat\b|\bdefeat\b|\bwin(?:s)?\s+(?:against|over)\b",
    re.IGNORECASE,
)

# Kept for the legacy rule_text sniff in the opportunity reasons list. The
# real classification work now happens in ``taxonomy.classify_rules``; this
# regex only annotates whether *any* fallback keyword appears at all.
_RULE_EDGE_RE = re.compile(
    r"\b(forfeit|no[-\s]?show|no\s+contest|walkover|withdraw(?:al|n)?|retire(?:ment|d)?|"
    r"cancel(?:led|ed|lation)?|postpone(?:d|ment)?|abandon(?:ed)?|void|unknown|50/50|fifty)\b",
    re.IGNORECASE,
)

# Rule classes that should never enter the opportunity list under strict mode.
_NEVER_TRADE_CLASSES: frozenset[FallbackRuleClass] = frozenset({
    FallbackRuleClass.REFUND_VOID,
    FallbackRuleClass.OTHER_OUTCOME,
    FallbackRuleClass.UNKNOWN_EXPLICIT,
    FallbackRuleClass.TIE_ONLY,
})


@dataclass
class ScanConfig:
    # Final alert threshold. If CLOB pricing is enabled, this is applied to the
    # executable ask. Otherwise it applies to the Gamma screen price.
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

    # Execution sanity. Gamma/outcomePrices are useful as a radar, but the
    # CLOB book is what you can actually lift. /book is preferred over /price
    # because it carries depth, tick, and spread context.
    use_clob_prices: bool = True
    use_book: bool = True
    require_clob_price: bool = False
    max_clob_probes_per_scan: int = 80

    # Pull the per-token taker fee rate from CLOB instead of the category
    # heuristic. Adds one API call per candidate; default off to keep scans
    # cheap. When off, ``fees.category_fee_rate`` is used.
    use_clob_fee_rate: bool = False
    fee_rate_override: float | None = None

    # Paper-trade sizing. The journal records VWAP fills at this notional so
    # later realised-PnL maths is honest. $100 is a reasonable default.
    paper_target_notional_usd: float = 100.0

    # Rule classifier gates. ``min_rule_confidence`` filters out candidates
    # whose rule text didn't match anything diagnostic; ``min_probability_fifty``
    # filters out candidates whose modelled 50/50 probability is too low to be
    # worth journalling.
    min_rule_confidence: float = 0.0
    min_probability_fifty: float = 0.0
    strict_rule_class: bool = False

    # Journal control. Persistence is opt-in: applications that want a
    # paper-trade journal set ``persist_opportunities=True`` explicitly. The
    # library never silently writes to disk, which keeps tests and one-shot
    # scans free of side effects.
    #
    # The journal is duck-typed: ``Journal`` (SQLite) and ``PostgresJournal``
    # share the same public method signatures.
    journal: object | None = field(default=None, repr=False)
    persist_opportunities: bool = False

    # Legacy bps haircuts kept for back-compat with old env files. They no
    # longer drive EV (fees.py owns that math now) but the dashboard still
    # surfaces them so users can compare.
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

    # New (edge-detection upgrades). All optional so legacy callers don't break.
    rule_class: str | None = None
    rule_confidence: float | None = None
    probability_fifty: float | None = None
    rule_matched: list[str] | None = None
    rule_contradicting: list[str] | None = None
    tick_size: float | None = None
    min_order_size: float | None = None
    ask_depth_usd: float | None = None
    target_shares: float | None = None
    vwap_buy: float | None = None
    shares_fillable: float | None = None
    fee_rate: float | None = None
    fee_source: str | None = None
    model_ev_per_share: float | None = None
    model_ev_pct: float | None = None

    def summary(self) -> str:
        when = self.market.end_date.isoformat() if self.market.end_date else "unknown"
        ev = self.model_ev_pct if self.model_ev_pct is not None else (self.net_edge_pct if self.net_edge_pct is not None else self.edge_pct)
        score_bits = f" score={self.score}/100" if self.score else ""
        rule_bits = f" rule={self.rule_class}" if self.rule_class else ""
        source_bits = f" source={self.price_source}"
        if self.best_bid is not None or self.best_ask is not None:
            source_bits += f" bid={self.best_bid if self.best_bid is not None else '—'} ask={self.best_ask if self.best_ask is not None else '—'}"
        return (
            f"[{ev:+.1%} EV{score_bits}{rule_bits}] {self.market.question}\n"
            f"  underdog: {self.underdog_outcome} @ {self.underdog_price:.3f}"
            f"  | screen={self.screen_price if self.screen_price is not None else '—'}{source_bits}\n"
            f"  liq=${self.market.liquidity:,.0f} vol=${self.market.volume:,.0f}\n"
            f"  ends: {when}\n"
            f"  why: {', '.join(self.reasons)}\n"
            f"  {self.market.url}"
        )


def _classify(market: Market, cfg: ScanConfig, now: datetime) -> list[str]:
    """Return reasons this market deserves manual edge review.

    This is the *gate*: does the market look like an h2h sports/esports
    structure at all? Detailed resolution-rules classification happens in
    ``taxonomy.classify_rules`` after this gate passes.
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
    if market.has_clob_tokens:
        reasons.append("clob_tokens")
    else:
        reasons.append("no_clob_tokens")
    return reasons


def _legacy_net_edge_pct(price: float, cfg: ScanConfig) -> float:
    """Back-compat shim for the old bps-haircut model.

    Surfaced as ``Opportunity.net_edge_pct`` so the dashboard can show both
    the legacy and the new model EV side by side. Do not use for ranking --
    use ``model_ev_pct`` instead.
    """
    haircut = price * ((cfg.fee_bps + cfg.slippage_buffer_bps) / 10_000)
    return ((0.50 - haircut) / price) - 1.0


def _score(
    reasons: list[str],
    price: float,
    screen_price: float | None,
    *,
    best_ask: float | None,
    best_bid: float | None,
    model_ev_pct: float,
    rule_class: FallbackRuleClass | None,
    rule_confidence: float,
    probability_fifty: float,
    shares_fillable: float | None,
    target_shares: float | None,
) -> tuple[int, list[str]]:
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
    if model_ev_pct >= 0.20:
        score += 12; why.append("20%+model-ev")
    elif model_ev_pct >= 0.05:
        score += 6; why.append("5%+model-ev")
    elif model_ev_pct < 0:
        score -= 12; why.append("negative-ev")

    # Rule classifier integration. This is where the false-positive reduction
    # actually shows up in the ranking.
    if rule_class is not None:
        rc_label = f"rule:{rule_class.value}"
        if rule_class in (
            FallbackRuleClass.FIFTY_FIFTY_EXPLICIT,
            FallbackRuleClass.WALKOVER_FIFTY_FIFTY,
            FallbackRuleClass.CRICKET_TIE_FIFTY,
        ):
            score += int(round(15 * rule_confidence))
            why.append(rc_label)
        elif rule_class is FallbackRuleClass.CLINCHING_EXCEPTION:
            score += int(round(8 * rule_confidence))
            why.append(rc_label)
        elif rule_class is FallbackRuleClass.ADVANCES_IF_STARTED:
            score -= 6
            why.append(rc_label)
        elif rule_class is FallbackRuleClass.UNSAFE_AMBIGUOUS:
            score -= 10
            why.append(rc_label)
        elif rule_class in _NEVER_TRADE_CLASSES:
            score -= 25
            why.append(rc_label)
        else:
            why.append(rc_label)

    if probability_fifty >= 0.85:
        score += 6; why.append("high-p50")
    elif probability_fifty < 0.40:
        score -= 6; why.append("low-p50")

    # Depth: did the visible book actually have enough size?
    if target_shares is not None and shares_fillable is not None and target_shares > 0:
        ratio = shares_fillable / target_shares
        if ratio >= 1.0:
            score += 6; why.append("full-depth")
        elif ratio >= 0.5:
            score += 2; why.append("partial-depth")
        else:
            score -= 6; why.append("thin-book")

    return max(0, min(100, score)), why


def _book_to_dict(book: OrderBook | None) -> dict[str, Any] | None:
    if book is None:
        return None
    return {
        "best_bid": book.best_bid,
        "best_ask": book.best_ask,
        "spread": book.spread,
        "midpoint": book.midpoint,
        "tick_size": book.tick_size,
        "min_order_size": book.min_order_size,
        "ask_depth_usd": round(book.ask_depth_usd, 4),
        "asks": [(l.price, l.size) for l in book.asks[:10]],
        "bids": [(l.price, l.size) for l in book.bids[:10]],
        "last_trade_price": book.last_trade_price,
        "timestamp": book.timestamp.isoformat() if book.timestamp else None,
    }


def evaluate_market(
    market: Market,
    cfg: ScanConfig,
    now: datetime | None = None,
    *,
    execution_quote: TopOfBookQuote | None = None,
    bid_quote: TopOfBookQuote | None = None,
    book: OrderBook | None = None,
    fee_rate: float | None = None,
    fee_source: str | None = None,
) -> Opportunity | None:
    """Return an Opportunity if the market clears all thresholds, else None.

    ``book`` takes precedence over the legacy ``execution_quote``/``bid_quote``
    pair when both are supplied -- ``/book`` carries depth and tick context
    that the price-only endpoints can't provide.
    """
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

    # Prefer book for executable price + depth context; fall back to quotes.
    if book is not None:
        best_ask = book.best_ask
        best_bid = book.best_bid
        spread = book.spread
        price_source = "clob_book"
    else:
        best_ask = execution_quote.price if execution_quote else None
        best_bid = bid_quote.price if bid_quote else None
        spread = round(best_ask - best_bid, 6) if best_ask is not None and best_bid is not None else None
        price_source = (
            execution_quote.source if execution_quote and execution_quote.price is not None else "gamma_screen"
        )

    if cfg.require_clob_price and best_ask is None:
        return None

    price = best_ask if best_ask is not None else screen_price
    if execution_quote and execution_quote.price is None and book is None:
        reasons.append("clob_price_unavailable")
    if best_ask is not None:
        reasons.append("exec_ask")
    elif not cfg.require_clob_price:
        reasons.append("screen_price_fallback")

    if price <= 0 or price > cfg.max_underdog_price:
        return None

    # Hard profitability floor, independent of the configurable threshold.
    # A 50/50 fallback pays $0.50 per share; buying at >= $0.50 is at best
    # break-even before fees and negative after them. Reject regardless of
    # what the user passed in --max-price so a generous threshold can't
    # produce false-positive "edge".
    if price >= 0.5:
        return None

    # ---- structured rule classification ----
    classification: RuleClassification = classify_rules(
        market.rule_text, outcomes=market.outcomes
    )

    if cfg.strict_rule_class and classification.rule_class in _NEVER_TRADE_CLASSES:
        return None
    if classification.confidence < cfg.min_rule_confidence:
        return None
    if classification.probability_fifty < cfg.min_probability_fifty:
        return None

    reasons.append(f"rule_class:{classification.rule_class.value}")
    if classification.rule_class is FallbackRuleClass.UNSAFE_AMBIGUOUS:
        reasons.append("rule_unsafe_ambiguous")
    if "danger" in classification.notes:
        reasons.append("rules:danger-keyword")

    # ---- fee model ----
    resolved_fee_rate, resolved_fee_source = resolve_fee_rate(
        market.category,
        token_fee_rate=fee_rate,
        override=cfg.fee_rate_override,
    )
    if fee_source:
        resolved_fee_source = fee_source

    # ---- depth-aware VWAP fill simulation ----
    target_shares: float | None = None
    vwap_buy: float | None = None
    shares_fillable: float | None = None
    ask_depth_usd: float | None = None
    tick_size: float | None = None
    min_order_size: float | None = None
    if book is not None:
        ask_depth_usd = book.ask_depth_usd
        tick_size = book.tick_size
        min_order_size = book.min_order_size
        if cfg.paper_target_notional_usd > 0 and price > 0:
            target_shares = cfg.paper_target_notional_usd / price
            vwap_buy, shares_fillable = book.vwap_ask(target_shares)
            if shares_fillable <= 0:
                vwap_buy = None
                shares_fillable = None

    # The fill price the model evaluates against is the depth-weighted VWAP
    # when available, otherwise top-of-book ask, otherwise the screen price.
    eval_price = vwap_buy if (vwap_buy and vwap_buy > 0) else price

    ev_per_share = net_ev_per_share(
        eval_price,
        resolved_fee_rate,
        p_fifty=classification.probability_fifty,
        p_lose=1.0 - classification.probability_fifty,
    )
    ev_pct = net_ev_pct(
        eval_price,
        resolved_fee_rate,
        p_fifty=classification.probability_fifty,
        p_lose=1.0 - classification.probability_fifty,
    )

    gross = (0.50 / price) - 1.0
    legacy_net = _legacy_net_edge_pct(price, cfg)

    score, score_reasons = _score(
        reasons, price, screen_price,
        best_ask=best_ask, best_bid=best_bid,
        model_ev_pct=ev_pct,
        rule_class=classification.rule_class,
        rule_confidence=classification.confidence,
        probability_fifty=classification.probability_fifty,
        shares_fillable=shares_fillable,
        target_shares=target_shares,
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
        net_edge_pct=legacy_net,
        score=score,
        score_reasons=score_reasons,
        rule_class=classification.rule_class.value,
        rule_confidence=classification.confidence,
        probability_fifty=classification.probability_fifty,
        rule_matched=classification.matched,
        rule_contradicting=classification.contradicting,
        tick_size=tick_size,
        min_order_size=min_order_size,
        ask_depth_usd=ask_depth_usd,
        target_shares=target_shares,
        vwap_buy=vwap_buy,
        shares_fillable=shares_fillable,
        fee_rate=resolved_fee_rate,
        fee_source=resolved_fee_source,
        model_ev_per_share=ev_per_share,
        model_ev_pct=ev_pct,
    )


def _persist_opportunity(
    journal: object | None,
    opp: Opportunity,
    *,
    book: OrderBook | None,
    scan_timestamp: datetime,
) -> None:
    if journal is None:
        return
    try:
        snap = OpportunitySnapshot(
            scan_timestamp=scan_timestamp,
            market_id=opp.market.id,
            event_id=str(opp.market.raw.get("eventId") or opp.market.raw.get("event_id") or ""),
            slug=opp.market.slug,
            token_id=opp.underdog_token_id,
            question=opp.market.question,
            category=opp.market.category,
            event_title=opp.market.event_title,
            game_start_time=opp.market.end_date,
            rule_text=opp.market.rule_text,
            rule_class=opp.rule_class,
            rule_confidence=opp.rule_confidence,
            probability_fifty=opp.probability_fifty,
            gamma_screen_price=opp.screen_price,
            best_bid=opp.best_bid,
            best_ask=opp.best_ask,
            spread=opp.spread,
            tick_size=opp.tick_size,
            min_order_size=opp.min_order_size,
            ask_depth_usd=opp.ask_depth_usd,
            target_shares=opp.target_shares,
            vwap_buy=opp.vwap_buy,
            shares_fillable=opp.shares_fillable,
            fee_rate=opp.fee_rate,
            fee_source=opp.fee_source,
            model_ev_per_share=opp.model_ev_per_share,
            model_ev_pct=opp.model_ev_pct,
            underdog_outcome=opp.underdog_outcome,
            liquidity=opp.market.liquidity,
            volume24h=opp.market.volume,
            score=opp.score,
            reasons=list(opp.reasons),
            score_reasons=list(opp.score_reasons or []),
            book_snapshot=_book_to_dict(book),
        )
        journal.record_opportunity(snap)
    except Exception:  # noqa: BLE001 -- journalling must never break the scan
        log.exception("journal write failed for market %s", opp.market.id)


def evaluate_markets(
    markets: Iterable[Market],
    cfg: ScanConfig,
    now: datetime | None = None,
    client: PolymarketClient | None = None,
) -> list[Opportunity]:
    """Evaluate a market snapshot.

    Two-pass design: a cheap Gamma-only pass picks candidates, then an
    expensive CLOB pass enriches them with /book (preferred) or /price.
    """
    now = now or datetime.now(timezone.utc)
    raw_candidates: list[Market] = []
    for market in markets:
        # First pass without CLOB. Screens broadly and avoids book-fetching every
        # active market on every cycle.
        opp = evaluate_market(market, cfg, now)
        if opp is not None:
            raw_candidates.append(market)

    books: dict[str, OrderBook] = {}
    ask_quotes: dict[str, TopOfBookQuote] = {}
    bid_quotes: dict[str, TopOfBookQuote] = {}
    fee_rates: dict[str, float] = {}
    if (cfg.use_clob_prices or cfg.use_book) and client is not None:
        token_ids = [m.underdog_token_id for m in raw_candidates[:cfg.max_clob_probes_per_scan] if m.underdog_token_id]
        if cfg.use_book:
            try:
                books = client.get_books_batch(token_ids)
            except Exception:  # noqa: BLE001
                log.exception("clob /book enrichment failed; falling back to /price")
                books = {}
        # If book lookups didn't return everything, fall back to /price for
        # tokens still missing executable prices.
        missing_for_price = [tid for tid in token_ids if tid not in books and tid]
        if cfg.use_clob_prices and missing_for_price:
            try:
                # Polymarket /price semantics (validated by ``validate_price_side_semantics``):
                #   side=SELL -> best ask (taker buy price)
                #   side=BUY  -> best bid (taker sell price)
                ask_quotes = client.get_best_prices_batch(missing_for_price, side="SELL")
                bid_quotes = client.get_best_prices_batch(missing_for_price, side="BUY")
            except Exception:  # noqa: BLE001
                log.exception("clob /price enrichment failed")
        if cfg.use_clob_fee_rate:
            for tid in token_ids:
                try:
                    rate = client.get_fee_rate(tid)
                    if rate is not None:
                        fee_rates[tid] = rate
                except Exception:  # noqa: BLE001
                    log.debug("clob fee-rate fetch failed for %s", tid, exc_info=True)

    journal = cfg.journal if cfg.journal is not None else (get_default_journal() if cfg.persist_opportunities else None)
    if not cfg.persist_opportunities:
        journal = None

    opportunities: list[Opportunity] = []
    for market in raw_candidates:
        token_id = market.underdog_token_id or ""
        book = books.get(token_id)
        token_fee_rate = fee_rates.get(token_id)
        opp = evaluate_market(
            market,
            cfg,
            now,
            execution_quote=ask_quotes.get(token_id),
            bid_quote=bid_quotes.get(token_id),
            book=book,
            fee_rate=token_fee_rate,
            fee_source="clob_fee_rate" if token_fee_rate is not None else None,
        )
        if opp:
            opportunities.append(opp)
            _persist_opportunity(journal, opp, book=book, scan_timestamp=now)
    opportunities.sort(
        key=lambda o: (
            o.score,
            o.model_ev_pct if o.model_ev_pct is not None else (
                o.net_edge_pct if o.net_edge_pct is not None else o.edge_pct
            ),
        ),
        reverse=True,
    )
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

    ``on_opportunity`` fires once per new alert (deduped by market id + cooldown).
    ``on_scan_complete`` receives the current opportunity list.
    ``on_markets_scanned`` receives the raw market snapshot from the same scan,
    avoiding a second full Gamma crawl inside the web runner.
    """
    seen: dict[str, datetime] = {}
    cooldown = timedelta(minutes=30)
    seen_dedup_cap = 4096

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
            # Bound the seen dict; drop oldest entries past the cap.
            if len(seen) > seen_dedup_cap:
                for mid in sorted(seen, key=lambda k: seen[k])[: len(seen) - seen_dedup_cap]:
                    seen.pop(mid, None)
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
