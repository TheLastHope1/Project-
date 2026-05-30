from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values, set_key

from polymarket_edge.logging import redact_value

SECRET_KEYS = (
    "POLYMARKET_PRIVATE_KEY",
    "POLYMARKET_FUNDER_ADDRESS",
    "POLYMARKET_SIGNATURE_TYPE",
    "POLYMARKET_API_KEY",
    "POLYMARKET_API_SECRET",
    "POLYMARKET_API_PASSPHRASE",
)


def env_path(path: str | Path = ".env.local") -> Path:
    return Path(path)


def load_secret_status(path: str | Path = ".env.local") -> dict[str, bool]:
    values = dotenv_values(env_path(path))
    return {key: bool(values.get(key)) for key in SECRET_KEYS}


def redacted_secret_status(path: str | Path = ".env.local") -> dict[str, str]:
    values = dotenv_values(env_path(path))
    result: dict[str, str] = {}
    for key in SECRET_KEYS:
        value = values.get(key) or ""
        result[key] = "missing" if not value else f"present:{redact_value(key, value)}"
    return result


def write_env_value(key: str, value: str, path: str | Path = ".env.local") -> None:
    target = env_path(path)
    target.touch(mode=0o600, exist_ok=True)
    set_key(str(target), key, value)


def required_trading_credentials_present(path: str | Path = ".env.local") -> bool:
    status = load_secret_status(path)
    return all(status[key] for key in SECRET_KEYS if key != "POLYMARKET_PRIVATE_KEY")

