#!/usr/bin/env bash
# Install the Polymarket scanner as a macOS launchd user agent.
# Runs at login, restarts on crash, logs to ./logs/scanner.{log,err}.
#
# Usage:   ./scripts/install-launchd.sh
# After:   launchctl list | grep com.polymarket.scanner
#          tail -f logs/scanner.log
# Remove:  ./scripts/uninstall-launchd.sh

set -euo pipefail

LABEL="com.polymarket.scanner"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"
ENV_FILE="$PROJECT_DIR/scanner.env"

if [[ "$(uname)" != "Darwin" ]]; then
    echo "launchd is macOS-only. Use systemd (scripts/install-systemd.sh) on Linux." >&2
    exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Python venv not found at $PYTHON_BIN" >&2
    echo "Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
    exit 1
fi

mkdir -p "$LOG_DIR" "$(dirname "$PLIST_PATH")"

# Pull config out of scanner.env if present so the plist bakes in the user's
# choices. launchd agents don't inherit the shell environment, so we either
# embed vars here or have the scanner load the file at startup (it does, but
# embedding also helps).
POLY_DESKTOP=""
POLY_WEBHOOK_URL=""
POLY_WATCHLIST=""
POLY_MAX_PRICE=""
POLY_MIN_LIQUIDITY=""
POLY_INTERVAL=""
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a; . "$ENV_FILE"; set +a
fi

# XML-escape a value for use inside a <string>...</string> element.
xml_escape() {
    local s="$1"
    s="${s//&/&amp;}"
    s="${s//</&lt;}"
    s="${s//>/&gt;}"
    s="${s//\"/&quot;}"
    printf '%s' "$s"
}

env_entries=""
add_env() {
    local key="$1" value="$2"
    [[ -z "$value" ]] && return
    env_entries+="        <key>${key}</key>"$'\n'
    env_entries+="        <string>$(xml_escape "$value")</string>"$'\n'
}
add_env POLY_DESKTOP        "${POLY_DESKTOP:-}"
add_env POLY_WEBHOOK_URL    "${POLY_WEBHOOK_URL:-}"
add_env POLY_WATCHLIST      "${POLY_WATCHLIST:-}"
add_env POLY_MAX_PRICE      "${POLY_MAX_PRICE:-}"
add_env POLY_MIN_LIQUIDITY  "${POLY_MIN_LIQUIDITY:-}"
add_env POLY_INTERVAL       "${POLY_INTERVAL:-}"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>-m</string>
        <string>polymarket_scanner.web</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ThrottleInterval</key>
    <integer>30</integer>

    <key>StandardOutPath</key>
    <string>${LOG_DIR}/scanner.log</string>

    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/scanner.err</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
${env_entries}    </dict>
</dict>
</plist>
EOF

# Reload: unload any previous version, then load the new one.
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "Installed launchd agent: $PLIST_PATH"
echo "Scanner + web UI are running in the background."
echo
# Best-effort pull of the auth token for the summary.
sleep 1
TOKEN=""
if [[ -f "$PROJECT_DIR/.scanner_token" ]]; then
    TOKEN="$(cat "$PROJECT_DIR/.scanner_token")"
fi
echo "  Dashboard: http://127.0.0.1:8787/${TOKEN:+?token=$TOKEN}"
echo "  Status:    launchctl list | grep $LABEL"
echo "  Logs:      tail -f $LOG_DIR/scanner.log"
echo "  Errors:    tail -f $LOG_DIR/scanner.err"
echo "  Stop:      ./scripts/uninstall-launchd.sh"
