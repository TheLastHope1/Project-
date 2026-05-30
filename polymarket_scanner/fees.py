"""Polymarket fee model.

The official taker-fee formula per Polymarket docs is:

    fee = C * r * p * (1 - p)

where C is shares, r is the category fee rate, and p is the trade price.
Makers pay nothing; takers pay the full fee. Fee is denominated in USDC
(same units as price * shares).

This module replaces the old bps haircut in ``scanner._net_edge`` and is the
single source of truth for fee-adjusted EV anywhere else in the codebase
(scanner ranking, paper-trade journal, future execution sizing).

Category fee rates below match Polymarket's published taker-fee schedule. If
the CLOB ``/fee-rate`` endpoint is reachable (see ``client.get_fee_rate``),
prefer the token-specific value via ``resolve_fee_rate`` -- the per-token
endpoint is authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass

# Source: docs.polymarket.com/trading/fees + PDF review breakeven derivation.
# Keys are normalised lowercase. Unknown -> DEFAULT_FEE_RATE.
CATEGORY_FEE_RATES: dict[str, float] = {
    "sports": 0.03,
    "esports": 0.03,
    "tennis": 0.03,
    "mma": 0.03,
    "ufc": 0.03,
    "boxing": 0.03,
    "cricket": 0.03,
    "soccer": 0.03,
    "football": 0.03,
    "basketball": 0.03,
    "baseball": 0.03,
    "hockey": 0.03,
    "golf": 0.03,
    # Common esports game tags Gamma exposes as the market category.
    "cs2": 0.03,
    "cs:go": 0.03,
    "csgo": 0.03,
    "counter-strike": 0.03,
    "dota": 0.03,
    "dota2": 0.03,
    "league of legends": 0.03,
    "lol": 0.03,
    "valorant": 0.03,
    "rocket league": 0.03,
    "overwatch": 0.03,
    "starcraft": 0.03,
    "finance": 0.04,
    "politics": 0.04,
    "mentions": 0.04,
    "tech": 0.04,
    "ai": 0.04,
    "economics": 0.05,
    "culture": 0.05,
    "weather": 0.05,
    "climate": 0.05,
    "other": 0.05,
    "crypto": 0.07,
    "geopolitics": 0.00,
    "elections": 0.04,
}

DEFAULT_FEE_RATE: float = 0.05  # Conservative when category is missing/unknown.


@dataclass(frozen=True)
class FeeQuote:
    """Result of a fee calculation for a single fill."""

    per_share: float       # fee in USDC per share
    total: float           # total fee in USDC for the requested size
    rate: float            # category rate r used
    price: float           # price used
    shares: float          # shares used
    source: str            # "category" | "clob_fee_rate" | "override"


def category_fee_rate(category: str | None) -> float:
    """Return the category taker fee rate. Falls back to ``DEFAULT_FEE_RATE``.

    Polymarket Gamma sometimes returns categories like "CS2", "Tennis", or
    "Politics, US" -- we match on the first token after lowercasing.
    """
    if not category:
        return DEFAULT_FEE_RATE
    norm = category.strip().lower()
    if norm in CATEGORY_FEE_RATES:
        return CATEGORY_FEE_RATES[norm]
    # Try the first space- or comma-separated token (e.g. "Politics, US").
    head = norm.replace(",", " ").split()
    if head and head[0] in CATEGORY_FEE_RATES:
        return CATEGORY_FEE_RATES[head[0]]
    # Match keyword anywhere (covers "CS2 esports", "Tennis (ITF)").
    for kw, rate in CATEGORY_FEE_RATES.items():
        if kw in norm:
            return rate
    return DEFAULT_FEE_RATE


def resolve_fee_rate(
    category: str | None,
    token_fee_rate: float | None = None,
    override: float | None = None,
) -> tuple[float, str]:
    """Pick the best available fee rate.

    Preference: explicit override > CLOB /fee-rate value > category heuristic.
    Returns ``(rate, source)`` so callers (journal, UI) can record provenance.
    """
    if override is not None:
        return float(override), "override"
    if token_fee_rate is not None and token_fee_rate >= 0:
        return float(token_fee_rate), "clob_fee_rate"
    return category_fee_rate(category), "category"


def taker_fee(price: float, shares: float, rate: float) -> FeeQuote:
    """Polymarket's taker fee: ``C * r * p * (1 - p)``.

    ``price`` must be in [0, 1]. Negative or out-of-range inputs are clamped
    to avoid producing negative fees that would inflate apparent edge.
    """
    p = max(0.0, min(1.0, float(price)))
    c = max(0.0, float(shares))
    r = max(0.0, float(rate))
    per_share = r * p * (1.0 - p)
    return FeeQuote(
        per_share=per_share,
        total=per_share * c,
        rate=r,
        price=p,
        shares=c,
        source="",
    )


def net_ev_per_share(
    ask: float,
    rate: float,
    *,
    p_win: float = 0.0,
    p_fifty: float = 1.0,
    p_lose: float = 0.0,
    slippage_per_share: float = 0.0,
) -> float:
    """Expected value per share for a binary outcome bought at ``ask``.

    By default this assumes a guaranteed 50/50 settlement (the canonical
    forfeit/no-show thesis). For non-50/50 hypotheses, pass explicit
    probabilities -- they should sum to ~1.

    Result is in USDC per share. Positive means the trade has positive EV
    after fees and slippage.
    """
    a = max(0.0, min(1.0, float(ask)))
    gross = p_win * (1.0 - a) + p_fifty * (0.5 - a) + p_lose * (0.0 - a)
    fee = rate * a * (1.0 - a)
    return gross - fee - max(0.0, float(slippage_per_share))


def net_ev_pct(
    ask: float,
    rate: float,
    *,
    p_win: float = 0.0,
    p_fifty: float = 1.0,
    p_lose: float = 0.0,
    slippage_per_share: float = 0.0,
) -> float:
    """EV as a fraction of cost basis (ask + fee per share).

    Cost basis is what you actually pay per share, including the taker fee.
    Returns 0 when cost basis is non-positive (defensive).
    """
    a = max(0.0, min(1.0, float(ask)))
    if a <= 0:
        return 0.0
    fee = rate * a * (1.0 - a)
    cost_basis = a + fee
    if cost_basis <= 0:
        return 0.0
    ev = net_ev_per_share(
        ask, rate,
        p_win=p_win, p_fifty=p_fifty, p_lose=p_lose,
        slippage_per_share=slippage_per_share,
    )
    return ev / cost_basis


def breakeven_ask(rate: float, *, payout: float = 0.5) -> float:
    """Solve ``payout - a - r*a*(1-a) = 0`` for the maximum ask ``a`` that
    still yields non-negative EV under a guaranteed ``payout`` outcome.

    Default ``payout=0.5`` models the 50/50 resolution thesis. With ``r=0``
    this collapses to ``a = payout`` as expected.

    Returns 0.0 if no positive root exists (e.g. negative payout).
    """
    r = max(0.0, float(rate))
    pay = float(payout)
    if r == 0:
        return max(0.0, min(1.0, pay))
    # Solve r*a^2 - (r+1)*a + payout = 0 ; pick the lower root in [0,1].
    b = r + 1.0
    disc = b * b - 4.0 * r * pay
    if disc < 0:
        return 0.0
    import math
    root_low = (b - math.sqrt(disc)) / (2.0 * r)
    return max(0.0, min(1.0, root_low))


def depth_weighted_ask(levels: list[tuple[float, float]], target_shares: float) -> tuple[float, float]:
    """VWAP across ask levels for filling ``target_shares``.

    ``levels`` is a list of ``(price, size)`` sorted from best (lowest) ask
    upward. Returns ``(vwap, shares_filled)``. ``shares_filled`` < target
    means the book did not have enough depth.
    """
    if target_shares <= 0 or not levels:
        return (0.0, 0.0)
    remaining = float(target_shares)
    notional = 0.0
    filled = 0.0
    for price, size in levels:
        if price <= 0 or size <= 0:
            continue
        take = min(remaining, float(size))
        notional += take * float(price)
        filled += take
        remaining -= take
        if remaining <= 0:
            break
    if filled <= 0:
        return (0.0, 0.0)
    return (notional / filled, filled)
