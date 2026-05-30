from __future__ import annotations

from polymarket_edge.auth.polymarket_auth import auth_check


def balances() -> tuple[bool, str]:
    auth = auth_check()
    if not auth.ok:
        return False, auth.message
    return True, "balance endpoint scaffold ready; no order placement attempted"


def open_orders() -> tuple[bool, str]:
    auth = auth_check()
    if not auth.ok:
        return False, auth.message
    return True, "open-orders endpoint scaffold ready; no order placement attempted"


def cancel_all(dry_run: bool = True) -> tuple[bool, str]:
    if dry_run:
        return True, "cancel-all dry-run complete; no authenticated cancel sent"
    return False, "real cancel-all requires authenticated trading client setup"

