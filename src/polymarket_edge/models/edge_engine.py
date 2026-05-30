from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from polymarket_edge.config import Settings
from polymarket_edge.models.costs import total_cost


@dataclass(frozen=True)
class EdgeScore:
    token_id: str
    bid: float | None
    ask: float | None
    p_hat: float
    sigma: float
    total_cost: float
    buy_raw_edge: float
    sell_raw_edge: float
    buy_net_edge: float
    sell_net_edge: float
    side: str
    best_net_edge: float
    kelly_size: float
    action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _kelly_buy(p_hat: float, ask: float) -> float:
    if ask >= 1:
        return 0.0
    return max((p_hat - ask) / (1.0 - ask), 0.0)


def _kelly_sell(p_hat: float, bid: float) -> float:
    if bid <= 0:
        return 0.0
    return max((bid - p_hat) / bid, 0.0)


def score_market(snapshot: Any, p_hat: float, sigma: float, config: Settings, n_markets: int) -> EdgeScore:
    bid = getattr(snapshot, "best_bid", None)
    ask = getattr(snapshot, "best_ask", None)
    spread = getattr(snapshot, "spread", None)
    token_id = str(getattr(snapshot, "token_id", ""))
    if bid is None or ask is None:
        return EdgeScore(token_id, bid, ask, p_hat, sigma, 0.0, 0.0, 0.0, 0.0, 0.0, "NONE", 0.0, 0.0, "NONE")

    cost = total_cost(
        fee=config.DEFAULT_FEE,
        spread=max(0.0, float(spread or ask - bid)),
        latency=config.DEFAULT_LATENCY_COST,
        adverse_selection=config.DEFAULT_ADVERSE_SELECTION_COST,
        z_alpha=config.Z_ALPHA,
        sigma=sigma,
        n=n_markets,
    )
    buy_raw_edge = float(p_hat) - float(ask)
    sell_raw_edge = float(bid) - float(p_hat)
    buy_net_edge = buy_raw_edge - cost
    sell_net_edge = sell_raw_edge - cost
    if buy_net_edge > 0 and buy_net_edge >= sell_net_edge:
        action = "BUY"
        side = "BUY"
        best = buy_net_edge
        kelly_raw = _kelly_buy(p_hat, ask)
    elif sell_net_edge > 0 and sell_net_edge > buy_net_edge:
        action = "SELL"
        side = "SELL"
        best = sell_net_edge
        kelly_raw = _kelly_sell(p_hat, bid)
    else:
        action = "NONE"
        side = "NONE"
        best = max(buy_net_edge, sell_net_edge)
        kelly_raw = 0.0
    kelly_size = min(max(kelly_raw, 0.0) * config.MAX_POSITION_FRACTION, config.MAX_POSITION_FRACTION)
    return EdgeScore(
        token_id=token_id,
        bid=bid,
        ask=ask,
        p_hat=float(p_hat),
        sigma=float(sigma),
        total_cost=cost,
        buy_raw_edge=buy_raw_edge,
        sell_raw_edge=sell_raw_edge,
        buy_net_edge=buy_net_edge,
        sell_net_edge=sell_net_edge,
        side=side,
        best_net_edge=best,
        kelly_size=kelly_size,
        action=action,
    )

