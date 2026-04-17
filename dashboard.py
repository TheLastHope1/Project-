"""
Local web dashboard for the Polymarket BTC trading bot.

Runs a Flask app in a daemon thread alongside the bot. Reads from
bot_state (shared, thread-safe) and writes control flags back. The
bot's main loop polls those flags each cycle.

Access:
    http://localhost:5000         (on the machine running the bot)
    http://<mac-lan-ip>:5000      (from phone/tablet on same WiFi)

Auth:
    Every /api/* call needs an X-Token header. The token is written
    to .dashboard_token on first run; append it to the URL as
    ?token=<value> once and the UI remembers it in localStorage.
"""
import logging
import os
import secrets
import socket
from functools import wraps
from pathlib import Path
from threading import Thread

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.serving import make_server

import config
from state import bot_state

logger = logging.getLogger("polymarket_bot.dashboard")

_TOKEN_FILE = Path(".dashboard_token")


def _load_or_create_token() -> str:
    """Return the dashboard token, creating one on first run."""
    if config.DASHBOARD_TOKEN:
        return config.DASHBOARD_TOKEN
    if _TOKEN_FILE.exists():
        token = _TOKEN_FILE.read_text().strip()
        if token:
            return token
    token = secrets.token_urlsafe(24)
    _TOKEN_FILE.write_text(token)
    try:
        os.chmod(_TOKEN_FILE, 0o600)
    except Exception:
        pass
    return token


def _local_ips() -> list[str]:
    """Best-effort list of LAN IPs to print on startup."""
    ips = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ":" in ip:  # skip IPv6
                continue
            if ip.startswith("127."):
                continue
            ips.add(ip)
    except Exception:
        pass
    # Also try the UDP-socket trick
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(ips)


