from __future__ import annotations

import math
from typing import Any


def market_mid_probability(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    return (float(bid) + float(ask)) / 2.0


def logit(p: float) -> float:
    p = min(1.0 - 1e-12, max(1e-12, float(p)))
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-float(x)))


def confidence_adjusted_probability(p_hat: float, sigma: float, z_alpha: float) -> float:
    return max(0.0, min(1.0, float(p_hat) - float(z_alpha) * max(0.0, float(sigma))))


def baseline_probability(snapshot: Any) -> float | None:
    return market_mid_probability(getattr(snapshot, "best_bid", None), getattr(snapshot, "best_ask", None))

