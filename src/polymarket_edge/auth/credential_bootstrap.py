from __future__ import annotations

from polymarket_edge.config import get_settings


def derive_api_credentials() -> tuple[bool, str]:
    settings = get_settings()
    if not settings.POLYMARKET_PRIVATE_KEY:
        return False, "POLYMARKET_PRIVATE_KEY is missing; provide it explicitly in .env.local or setup-secrets."
    return (
        False,
        "Automatic credential derivation is intentionally not enabled without the official CLOB client setup. "
        "No credentials were created or overwritten.",
    )

