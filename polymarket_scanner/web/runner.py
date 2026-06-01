"""Runs the scanner inside the web process as a background thread."""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from ..client import PolymarketClient
from ..notifier import build_default_notifier
from ..scanner import Opportunity, ScanConfig, run_forever
from ..signals import PriceAnomalyWatcher
from ..state import AppState

if False:  # TYPE_CHECKING -- Journal is duck-typed; both SQLite + Postgres satisfy it.
    from ..journal import Journal  # noqa: F401

log = logging.getLogger(__name__)


class ScannerRunner:
    """Start / stop the scanner thread. Thread-safe."""

    def __init__(self, state: AppState, journal: object | None = None):
        # journal is duck-typed: either ``Journal`` (SQLite) or ``PostgresJournal``.
        self.state = state
        self.journal = journal
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        # cfg is rebuilt on each start() so config edits via the UI take effect.
        self._cfg: ScanConfig | None = None

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, cfg: ScanConfig) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            # Make sure the journal is attached even if the caller forgot.
            if self.journal is not None and cfg.journal is None:
                cfg.journal = self.journal
                cfg.persist_opportunities = True
            self._cfg = cfg
            self._stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._run, name="scanner", daemon=True
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = 10.0) -> bool:
        with self._lock:
            t = self._thread
            self._stop_event.set()
        if t is not None:
            t.join(timeout=timeout)
        with self._lock:
            alive = t is not None and t.is_alive()
            if not alive:
                self._thread = None
        self.state.mark_stopped()
        return not alive

    def _run(self) -> None:
        assert self._cfg is not None
        cfg = self._cfg
        client = PolymarketClient()
        notify = build_default_notifier()
        watcher = PriceAnomalyWatcher(self.state, cfg)
        self.state.mark_started()

        last_markets = []

        def on_markets_scanned(markets):
            nonlocal last_markets
            last_markets = list(markets)
            try:
                watcher.observe(last_markets)
                watcher.observe_stale(last_markets)
            except Exception:  # noqa: BLE001
                log.exception("signal watcher failed")

        def on_opportunity(opp: Opportunity) -> None:
            try:
                notify(opp)
            except Exception:  # noqa: BLE001
                log.exception("notifier failed")

        def on_scan_complete(opps: list[Opportunity]) -> None:
            self.state.set_opportunities(opps)

        try:
            run_forever(
                client=client,
                cfg=cfg,
                on_opportunity=on_opportunity,
                stop_event=self._stop_event,
                on_scan_complete=on_scan_complete,
                on_markets_scanned=on_markets_scanned,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("scanner thread crashed")
            self.state.mark_stopped(error=str(exc))
        else:
            self.state.mark_stopped()
