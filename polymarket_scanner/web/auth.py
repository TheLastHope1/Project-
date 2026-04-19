"""Token auth for the web UI.

Designed for a personal-use app bound to localhost by default. If you expose
it to the internet (reverse proxy / Tailscale), keep the token secret.
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from fastapi import Header, HTTPException, Request, status

log = logging.getLogger(__name__)

_TOKEN_FILE = Path.cwd() / ".scanner_token"


def get_or_create_token() -> str:
    """Return the auth token. Reads from $POLY_AUTH_TOKEN first, then from
    ./.scanner_token, otherwise generates a fresh one and persists it.
    """
    env_token = os.environ.get("POLY_AUTH_TOKEN")
    if env_token:
        return env_token.strip()
    if _TOKEN_FILE.is_file():
        tok = _TOKEN_FILE.read_text().strip()
        if tok:
            return tok
    tok = secrets.token_urlsafe(24)
    _TOKEN_FILE.write_text(tok)
    _TOKEN_FILE.chmod(0o600)
    log.warning("generated new auth token at %s", _TOKEN_FILE)
    return tok


def require_auth(expected_token: str):
    """FastAPI dependency factory. Accepts the token via either the
    Authorization: Bearer <token> header OR ?token=... query param (so the
    user can paste a magic URL on a new device without typing the token).
    """
    async def _dep(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        supplied: str | None = None
        if authorization and authorization.lower().startswith("bearer "):
            supplied = authorization.split(None, 1)[1].strip()
        if not supplied:
            supplied = request.query_params.get("token")
        if not supplied or not secrets.compare_digest(supplied, expected_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or missing token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return _dep
