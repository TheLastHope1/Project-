from __future__ import annotations

from pathlib import Path

from dotenv import set_key
from sqlalchemy.orm import Session

from polymarket_edge.db.models import KillSwitchEvent


def _safe_set_key(path: str | Path, key: str, value: str) -> bool:
    target = Path(path)
    try:
        target.touch(mode=0o600, exist_ok=True)
        set_key(str(target), key, value)
    except OSError:
        return False
    return True


def disable_live(path: str | Path = ".env.local") -> bool:
    live_disabled = _safe_set_key(path, "LIVE_TRADING_ENABLED", "false")
    paper_mode = _safe_set_key(path, "TRADING_MODE", "paper")
    return live_disabled and paper_mode


def trigger_kill_switch(session: Session, reason: str = "manual kill switch") -> bool:
    live_disabled = disable_live()
    halt_written = _safe_set_key(".env.local", "LIVE_TRADING_HALTED", "true")
    local_env_updated = live_disabled and halt_written
    session.add(
        KillSwitchEvent(
            reason=reason,
            raw_json={"cancel_all": "dry-run", "local_env_updated": local_env_updated},
        )
    )
    return local_env_updated


def reset_live_halt(confirm_text: str | None = None) -> bool:
    if confirm_text != "RESET LIVE HALT":
        return False
    return _safe_set_key(".env.local", "LIVE_TRADING_HALTED", "false")
