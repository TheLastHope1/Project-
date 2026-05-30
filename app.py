"""Vercel FastAPI entrypoint for polymarket-edge."""

from __future__ import annotations

from polymarket_edge.web.app import app

__all__ = ["app"]
