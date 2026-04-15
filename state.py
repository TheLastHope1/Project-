"""
Thread-safe shared state container used by the bot (writer) and the
dashboard (reader + control writer). Single module-level instance
keeps things simple - we don't need to pass it around.
"""
import logging
import threading
import time
from collections import deque
from typing import Any, Optional


class BotState:
    """Thread-safe state shared between the trading loop and the dashboard."""

    def __init__(self):
        self._lock = threading.Lock()

        # Control flags (dashboard -> bot)
        self.paused: bool = False
        self.shutdown_requested: bool = False
        self.cancel_all_requested: bool = False
        self.dry_run_override: Optional[bool] = None  # None = use current mode

        # Mode & lifecycle
        self.dry_run: bool = True
        self.running: bool = False
        self.start_time: float = time.time()

        # Capital
        self.current_capital: float = 0.0
        self.starting_capital: float = 0.0
        self.peak_capital: float = 0.0
        self.total_pnl: float = 0.0
        self.total_exposure: float = 0.0
        self.available: float = 0.0

        # Trading stats
        self.session_trades: int = 0
        self.session_wins: int = 0
        self.session_losses: int = 0
        self.current_streak: int = 0
        self.streak_type: str = ""

        # Live activity
        self.current_btc_price: float = 0.0
        self.current_market: Optional[dict] = None
        self.current_status: str = "starting"

        # Collections
        self.open_positions: list[dict] = []
        self.recent_trades: list[dict] = []
        self.capital_history: deque = deque(maxlen=500)
        self.log_buffer: deque = deque(maxlen=300)

    # ---- writers ----
    def update(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self, k):
                    setattr(self, k, v)

    def add_capital_point(self, capital: float) -> None:
        with self._lock:
            self.capital_history.append((time.time(), capital))

    def add_log(self, entry: dict) -> None:
        with self._lock:
            self.log_buffer.append(entry)

    def consume_cancel_all(self) -> bool:
        """Return True if cancel-all was requested and clear the flag."""
        with self._lock:
            if self.cancel_all_requested:
                self.cancel_all_requested = False
                return True
            return False

    def consume_dry_run_override(self) -> Optional[bool]:
        """Return the pending dry-run override (if any) and clear it."""
        with self._lock:
            val = self.dry_run_override
            self.dry_run_override = None
            return val

    # ---- readers ----
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "paused": self.paused,
                "dry_run": self.dry_run,
                "running": self.running,
                "uptime_seconds": time.time() - self.start_time,
                "current_capital": self.current_capital,
                "starting_capital": self.starting_capital,
                "peak_capital": self.peak_capital,
                "total_pnl": self.total_pnl,
                "total_exposure": self.total_exposure,
                "available": self.available,
                "session_trades": self.session_trades,
                "session_wins": self.session_wins,
                "session_losses": self.session_losses,
                "win_rate": (
                    self.session_wins / self.session_trades * 100
                    if self.session_trades else 0.0
                ),
                "current_streak": self.current_streak,
                "streak_type": self.streak_type,
                "current_btc_price": self.current_btc_price,
                "current_market": self.current_market,
                "current_status": self.current_status,
                "open_positions": list(self.open_positions),
                "recent_trades": list(self.recent_trades)[-20:],
                "capital_history": [
                    {"t": t, "v": v} for (t, v) in self.capital_history
                ],
            }

    def get_logs(self, limit: int = 200) -> list:
        with self._lock:
            buf = list(self.log_buffer)
        return buf[-limit:]


class StateLogHandler(logging.Handler):
    """Logging handler that appends every record into bot_state's log buffer."""

    def __init__(self, state: BotState):
        super().__init__()
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.state.add_log({
                "time": record.created,
                "level": record.levelname,
                "name": record.name,
                "message": record.getMessage(),
            })
        except Exception:
            self.handleError(record)


# Module-level singleton used by bot.py and dashboard.py
bot_state = BotState()
