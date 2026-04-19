"""Run the web UI: `python -m polymarket_scanner.web`."""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import uvicorn

from ..__main__ import _load_env_file


def main() -> int:
    # Load scanner.env from cwd so auth token / webhook / etc. pick up.
    _load_env_file(Path.cwd() / "scanner.env")

    parser = argparse.ArgumentParser(prog="polymarket_scanner.web")
    parser.add_argument("--host", default=os.environ.get("POLY_WEB_HOST", "127.0.0.1"),
                        help="Bind address. Default 127.0.0.1 (local only). "
                             "Use 0.0.0.0 for LAN access, but only if you trust the network.")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("POLY_WEB_PORT", "8787")))
    parser.add_argument("--reload", action="store_true",
                        help="Auto-reload on file changes (development only).")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Print the access URL + token once at startup.
    from .auth import get_or_create_token
    token = get_or_create_token()
    url = f"http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}/?token={token}"
    print("=" * 72)
    print("Polymarket scanner UI")
    print(f"  URL: {url}")
    print(f"  (token is also stored in ./.scanner_token)")
    print("=" * 72)

    uvicorn.run(
        "polymarket_scanner.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
