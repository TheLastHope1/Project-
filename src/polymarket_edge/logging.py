from __future__ import annotations

import logging
from collections.abc import Iterable

import structlog

_SECRET_WORDS = ("PRIVATE_KEY", "API_SECRET", "PASSPHRASE", "PASSWORD", "SECRET")


def redact_value(key: str, value: object) -> str:
    text = "" if value is None else str(value)
    if any(word in key.upper() for word in _SECRET_WORDS):
        return "[REDACTED]" if text else ""
    if key.upper().endswith(("ADDRESS", "API_KEY")) and len(text) > 4:
        return f"...{text[-4:]}"
    return text


def redact_mapping(items: dict[str, object], secret_keys: Iterable[str] = ()) -> dict[str, str]:
    secret_set = {key.upper() for key in secret_keys}
    return {
        key: "[REDACTED]" if key.upper() in secret_set else redact_value(key, value)
        for key, value in items.items()
    }


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)

