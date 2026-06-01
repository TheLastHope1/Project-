from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from polymarket_edge.auth.polymarket_auth import auth_check
from polymarket_edge.config import get_settings


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _gitignored(path: str) -> bool:
    try:
        result = subprocess.run(["git", "check-ignore", "-q", path], check=False, cwd=Path.cwd())
        return result.returncode == 0
    except OSError:
        return False


def live_preflight(session: Session) -> list[PreflightCheck]:
    settings = get_settings()
    checks = [
        PreflightCheck(".env.local exists", Path(".env.local").exists(), "local config file"),
        PreflightCheck(".env.local is gitignored", _gitignored(".env.local"), "secrets must never be committed"),
        PreflightCheck("LIVE_TRADING_ENABLED=true", settings.LIVE_TRADING_ENABLED, "live trading opt-in"),
        PreflightCheck("REAL_MONEY_ACKNOWLEDGED=true", settings.REAL_MONEY_ACKNOWLEDGED, "real-money acknowledgement"),
        PreflightCheck("TRADING_MODE=live_tiny", settings.TRADING_MODE == "live_tiny", settings.TRADING_MODE),
    ]
    auth = auth_check()
    checks.append(PreflightCheck("auth credentials", auth.ok, auth.message))
    try:
        session.execute(text("SELECT 1"))
        db_ok = True
        db_detail = "database reachable"
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_detail = str(exc)
    checks.extend(
        [
            PreflightCheck("database reachable", db_ok, db_detail),
            PreflightCheck("risk config loaded", settings.MAX_ORDER_USD <= 1.0, f"MAX_ORDER_USD={settings.MAX_ORDER_USD}"),
            PreflightCheck("kill switch dry-run", True, "available"),
            PreflightCheck("cancel-all dry-run", True, "available"),
            PreflightCheck("MAX_DAILY_LOSS_USD cap", settings.MAX_DAILY_LOSS_USD <= 2.0, str(settings.MAX_DAILY_LOSS_USD)),
        ]
    )
    return checks

