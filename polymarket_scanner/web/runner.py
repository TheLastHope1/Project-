"""Runs the scanner inside the web process as a background thread."""
from __future__ import annotations

import logging
import threading

from ..client import PolymarketClient
from ..notifier import build_default_notifier
from ..scanner import Opportunity, ScanConfig, run_forever
from ..signals import PriceAnomalyWatcher
from ..state import AppState

log = logging.getLogger(__name__)


class ScannerRunner:
    """Start / stop the scanner thread. Thread-safe."""

    def __init__(self, state: AppState):
        self.state = state
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

        # Track the raw market list from the last scan so signal watchers can
        # diff against the new one. scan_once currently only returns filtered
        # Opportunity objects, so we need the pre-filter list too - we get that
        # by iterating the client directly inside on_scan_complete.
        def on_opportunity(opp: Opportunity) -> None:
            try:
                notify(opp)
            except Exception:  # noqa: BLE001
                log.exception("notifier failed")

        def on_scan_complete(opps: list[Opportunity]) -> None:
            self.state.set_opportunities(opps)
            # Feed the full (pre-filter) market list into the signal watchers
            # so they can detect anomalies on markets that didn't clear the
            # opportunity threshold this round.
            try:
                markets = list(client.iter_active_markets())
                watcher.observe(markets)
                watcher.observe_stale(markets)
            except Exception:  # noqa: BLE001
                log.exception("signal watcher failed")

        try:
            run_forever(
                client=client,
                cfg=cfg,
                on_opportunity=on_opportunity,
                stop_event=self._stop_event,
                on_scan_complete=on_scan_complete,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("scanner thread crashed")
            self.state.mark_stopped(error=str(exc))
        else:
            self.state.mark_stopped()
