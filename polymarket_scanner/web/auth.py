"""Token auth for the web UI.

Designed for a personal-use app bound to localhost by default. If you expose
it to the internet (reverse proxy / Tailscale), keep the token secret.

Token resolution, in order:

    1. ``$POLY_AUTH_TOKEN`` -- always wins. Required on serverless
       deploys (Vercel, Cloud Run) where neither the cwd nor /tmp survives.
    2. ``./.scanner_token`` -- used on local/VM deploys.
    3. ``$TMPDIR/.polymarket_scanner_token`` -- last-resort fallback for
       read-only filesystems where we can still write to /tmp.
    4. In-memory ephemeral token -- generated if absolutely nothing else
       worked. Won't survive a process restart, but at least the app boots.
"""
from __future__ import annotations

import logging
import os
import secrets
import tempfile
from pathlib import Path

from fastapi import Header, HTTPException, Request, status

log = logging.getLogger(__name__)

_TOKEN_FILE = Path.cwd() / ".scanner_token"
_TMP_TOKEN_FILE = Path(tempfile.gettempdir()) / ".polymarket_scanner_token"


def _try_read(path: Path) -> str | None:
    try:
        if path.is_file():
            tok = path.read_text().strip()
            return tok or None
    except OSError:
        pass
    return None


def _try_write(path: Path, value: str) -> bool:
    try:
        path.write_text(value)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False


def get_or_create_token() -> str:
    """Resolve (or persist) the auth token.

    Honours ``$POLY_AUTH_TOKEN`` first; falls back to the local-disk file,
    then to a /tmp-backed file, then to a process-lifetime in-memory value.
    """
    env_token = os.environ.get("POLY_AUTH_TOKEN")
    if env_token:
        return env_token.strip()

    for candidate in (_TOKEN_FILE, _TMP_TOKEN_FILE):
        existing = _try_read(candidate)
        if existing:
            return existing

    tok = secrets.token_urlsafe(24)
    for candidate in (_TOKEN_FILE, _TMP_TOKEN_FILE):
        if _try_write(candidate, tok):
            log.warning("generated new auth token at %s", candidate)
            return tok

    log.error(
        "could not persist auth token to disk; using an ephemeral one. "
        "Set $POLY_AUTH_TOKEN to a stable value for production deploys."
    )
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
