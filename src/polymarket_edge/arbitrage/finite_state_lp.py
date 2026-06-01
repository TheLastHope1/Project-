from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from scipy.optimize import linprog


@dataclass(frozen=True)
class LPResult:
    success: bool
    arbitrage_exists: bool
    worst_case_profit: float
    x: list[float]
    x_plus: list[float]
    x_minus: list[float]
    solver_status: int
    solver_message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def finite_state_arbitrage_lp(
    V: np.ndarray,
    ask: np.ndarray,
    bid: np.ndarray,
    max_exposure: float = 1.0,
) -> LPResult:
    V = np.asarray(V, dtype=float)
    ask = np.asarray(ask, dtype=float)
    bid = np.asarray(bid, dtype=float)
    states, contracts = V.shape
    # Variables: x_plus[contracts], x_minus[contracts], z
    n_vars = contracts * 2 + 1
    z_idx = n_vars - 1
    c = np.zeros(n_vars)
    c[z_idx] = -1.0

    a_ub: list[np.ndarray] = []
    b_ub: list[float] = []
    cost_plus = ask
    cost_minus = -bid
    for omega in range(states):
        row = np.zeros(n_vars)
        # Convert payoff - cost >= z to -payoff + cost + z <= 0.
        row[:contracts] = -(V[omega] - cost_plus)
        row[contracts : 2 * contracts] = -(-V[omega] - cost_minus)
        row[z_idx] = 1.0
        a_ub.append(row)
        b_ub.append(0.0)

    exposure = np.zeros(n_vars)
    exposure[: 2 * contracts] = 1.0
    a_ub.append(exposure)
    b_ub.append(float(max_exposure))

    bounds = [(0, None)] * (2 * contracts) + [(None, None)]
    result = linprog(c, A_ub=np.asarray(a_ub), b_ub=np.asarray(b_ub), bounds=bounds, method="highs")
    if not result.success:
        return LPResult(False, False, 0.0, [], [], [], int(result.status), str(result.message))
    values = result.x
    x_plus = values[:contracts]
    x_minus = values[contracts : 2 * contracts]
    x = x_plus - x_minus
    worst_case_profit = float(values[z_idx])
    return LPResult(
        success=True,
        arbitrage_exists=worst_case_profit > 1e-9,
        worst_case_profit=worst_case_profit,
        x=x.tolist(),
        x_plus=x_plus.tolist(),
        x_minus=x_minus.tolist(),
        solver_status=int(result.status),
        solver_message=str(result.message),
    )

