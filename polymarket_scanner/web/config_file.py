"""Read and write ./scanner.env from the web UI."""
from __future__ import annotations

from pathlib import Path
from typing import Any

ENV_PATH = Path.cwd() / "scanner.env"

# Keys exposed to the UI. Anything else in scanner.env is preserved but hidden.
EDITABLE_KEYS = (
    "POLY_DESKTOP",
    "POLY_WEBHOOK_URL",
    "POLY_WATCHLIST",
    "POLY_MAX_PRICE",
    "POLY_MIN_LIQUIDITY",
    "POLY_MIN_VOLUME",
    "POLY_INTERVAL",
    "POLY_MAX_SCREEN_PRICE",
    "POLY_USE_CLOB_PRICES",
    "POLY_REQUIRE_CLOB_PRICE",
    "POLY_MAX_CLOB_PROBES",
    "POLY_FEE_BPS",
    "POLY_SLIPPAGE_BUFFER_BPS",
)


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def read_config() -> dict[str, str]:
    if not ENV_PATH.is_file():
        return {}
    return _parse(ENV_PATH.read_text())


def read_config_for_ui() -> dict[str, Any]:
    current = read_config()
    return {k: current.get(k, "") for k in EDITABLE_KEYS}


def _quote_env_value(value: str) -> str:
    safe = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    return f'"{safe}"'


def write_config(updates: dict[str, str]) -> dict[str, str]:
    """Update keys in scanner.env, preserving comments / unknown keys.

    Only EDITABLE_KEYS are accepted. Values are re-quoted with double quotes.
    """
    clean = {k: str(v) for k, v in updates.items() if k in EDITABLE_KEYS}

    if not ENV_PATH.is_file():
        # Write a fresh file with defaults.
        lines = [f"{k}={_quote_env_value(clean.get(k, ''))}" for k in EDITABLE_KEYS]
        ENV_PATH.write_text("\n".join(lines) + "\n")
        return read_config_for_ui()

    existing_lines = ENV_PATH.read_text().splitlines()
    written: set[str] = set()
    new_lines: list[str] = []
    for raw in existing_lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(raw)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in clean:
            new_lines.append(f"{key}={_quote_env_value(clean[key])}")
            written.add(key)
        else:
            new_lines.append(raw)
    for k in EDITABLE_KEYS:
        if k not in written and k in clean:
            new_lines.append(f"{k}={_quote_env_value(clean[k])}")
    ENV_PATH.write_text("\n".join(new_lines) + "\n")
    return read_config_for_ui()


def config_to_scanconfig_kwargs(raw: dict[str, str]) -> dict[str, Any]:
    """Convert env-string values into ScanConfig constructor kwargs."""
    from datetime import timedelta

    kwargs: dict[str, Any] = {}
    if raw.get("POLY_MAX_PRICE"):
        kwargs["max_underdog_price"] = float(raw["POLY_MAX_PRICE"])
    if raw.get("POLY_MIN_LIQUIDITY"):
        kwargs["min_liquidity"] = float(raw["POLY_MIN_LIQUIDITY"])
    if raw.get("POLY_MIN_VOLUME"):
        kwargs["min_volume"] = float(raw["POLY_MIN_VOLUME"])
    if raw.get("POLY_INTERVAL"):
        kwargs["scan_interval"] = timedelta(seconds=int(raw["POLY_INTERVAL"]))
    if raw.get("POLY_MAX_SCREEN_PRICE"):
        kwargs["max_screen_price"] = float(raw["POLY_MAX_SCREEN_PRICE"])
    if raw.get("POLY_USE_CLOB_PRICES"):
        kwargs["use_clob_prices"] = raw["POLY_USE_CLOB_PRICES"].strip().lower() not in {"0", "false", "no", "off"}
    if raw.get("POLY_REQUIRE_CLOB_PRICE"):
        kwargs["require_clob_price"] = raw["POLY_REQUIRE_CLOB_PRICE"].strip().lower() in {"1", "true", "yes", "on"}
    if raw.get("POLY_MAX_CLOB_PROBES"):
        kwargs["max_clob_probes_per_scan"] = int(raw["POLY_MAX_CLOB_PROBES"])
    if raw.get("POLY_FEE_BPS"):
        kwargs["fee_bps"] = float(raw["POLY_FEE_BPS"])
    if raw.get("POLY_SLIPPAGE_BUFFER_BPS"):
        kwargs["slippage_buffer_bps"] = float(raw["POLY_SLIPPAGE_BUFFER_BPS"])
    if raw.get("POLY_WATCHLIST"):
        kwargs["team_watchlist"] = tuple(
            s.strip() for s in raw["POLY_WATCHLIST"].split(",") if s.strip()
        )
    return kwargs
