#!/usr/bin/env bash
# One-shot launcher for the Polymarket BTC bot.
#
# Usage:
#   ./start.sh              # whatever DRY_RUN is set to in .env
#   ./start.sh --live       # force live trading
#   ./start.sh --dry-run    # force paper trading
#
# The script:
#   1. cds into its own directory (so you can double-click it from Finder)
#   2. activates ./venv (creates it on first run if missing)
#   3. installs requirements if needed
#   4. verifies .env exists
#   5. launches python run.py under caffeinate so the Mac won't sleep

set -e

cd "$(dirname "$0")"

# ---- venv ----
if [ ! -d "venv" ]; then
  echo "==> Creating venv..."
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

# ---- deps ----
# Only re-install if requirements.txt is newer than the marker file.
if [ ! -f ".deps_installed" ] || [ "requirements.txt" -nt ".deps_installed" ]; then
  echo "==> Installing/updating dependencies..."
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
  touch .deps_installed
fi

# ---- .env sanity check ----
if [ ! -f ".env" ]; then
  echo "==> No .env found — launching interactive setup wizard..."
  echo ""
  python setup.py
  if [ ! -f ".env" ]; then
    echo "!! Setup did not complete. Run ./start.sh again when ready."
    exit 1
  fi
fi

# ---- launch ----
echo "==> Starting bot (Ctrl+C to stop)..."
exec caffeinate -dims python run.py "$@"
