"""Vercel serverless entrypoint.

Vercel's Python runtime only picks up function files inside the ``api/``
directory. The dashboard's regular local entrypoint remains
``python -m polymarket_scanner.web`` -- this file exists purely so Vercel
has a function to bind ``vercel.json``'s ``rewrites`` to.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add the project root to sys.path so the `polymarket_scanner` package is
# importable. Vercel runs each function with its own working directory
# rooted at the file's location; without this the top-level package
# wouldn't resolve.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Serverless instances should not start a long-lived scanner thread on
# import. The dashboard can still be opened for smoke testing; local /
# VPS deploys keep their existing autostart behaviour because they don't
# load this module.
os.environ.setdefault("POLY_AUTOSTART", "0")
os.environ.setdefault("POLY_WEB_SCAN_MAX_PAGES", "1")

from polymarket_scanner.web.app import app  # noqa: E402,F401
