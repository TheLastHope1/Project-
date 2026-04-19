"""Notification sinks for scanner alerts."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from typing import Callable

import requests

from .scanner import Opportunity

log = logging.getLogger(__name__)

Notifier = Callable[[Opportunity], None]


def console_notifier(opp: Opportunity) -> None:
    banner = "=" * 72
    print(f"\n{banner}\nALERT\n{banner}\n{opp.summary()}\n", flush=True)


def _desktop_available() -> str | None:
    if sys.platform == "darwin":
        return "osascript"
    if sys.platform.startswith("linux") and shutil.which("notify-send"):
        return "notify-send"
    if sys.platform == "win32":
        return "msg"
    return None


def desktop_notifier(opp: Opportunity) -> None:
    tool = _desktop_available()
    title = f"Polymarket edge {opp.edge_pct:+.0%}"
    body = f"{opp.underdog_outcome} @ {opp.underdog_price:.2f} - {opp.market.question[:120]}"
    try:
        if tool == "notify-send":
            subprocess.run(["notify-send", title, body], check=False, timeout=5)
        elif tool == "osascript":
            script = f'display notification "{body}" with title "{title}"'
            subprocess.run(["osascript", "-e", script], check=False, timeout=5)
        elif tool == "msg":
            subprocess.run(["msg", "*", f"{title}: {body}"], check=False, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("desktop notification failed: %s", exc)


def webhook_notifier(url: str) -> Notifier:
    """POST a JSON payload to an arbitrary webhook (Discord/Slack compatible)."""
    def _send(opp: Opportunity) -> None:
        payload = {
            "content": opp.summary(),
            "text": opp.summary(),  # Slack-compatible
            "market_id": opp.market.id,
            "question": opp.market.question,
            "underdog_outcome": opp.underdog_outcome,
            "underdog_price": opp.underdog_price,
            "edge_pct": opp.edge_pct,
            "reasons": opp.reasons,
            "url": opp.market.url,
        }
        try:
            requests.post(url, json=payload, timeout=10)
        except requests.RequestException as exc:
            log.warning("webhook post failed: %s", exc)

    return _send


def build_default_notifier() -> Notifier:
    """Compose notifiers based on env: POLY_WEBHOOK_URL, POLY_DESKTOP=1."""
    sinks: list[Notifier] = [console_notifier]
    webhook = os.environ.get("POLY_WEBHOOK_URL")
    if webhook:
        sinks.append(webhook_notifier(webhook))
    if os.environ.get("POLY_DESKTOP") == "1":
        sinks.append(desktop_notifier)

    def _fanout(opp: Opportunity) -> None:
        for sink in sinks:
            try:
                sink(opp)
            except Exception:  # noqa: BLE001
                log.exception("notifier sink raised")

    return _fanout
