"""Vercel/FastAPI entrypoint.

The regular local entrypoint remains `python -m polymarket_scanner.web`.
Vercel looks for a top-level FastAPI `app`, so this module exports the existing
dashboard app without changing the package layout.
"""
from __future__ import annotations

import os

# Serverless instances should not start a long-lived scanner thread on import.
# The dashboard can still be opened for smoke testing and local/VPS deploys keep
# their existing autostart behavior.
os.environ.setdefault("POLY_AUTOSTART", "0")
os.environ.setdefault("POLY_WEB_SCAN_MAX_PAGES", "1")

from polymarket_scanner.web.app import app  # noqa: E402,F401