def create_app(token: str) -> Flask:
    """Build the Flask app. Token is checked on every /api/* call."""
    static_dir = Path(__file__).parent / "static"
    app = Flask(
        __name__,
        static_folder=str(static_dir),
        static_url_path="/static",
    )
    # Quieter werkzeug access log
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    def require_token(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            supplied = (
                request.headers.get("X-Token")
                or request.args.get("token")
                or ""
            )
            if not secrets.compare_digest(supplied, token):
                return jsonify({"error": "unauthorized"}), 401
            return fn(*args, **kwargs)

        return wrapper

    # ---- static UI ----
    @app.route("/")
    def index():
        return send_from_directory(str(static_dir), "dashboard.html")

    @app.route("/health")
    def health():
        # No auth, just for "is it up" checks.
        return jsonify({"ok": True})

    # ---- read endpoints ----
    @app.route("/api/status")
    @require_token
    def api_status():
        return jsonify(bot_state.snapshot())

    @app.route("/api/logs")
    @require_token
    def api_logs():
        try:
            limit = int(request.args.get("limit", "200"))
        except ValueError:
            limit = 200
        limit = max(1, min(limit, 300))
        return jsonify({"logs": bot_state.get_logs(limit=limit)})

    @app.route("/api/config")
    @require_token
    def api_config_get():
        # Expose only the fields that are safe to display/edit.
        return jsonify({
            "MAX_BET_SIZE": config.MAX_BET_SIZE,
            "MIN_BET_SIZE": config.MIN_BET_SIZE,
            "MAX_CONCURRENT_POSITIONS": config.MAX_CONCURRENT_POSITIONS,
            "MAX_BET_FRACTION": config.MAX_BET_FRACTION,
            "KELLY_FRACTION": config.KELLY_FRACTION,
            "MIN_EDGE_THRESHOLD": config.MIN_EDGE_THRESHOLD,
            "ENTRY_SECONDS_BEFORE_CLOSE": config.ENTRY_SECONDS_BEFORE_CLOSE,
            "LATEST_ENTRY_SECONDS": config.LATEST_ENTRY_SECONDS,
            "MIN_TAKE_PRICE": config.MIN_TAKE_PRICE,
            "MAX_TAKE_PRICE": config.MAX_TAKE_PRICE,
            "SCAN_INTERVAL_SECONDS": config.SCAN_INTERVAL_SECONDS,
        })

    # ---- write endpoints ----
    _ALLOWED_CONFIG_EDITS = {
        "MAX_BET_SIZE": (float, 1.0, 1000.0),
        "MIN_BET_SIZE": (float, 1.0, 100.0),
        "MAX_CONCURRENT_POSITIONS": (int, 1, 50),
        "MAX_BET_FRACTION": (float, 0.001, 1.0),
        "KELLY_FRACTION": (float, 0.01, 1.0),
        "MIN_EDGE_THRESHOLD": (float, 0.0, 0.5),
        "MIN_TAKE_PRICE": (float, 0.01, 0.99),
        "MAX_TAKE_PRICE": (float, 0.01, 0.99),
    }

    @app.route("/api/config", methods=["POST"])
    @require_token
    def api_config_set():
        payload = request.get_json(silent=True) or {}
        applied: dict = {}
        errors: dict = {}
        for key, raw in payload.items():
            spec = _ALLOWED_CONFIG_EDITS.get(key)
            if spec is None:
                errors[key] = "not editable"
                continue
            caster, lo, hi = spec
            try:
                value = caster(raw)
            except (TypeError, ValueError):
                errors[key] = "bad type"
                continue
            if not (lo <= value <= hi):
                errors[key] = f"out of range [{lo}, {hi}]"
                continue
            setattr(config, key, value)
            applied[key] = value
            logger.info(f"Dashboard: config update {key} -> {value}")
        return jsonify({"applied": applied, "errors": errors})

    @app.route("/api/control/pause", methods=["POST"])
    @require_token
    def api_pause():
        bot_state.update(paused=True)
        logger.info("Dashboard: PAUSE requested - no new trades will be opened.")
        return jsonify({"paused": True})

    @app.route("/api/control/resume", methods=["POST"])
    @require_token
    def api_resume():
        bot_state.update(paused=False)
        logger.info("Dashboard: RESUME requested.")
        return jsonify({"paused": False})

    @app.route("/api/control/cancel_all", methods=["POST"])
    @require_token
    def api_cancel_all():
        bot_state.update(cancel_all_requested=True)
        logger.info("Dashboard: cancel-all-orders requested.")
        return jsonify({"queued": True})

    @app.route("/api/control/shutdown", methods=["POST"])
    @require_token
    def api_shutdown():
        bot_state.update(shutdown_requested=True)
        logger.warning("Dashboard: SHUTDOWN requested.")
        return jsonify({"shutting_down": True})

    @app.route("/api/control/dry_run", methods=["POST"])
    @require_token
    def api_dry_run():
        payload = request.get_json(silent=True) or {}
        if "dry_run" not in payload:
            return jsonify({"error": "missing 'dry_run' boolean"}), 400
        value = bool(payload["dry_run"])
        bot_state.update(dry_run_override=value)
        logger.warning(
            f"Dashboard: mode switch requested -> "
            f"{'DRY RUN' if value else 'LIVE'}"
        )
        return jsonify({"queued_dry_run": value})

    return app


class DashboardServer(Thread):
    """Runs the Flask app on a werkzeug server inside a daemon thread."""

    def __init__(self, host: str, port: int, token: str):
        super().__init__(daemon=True, name="dashboard")
        self.host = host
        self.port = port
        self.token = token
        app = create_app(token)
        self._server = make_server(host, port, app, threaded=True)
        self._ctx = app.app_context()
        self._ctx.push()

    def run(self) -> None:  # noqa: D401
        try:
            self._server.serve_forever()
        except Exception as e:
            logger.error(f"Dashboard server crashed: {e}", exc_info=True)

    def shutdown(self) -> None:
        try:
            self._server.shutdown()
        except Exception:
            pass


def start_dashboard() -> DashboardServer | None:
    """Spin up the dashboard server. Returns None if disabled."""
    if not config.DASHBOARD_ENABLED:
        return None

    token = _load_or_create_token()
    host = config.DASHBOARD_HOST
    port = config.DASHBOARD_PORT

    try:
        server = DashboardServer(host=host, port=port, token=token)
    except OSError as e:
        logger.error(
            f"Could not bind dashboard to {host}:{port} - {e}. "
            f"Continuing without the UI."
        )
        return None

    server.start()

    print("\n" + "-" * 60)
    print("  DASHBOARD")
    print("-" * 60)
    print(f"  Local:   http://localhost:{port}?token={token}")
    for ip in _local_ips():
        print(f"  Network: http://{ip}:{port}?token={token}")
    print("  (open the URL once; the token is saved in your browser)")
    print("-" * 60 + "\n")

    return server
