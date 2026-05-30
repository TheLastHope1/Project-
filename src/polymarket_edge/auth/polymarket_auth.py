from __future__ import annotations

from dataclasses import dataclass

from polymarket_edge.config import get_settings


@dataclass(frozen=True)
class AuthCheckResult:
    ok: bool
    message: str


def auth_check() -> AuthCheckResult:
    settings = get_settings()
    missing = [
        key
        for key, value in {
            "POLYMARKET_API_KEY": settings.POLYMARKET_API_KEY,
            "POLYMARKET_API_SECRET": settings.POLYMARKET_API_SECRET,
            "POLYMARKET_API_PASSPHRASE": settings.POLYMARKET_API_PASSPHRASE,
            "POLYMARKET_FUNDER_ADDRESS": settings.POLYMARKET_FUNDER_ADDRESS,
        }.items()
        if not value
    ]
    if missing:
        return AuthCheckResult(False, f"missing credentials: {', '.join(missing)}")
    return AuthCheckResult(True, "authenticated credentials are present; no orders placed")

