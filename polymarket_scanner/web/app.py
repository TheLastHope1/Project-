"""FastAPI app exposing the scanner's state and controls."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..scanner import ScanConfig
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


def _build_cfg_from_env() -> ScanConfig:
    return ScanConfig(**config_to_scanconfig_kwargs(read_config()))


class ConfigUpdate(BaseModel):
    POLY_DESKTOP: str | None = Field(default=None)
    POLY_WEBHOOK_URL: str | None = Field(default=None)
    POLY_WATCHLIST: str | None = Field(default=None)
    POLY_MAX_PRICE: str | None = Field(default=None)
    POLY_MIN_LIQUIDITY: str | None = Field(default=None)
    POLY_MIN_VOLUME: str | None = Field(default=None)
    POLY_INTERVAL: str | None = Field(default=None)
    POLY_MAX_SCREEN_PRICE: str | None = Field(default=None)
    POLY_USE_CLOB_PRICES: str | None = Field(default=None)
    POLY_REQUIRE_CLOB_PRICE: str | None = Field(default=None)
    POLY_MAX_CLOB_PROBES: str | None = Field(default=None)
    POLY_FEE_BPS: str | None = Field(default=None)
    POLY_SLIPPAGE_BUFFER_BPS: str | None = Field(default=None)


def create_app() -> FastAPI:
    state = AppState()
    runner = ScannerRunner(state)
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
        saved = write_config(updates)

        # Sync os.environ so notifier config (webhook, desktop) picks up the
        # new values on the next alert without a full restart.
        for k, v in saved.items():
            os.environ[k] = v

        restarted = False
        if runner.is_running():
            log.info("config changed - restarting scanner thread")
            runner.stop()
            runner.start(_build_cfg_from_env())
            restarted = True

        return {"config": saved, "scanner_restarted": restarted}

    class _StartRequest(BaseModel):
        pass

    @app.post("/api/start", dependencies=[Depends(auth)])
    def api_start(_: _StartRequest | None = None) -> Any:
        if runner.is_running():
            return {"running": True, "started": False, "message": "already running"}
        started = runner.start(_build_cfg_from_env())
        return {"running": runner.is_running(), "started": started}

    @app.post("/api/stop", dependencies=[Depends(auth)])
    def api_stop() -> Any:
        stopped = runner.stop()
        return {"running": runner.is_running(), "stopped": stopped}

    # --- lifecycle ---
    @app.on_event("startup")
    def _on_startup() -> None:
        log.info("scanner web UI started; auth token prefix: %s...", token[:6])
        if os.environ.get("POLY_AUTOSTART", "1") == "1":
            runner.start(_build_cfg_from_env())

    @app.on_event("shutdown")
    def _on_shutdown() -> None:
        runner.stop(timeout=5.0)

    return app


app = create_app()
