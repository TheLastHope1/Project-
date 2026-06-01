#!/usr/bin/env bash
# One-command bootstrap for the Polymarket Scanner on a fresh Ubuntu 24.04
# server (Azure B1s, DigitalOcean Droplet, or any Debian-family VPS).
#
# Usage:
#   bash deploy/setup-droplet.sh                 # IP-only, self-signed TLS
#   bash deploy/setup-droplet.sh scanner.me.com  # domain, auto Let's Encrypt
#
# Re-running is safe (idempotent). It will pull the latest code and
# restart services without touching scanner.env.

set -euo pipefail

DOMAIN="${1:-}"
REPO_URL="https://github.com/TheLastHope1/Project-.git"
BRANCH="claude/poly-market-scanner-R3RKz"
INSTALL_DIR="/opt/polymarket-scanner"
SERVICE_NAME="polymarket-scanner"

echo "=== Polymarket Scanner — Droplet Setup ==="
echo

# ---- 1. System packages ---------------------------------------------------
echo "[1/8] Installing system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl ufw > /dev/null

# ---- 2. Install Caddy from official repo ----------------------------------
echo "[2/8] Installing Caddy..."
if ! command -v caddy &> /dev/null; then
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https > /dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq caddy > /dev/null
fi

# ---- 3. Swap (safety net for 1 GB droplets) --------------------------------
echo "[3/8] Ensuring swap..."
if [ ! -f /swapfile ]; then
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile > /dev/null
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "  created 1 GB swapfile"
else
    echo "  swapfile already exists"
fi

# ---- 4. Service user -------------------------------------------------------
echo "[4/8] Creating scanner user..."
if ! id -u scanner &>/dev/null; then
    useradd --system --shell /usr/sbin/nologin --home-dir "$INSTALL_DIR" scanner
    echo "  created user: scanner"
else
    echo "  user already exists"
fi

# ---- 5. Clone / update repo ------------------------------------------------
echo "[5/8] Fetching code..."
if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR"
    git fetch origin "$BRANCH"
    git reset --hard "origin/$BRANCH"
    echo "  updated to latest"
else
    git clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    echo "  cloned fresh"
fi
chown -R scanner:scanner "$INSTALL_DIR"

# ---- 6. Python venv + deps -------------------------------------------------
echo "[6/8] Setting up Python environment..."
cd "$INSTALL_DIR"
sudo -u scanner python3 -m venv .venv
sudo -u scanner .venv/bin/pip install --upgrade pip -q
sudo -u scanner .venv/bin/pip install -r requirements.txt -q
echo "  dependencies installed"

# ---- 7. Configuration ------------------------------------------------------
echo "[7/8] Configuring..."

# scanner.env — never overwrite existing (preserves user edits)
if [ ! -f "$INSTALL_DIR/scanner.env" ]; then
    cp "$INSTALL_DIR/scanner.env.example" "$INSTALL_DIR/scanner.env"
    # Sensible server defaults
    sed -i 's/^POLY_DESKTOP=.*/POLY_DESKTOP=0/' "$INSTALL_DIR/scanner.env"
    chown scanner:scanner "$INSTALL_DIR/scanner.env"
    echo "  created scanner.env from example"
else
    echo "  scanner.env exists — not overwriting"
fi

# Caddyfile — domain or IP
if [ -n "$DOMAIN" ]; then
    cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
    reverse_proxy 127.0.0.1:8787
}
CADDY
    echo "  Caddy configured for domain: $DOMAIN"
    echo "  (ensure DNS A record points to this server's IP)"
else
    cat > /etc/caddy/Caddyfile <<CADDY
:443 {
    tls internal
    reverse_proxy 127.0.0.1:8787
}
CADDY
    echo "  Caddy configured for IP-only (self-signed TLS)"
fi

# systemd service
cp "$INSTALL_DIR/deploy/polymarket-scanner.service" \
   /etc/systemd/system/${SERVICE_NAME}.service
systemctl daemon-reload

# ---- 8. Enable + start + firewall ------------------------------------------
echo "[8/8] Starting services..."
systemctl enable --now ${SERVICE_NAME}.service
systemctl enable --now caddy
caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 2>/dev/null || true

# Firewall — allow SSH first to avoid lockout
ufw allow 22/tcp > /dev/null 2>&1
ufw allow 80/tcp > /dev/null 2>&1
ufw allow 443/tcp > /dev/null 2>&1
ufw --force enable > /dev/null 2>&1

# ---- Done -------------------------------------------------------------------
echo
echo "Waiting for app to start..."
sleep 3

TOKEN=""
if [ -f "$INSTALL_DIR/.scanner_token" ]; then
    TOKEN=$(cat "$INSTALL_DIR/.scanner_token")
fi

IP=$(curl -s -4 ifconfig.me || hostname -I | awk '{print $1}')
if [ -n "$DOMAIN" ]; then
    BASE_URL="https://$DOMAIN"
else
    BASE_URL="https://$IP"
fi

echo
echo "========================================================================"
echo "  Polymarket Scanner is live!"
echo
echo "  Dashboard: ${BASE_URL}/?token=${TOKEN}"
echo
echo "  (If using IP-only, accept the self-signed cert warning in your browser)"
echo "========================================================================"
echo
echo "Management commands:"
echo "  systemctl status $SERVICE_NAME    # check status"
echo "  systemctl restart $SERVICE_NAME   # restart"
echo "  journalctl -u $SERVICE_NAME -f    # tail logs"
echo "  nano $INSTALL_DIR/scanner.env     # edit config"
echo
