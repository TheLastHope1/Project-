from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from statistics import mean, median
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from polymarket_edge.db.models import EdgeSnapshot, OrderbookSnapshot


@dataclass(frozen=True)
class BacktestResult:
    trades: int
    total_pnl: float
    mean_pnl: float
    median_pnl: float
    win_rate: float
    max_drawdown: float
    sharpe_like: float
    average_net_edge: float
    average_realized_pnl: float
    edge_to_pnl_correlation: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _nearest_later_snapshot(session: Session, token_id: str, after_ts) -> OrderbookSnapshot | None:
    return session.scalar(
        select(OrderbookSnapshot)
        .where(OrderbookSnapshot.token_id == token_id, OrderbookSnapshot.timestamp >= after_ts)
        .order_by(OrderbookSnapshot.timestamp.asc())
        .limit(1)
    )


def _max_drawdown(values: list[float]) -> float:
    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return max_dd


def run_backtest(session: Session, holding_period_seconds: int = 3600) -> BacktestResult:
    edges = list(
        session.execute(
            select(EdgeSnapshot).where(EdgeSnapshot.action.in_(("BUY", "SELL"))).order_by(EdgeSnapshot.timestamp.asc())
        ).scalars()
    )
    pnls: list[float] = []
    edge_values: list[float] = []
    for edge in edges:
        if edge.ask is None or edge.bid is None:
            continue
        exit_snapshot = _nearest_later_snapshot(
            session,
            edge.token_id,
            edge.timestamp + timedelta(seconds=holding_period_seconds),
        )
        if exit_snapshot is None or exit_snapshot.mid is None:
            continue
        size = max(edge.kelly_size or 0.0, 0.0)
        if size <= 0:
            size = 1.0
        if edge.action == "BUY":
            entry = edge.ask
            pnl = (exit_snapshot.mid - entry) * size
        else:
            entry = edge.bid
            pnl = (entry - exit_snapshot.mid) * size
        pnls.append(float(pnl))
        edge_values.append(float(edge.net_edge or 0.0))

    if not pnls:
        return BacktestResult(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    pnl_arr = np.asarray(pnls, dtype=float)
    edge_arr = np.asarray(edge_values, dtype=float)
    corr = float(np.corrcoef(edge_arr, pnl_arr)[0, 1]) if len(pnls) > 1 and np.std(edge_arr) > 0 and np.std(pnl_arr) > 0 else 0.0
    std = float(np.std(pnl_arr))
    return BacktestResult(
        trades=len(pnls),
        total_pnl=float(sum(pnls)),
        mean_pnl=float(mean(pnls)),
        median_pnl=float(median(pnls)),
        win_rate=float(sum(1 for pnl in pnls if pnl > 0) / len(pnls)),
        max_drawdown=float(_max_drawdown(pnls)),
        sharpe_like=float(mean(pnls) / std) if std > 0 else 0.0,
        average_net_edge=float(mean(edge_values)) if edge_values else 0.0,
        average_realized_pnl=float(mean(pnls)),
        edge_to_pnl_correlation=corr,
    )

