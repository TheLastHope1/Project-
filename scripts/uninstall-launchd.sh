#!/usr/bin/env bash
# Stop and remove the Polymarket scanner launchd agent.

set -euo pipefail

LABEL="com.polymarket.scanner"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [[ -f "$PLIST_PATH" ]]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "Removed $PLIST_PATH"
else
    echo "No launchd agent installed at $PLIST_PATH"
fi

# Also kill any stray python processes running the scanner (belt-and-braces).
pkill -f "python.* -m polymarket_scanner" 2>/dev/null || true
echo "Scanner stopped."
