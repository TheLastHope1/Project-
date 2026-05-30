"""Vercel serverless entrypoint (FastAPI framework detection).

Per Vercel's Python docs, a FastAPI ``app`` exported from one of
``app.py`` / ``index.py`` / ``server.py`` / ``main.py`` *at the project
root* triggers Vercel's FastAPI framework detection. The earlier
``api/index.py`` attempt failed because that directory is reserved for
ad-hoc ``BaseHTTPRequestHandler`` functions, not framework-mode FastAPI.

Local development still uses ``python -m polymarket_scanner.web``; this
module exists only so Vercel has an importable ``app`` at the root.
"""
from __future__ import annotations

import os

# Serverless instances should not start a long-lived scanner thread on
# import: the thread dies the moment the container freezes. The dashboard
# can still be opened for smoke testing, and the /api/scan-now endpoint
# fires individual scans on demand. Local/VPS deploys keep their
# existing autostart behaviour because they don't load this module.
os.environ.setdefault("POLY_AUTOSTART", "0")
os.environ.setdefault("POLY_WEB_SCAN_MAX_PAGES", "1")

from polymarket_scanner.web.app import app  # noqa: E402,F401
