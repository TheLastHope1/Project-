#!/usr/bin/env bash
# Tail the scanner's log (stdout) live. Ctrl+C to stop tailing - this does
# NOT stop the scanner itself.

set -euo pipefail
LOG="$(cd "$(dirname "$0")/.." && pwd)/logs/scanner.log"
if [[ ! -f "$LOG" ]]; then
    echo "No log yet at $LOG - scanner may not be installed/running." >&2
    echo "Run ./scripts/install-launchd.sh first." >&2
    exit 1
fi
exec tail -F "$LOG"
