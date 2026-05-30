from __future__ import annotations

import getpass
import sys
from pathlib import Path

from dotenv import dotenv_values

from polymarket_edge.secrets.manager import SECRET_KEYS, write_env_value


def ensure_env_file(path: str | Path = ".env.local") -> Path:
    target = Path(path)
    if not target.exists():
        target.write_text("# Local polymarket-edge config. Never commit this file.\n", encoding="utf-8")
        target.chmod(0o600)
    return target


def setup_secrets(path: str | Path = ".env.local") -> dict[str, str]:
    target = ensure_env_file(path)
    values = dotenv_values(target)
    if not sys.stdin.isatty():
        for key in SECRET_KEYS:
            if key not in values:
                write_env_value(key, "", target)
        return {"mode": "non-interactive", "message": "created .env.local; trading credentials left blank"}

    print("Enter Polymarket credentials, or press Enter to skip any value.")
    for key in SECRET_KEYS:
        current = values.get(key)
        suffix = " (already set)" if current else ""
        if "PRIVATE_KEY" in key or "SECRET" in key or "PASSPHRASE" in key:
            value = getpass.getpass(f"{key}{suffix}: ")
        else:
            value = input(f"{key}{suffix}: ")
        if value:
            write_env_value(key, value, target)
    return {"mode": "interactive", "message": "secret setup complete; values were not printed"}

