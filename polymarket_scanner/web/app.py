"""FastAPI app exposing the scanner's state and controls."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..client import PolymarketClient
from ..journal import make_journal
from ..scanner import ScanConfig, evaluate_markets
from ..signals import PriceAnomalyWatcher
from ..state import AppState, StateLogHandler
from .auth import get_or_create_token, require_auth
from .config_file import (
    EDITABLE_KEYS,
    config_to_scanconfig_kwargs,
    read_config,
    read_config_for_ui,
    write_config,
)
from .runner import ScannerRunner

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def _build_cfg_from_env(journal: Journal | None = None) -> ScanConfig:
    kwargs = config_to_scanconfig_kwargs(read_config())
    cfg = ScanConfig(**kwargs)
    if journal is not None:
        cfg.journal = journal
        cfg.persist_opportunities = True
    return cfg


def _manual_scan_max_pages() -> int:
    try:
        return max(1, int(os.environ.get("POLY_WEB_SCAN_MAX_PAGES", "1")))
    except ValueError:
        return 1


class ConfigUpdate(BaseModel):
    POLY_DESKTOP: str | None = Field(default=None)
    POLY_WEBHOOK_URL: str | None = Field(default=None)
    POLY_WATCHLIST: str | None = Field(default=None)
    POLY_MAX_PRICE: str | None = Field(default=None)
    POLY_MIN_LIQUIDITY: str | None = Field(default=None)
    POLY_MIN_VOLUME: str | None = Field(default=None)
    POLY_INTERVAL: str | None = Field(default=None)
    POLY_MAX_SCREEN_PRICE: str | None = Field(default=None)
    POLY_USE_BOOK: str | None = Field(default=None)
    POLY_USE_CLOB_PRICES: str | None = Field(default=None)
    POLY_REQUIRE_CLOB_PRICE: str | None = Field(default=None)
    POLY_USE_CLOB_FEE_RATE: str | None = Field(default=None)
    POLY_MAX_CLOB_PROBES: str | None = Field(default=None)
    POLY_PAPER_NOTIONAL: str | None = Field(default=None)
    POLY_MIN_RULE_CONFIDENCE: str | None = Field(default=None)
    POLY_MIN_P50: str | None = Field(default=None)
    POLY_STRICT_RULE_CLASS: str | None = Field(default=None)
    POLY_FEE_RATE_OVERRIDE: str | None = Field(default=None)
    POLY_FEE_BPS: str | None = Field(default=None)
    POLY_SLIPPAGE_BUFFER_BPS: str | None = Field(default=None)
    POLY_WEB_SCAN_MAX_PAGES: str | None = Field(default=None)


def create_app() -> FastAPI:
    state = AppState()
    # Prefer the durable Postgres backend when POLY_JOURNAL_URL is set
    # (required for serverless deploys); fall back to SQLite at
    # POLY_JOURNAL_PATH otherwise. Either path can fail on a read-only
    # filesystem -- in that case we run with persistence disabled rather
    # than refusing to boot.
    journal_target = os.environ.get("POLY_JOURNAL_URL") or os.environ.get("POLY_JOURNAL_PATH", "journal.db")
    try:
        journal = make_journal(journal_target)
    except Exception:  # noqa: BLE001
        log.exception("could not open journal at %s; persistence disabled", journal_target)
        journal = None
    runner = ScannerRunner(state, journal=journal)
    token = get_or_create_token()
    auth = require_auth(token)

    # Capture scanner log output into AppState.
    root_logger = logging.getLogger()
    if not any(isinstance(h, StateLogHandler) for h in root_logger.handlers):
        root_logger.addHandler(StateLogHandler(state))
    root_logger.setLevel(logging.INFO)

    app = FastAPI(title="Polymarket Scanner", version="0.2.0")

    # Public: serve the dashboard HTML. Auth enforced on /api/*.
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> Any:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # --- API ---
    @app.get("/api/stats", dependencies=[Depends(auth)])
    def api_stats() -> Any:
        return state.snapshot_stats()

    @app.get("/api/opportunities", dependencies=[Depends(auth)])
    def api_opportunities() -> Any:
        return {"opportunities": state.snapshot_opportunities()}

    @app.get("/api/signals", dependencies=[Depends(auth)])
    def api_signals() -> Any:
        return {"signals": state.snapshot_signals()}

    @app.get("/api/logs", dependencies=[Depends(auth)])
    def api_logs(limit: int = 500) -> Any:
        return {"logs": state.snapshot_logs(limit=limit)}

    @app.get("/api/config", dependencies=[Depends(auth)])
    def api_config_get() -> Any:
        return {"config": read_config_for_ui(), "editable_keys": list(EDITABLE_KEYS)}

    @app.put("/api/config", dependencies=[Depends(auth)])
    def api_config_put(payload: ConfigUpdate) -> Any:
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        try:
            saved = write_config(updates)
        except OSError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"config file is read-only on this deployment ({exc.strerror or exc!s}); "
                       f"set values via environment variables instead",
            ) from exc

        # Sync os.environ so notifier config (webhook, desktop) picks up the
        # new values on the next alert without a full restart.
        for k, v in saved.items():
            os.environ[k] = v

        restarted = False
        if runner.is_running():
            log.info("config changed - restarting scanner thread")
            runner.stop()
            runner.start(_build_cfg_from_env(journal=journal))
            restarted = True

        return {"config": saved, "scanner_restarted": restarted}

    class _StartRequest(BaseModel):
        pass

    @app.post("/api/start", dependencies=[Depends(auth)])
    def api_start(_: _StartRequest | None = None) -> Any:
        if runner.is_running():
            return {"running": True, "started": False, "message": "already running"}
        started = runner.start(_build_cfg_from_env(journal=journal))
        return {"running": runner.is_running(), "started": started}

    @app.post("/api/stop", dependencies=[Depends(auth)])
    def api_stop() -> Any:
        stopped = runner.stop()
        return {"running": runner.is_running(), "stopped": stopped}

    @app.post("/api/scan-now", dependencies=[Depends(auth)])
    def api_scan_now() -> Any:
        cfg = _build_cfg_from_env(journal=journal)
        max_pages = _manual_scan_max_pages()
        client = PolymarketClient()
        now = datetime.now(timezone.utc)
        markets = list(client.iter_active_markets(max_pages=max_pages))
        watcher = PriceAnomalyWatcher(state, cfg)
        try:
            watcher.observe(markets)
            watcher.observe_stale(markets)
        except Exception:  # noqa: BLE001
            log.exception("signal watcher failed during manual scan")
        opps = evaluate_markets(markets, cfg, now, client=client)
        state.set_opportunities(opps)
        log.info(
            "manual scan: markets=%d opportunities=%d max_pages=%d journal_rows=%d",
            len(markets),
            len(opps),
            max_pages,
            journal.opportunity_count() if journal else -1,
        )
        return {
            "markets_scanned": len(markets),
            "opportunities": len(opps),
            "max_pages": max_pages,
            "stats": state.snapshot_stats(),
            "journal_total_rows": journal.opportunity_count() if journal else None,
        }

    @app.get("/api/journal/pnl", dependencies=[Depends(auth)])
    def api_journal_pnl() -> Any:
        if journal is None:
            return JSONResponse({"error": "journal disabled in this deployment"}, status_code=503)
        return journal.realised_pnl_summary()

    @app.get("/api/journal/latest", dependencies=[Depends(auth)])
    def api_journal_latest(limit: int = 100) -> Any:
        if journal is None:
            return JSONResponse({"error": "journal disabled in this deployment"}, status_code=503)
        return {"rows": journal.latest_opportunities(limit=limit)}

    @app.post("/api/validate-side-semantics", dependencies=[Depends(auth)])
    def api_validate_side_semantics(token_id: str) -> Any:
        """Cross-check ``/price`` BUY/SELL semantics against ``/book``.

        Runs the contract test the PDF review identified as the single most
        important integration check. Persists the result so a CI/cron job
        can audit drift over time.
        """
        client = PolymarketClient()
        result = client.validate_price_side_semantics(token_id)
        if journal is not None:
            try:
                journal.record_side_semantics_check(
                    checked_at=datetime.now(timezone.utc),
                    token_id=token_id,
                    ok=bool(result.get("ok")),
                    buy_price=result.get("buy_price"),
                    sell_price=result.get("sell_price"),
                    best_bid=result.get("best_bid"),
                    best_ask=result.get("best_ask"),
                    notes=result.get("notes"),
                )
            except Exception:  # noqa: BLE001
                log.exception("failed to persist side-semantics check")
        return result

    # --- lifecycle ---
    @app.on_event("startup")
    def _on_startup() -> None:
        # Don't log even a prefix of the auth token. Vercel/cloud log
        # aggregators are not a safe place to leak secrets.
        log.info("scanner web UI started; auth token length=%d", len(token))
        if journal is not None:
            log.info("journal enabled at %s (rows=%d)", journal.path, journal.opportunity_count())
        if os.environ.get("POLY_AUTOSTART", "1") == "1":
            runner.start(_build_cfg_from_env(journal=journal))

    @app.on_event("shutdown")
    def _on_shutdown() -> None:
        runner.stop(timeout=5.0)

    return app


app = create_app()
