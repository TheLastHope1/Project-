"""Thread-safe in-memory app state shared between the scanner thread and
the FastAPI request handlers."""
from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Deque

from .scanner import Opportunity

log = logging.getLogger(__name__)


@dataclass
class Signal:
    kind: str              # "price_anomaly", "uma_propose", "whale_trade", ...
    market_id: str
    question: str
    url: str
    detail: str
    severity: str          # "info" | "warn" | "alert"
    detected_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "detected_at": self.detected_at.isoformat()}


@dataclass
class ScannerStats:
    running: bool = False
    started_at: datetime | None = None
    last_scan_at: datetime | None = None
    total_scans: int = 0
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_scan_at": self.last_scan_at.isoformat() if self.last_scan_at else None,
            "total_scans": self.total_scans,
            "last_error": self.last_error,
        }


def _opportunity_to_dict(opp: Opportunity) -> dict[str, Any]:
    m = opp.market
    return {
        "market_id": m.id,
        "question": m.question,
        "slug": m.slug,
        "url": m.url,
        "underdog_outcome": opp.underdog_outcome,
        "underdog_price": opp.underdog_price,
        "screen_price": opp.screen_price,
        "price_source": opp.price_source,
        "underdog_token_id": opp.underdog_token_id,
        "best_ask": opp.best_ask,
        "best_bid": opp.best_bid,
        "spread": opp.spread,
        "edge_pct": opp.edge_pct,
        "net_edge_pct": opp.net_edge_pct,
        "score": opp.score,
        "score_reasons": opp.score_reasons or [],
        "reasons": opp.reasons,
        "liquidity": m.liquidity,
        "volume": m.volume,
        "end_date": m.end_date.isoformat() if m.end_date else None,
        "category": m.category,
        "event_title": m.event_title,
        "detected_at": opp.detected_at.isoformat(),
    }


class AppState:
    """Single source of truth for the web UI. All mutations take the lock."""

    def __init__(self, max_signals: int = 200, max_logs: int = 2000):
        self._lock = threading.Lock()
        self._opportunities: dict[str, Opportunity] = {}
        self._signals: Deque[Signal] = deque(maxlen=max_signals)
        self._logs: Deque[str] = deque(maxlen=max_logs)
        self._stats = ScannerStats()

    # ----- scanner side -----

    def set_opportunities(self, opps: list[Opportunity]) -> None:
        with self._lock:
            self._opportunities = {o.market.id: o for o in opps}
            self._stats.last_scan_at = datetime.now(timezone.utc)
            self._stats.total_scans += 1

    def add_signal(self, signal: Signal) -> None:
        with self._lock:
            self._signals.appendleft(signal)

    def append_log(self, line: str) -> None:
        with self._lock:
            self._logs.append(line)

    def mark_started(self) -> None:
        with self._lock:
            self._stats.running = True
            self._stats.started_at = datetime.now(timezone.utc)
            self._stats.last_error = None

    def mark_stopped(self, error: str | None = None) -> None:
        with self._lock:
            self._stats.running = False
            if error:
                self._stats.last_error = error

    # ----- web side (read-only snapshots) -----

    def snapshot_opportunities(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = [_opportunity_to_dict(o) for o in self._opportunities.values()]
        rows.sort(key=lambda r: (r.get("score") or 0, r.get("net_edge_pct") or r["edge_pct"]), reverse=True)
        return rows

    def snapshot_signals(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return [s.to_dict() for s in list(self._signals)[:limit]]

    def snapshot_logs(self, limit: int = 500) -> list[str]:
        with self._lock:
            return list(self._logs)[-limit:]

    def snapshot_stats(self) -> dict[str, Any]:
        with self._lock:
            stats = self._stats.to_dict()
            stats["opportunity_count"] = len(self._opportunities)
            stats["signal_count"] = len(self._signals)
            return stats


class StateLogHandler(logging.Handler):
    """Fan logging records out to AppState so the web UI can show them."""

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.state.append_log(self.format(record))
        except Exception:  # noqa: BLE001
            pass
