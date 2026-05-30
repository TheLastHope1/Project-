from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass


def multiple_testing_penalty(sigma: float, n: int) -> float:
    n_eff = max(1, int(n))
    if n_eff <= 1:
        return 0.0
    return float(sigma) * math.sqrt(2.0 * math.log(n_eff))


def total_cost(
    fee: float,
    spread: float,
    latency: float,
    adverse_selection: float,
    z_alpha: float,
    sigma: float,
    n: int,
) -> float:
    return (
        max(0.0, float(fee))
        + max(0.0, float(spread))
        + max(0.0, float(latency))
        + max(0.0, float(adverse_selection))
        + max(0.0, float(z_alpha)) * max(0.0, float(sigma))
        + multiple_testing_penalty(sigma, n)
    )


@dataclass(frozen=True)
class SlippageResult:
    executable_size: float
    vwap: float | None
    slippage: float | None


def _levels(orderbook_side: Iterable[dict[str, float] | tuple[float, float]]) -> list[tuple[float, float]]:
    levels: list[tuple[float, float]] = []
    for level in orderbook_side:
        if isinstance(level, dict):
            price = float(level.get("price", 0))
            size = float(level.get("size", 0))
        else:
            price = float(level[0])
            size = float(level[1])
        if price > 0 and size > 0:
            levels.append((price, size))
    return levels


def vwap_slippage(
    orderbook_side: Iterable[dict[str, float] | tuple[float, float]],
    target_size: float,
    best_price: float,
    side: str,
) -> SlippageResult:
    remaining = max(0.0, float(target_size))
    if remaining <= 0:
        return SlippageResult(0.0, None, None)
    notional = 0.0
    filled = 0.0
    for price, size in _levels(orderbook_side):
        take = min(remaining, size)
        notional += take * price
        filled += take
        remaining -= take
        if remaining <= 0:
            break
    if filled <= 0:
        return SlippageResult(0.0, None, None)
    vwap = notional / filled
    side_upper = side.upper()
    if side_upper == "BUY":
        slippage = vwap - best_price
    elif side_upper == "SELL":
        slippage = best_price - vwap
    else:
        raise ValueError(f"unknown side: {side}")
    return SlippageResult(filled, vwap, slippage)

