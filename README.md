# Polymarket Forfeit-Edge Scanner

Scans Polymarket continuously for binary markets where a forfeit / no-show
would be profitable and alerts you so you can place a trade manually.

## Why this works

Polymarket resolves forfeited or canceled events as a 50/50 split of the pot,
**not** as a refund. Every share pays out $0.50 regardless of which side
you hold. So if you can buy the underdog at price `P < 0.50`, a forfeit
resolution nets you `0.50 - P` per share. The cheaper the underdog, the
bigger the edge.

Example: FaZe CS2 vs eyeballers with FaZe double-booked in another tournament.
Market priced FaZe at 0.80 / eyeballers at 0.20. FaZe no-shows -> 50/50 split
-> buying the underdog at 0.20 returns 0.50 per share (150% gross).

The scanner only flags markets that look like plausible forfeit candidates
(esports / tennis / combat-sports categories, or teams on a user watchlist).
A cheap underdog in a politics market is not a forfeit candidate and is
filtered out.

## How it decides

A market is alerted when **all** of these hold:

1. It is active, open, and accepting orders.
2. Liquidity and 24h volume clear the configured floors.
3. The underdog side trades at or below `--max-price` (default 0.40).
4. It matches at least one forfeit-prone signal:
   - category/event title contains an esports or combat-sport keyword, or
   - question text contains a team/entity on your `--watchlist`.

On top of the domain match, the alert notes whether the event starts soon
(`starts_in:Nm`) or - the strongest signal - the scheduled end time has
already passed but the market is still taking trades (`past_end:Nm_still_open`,
which is exactly the FaZe/eyeballers pattern).

## Install

```bash
git clone -b claude/poly-market-scanner-R3RKz https://github.com/TheLastHope1/Project-.git
cd Project-
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Configure

Copy the example env file and edit to taste:

```bash
cp scanner.env.example scanner.env
```

`scanner.env` supports:

| key                 | meaning                                              |
| ------------------- | ---------------------------------------------------- |
| `POLY_DESKTOP`      | `1` = macOS banner notifications on every alert      |
| `POLY_WEBHOOK_URL`  | Discord/Slack incoming-webhook URL (optional)        |
| `POLY_WATCHLIST`    | comma-separated team/entity substrings               |
| `POLY_MAX_PRICE`    | max underdog price to alert (default `0.40`)         |
| `POLY_MIN_LIQUIDITY`| minimum USDC liquidity (default `500`)               |
| `POLY_INTERVAL`     | seconds between scans (default `120`)                |

Values with spaces must be inside the outer quotes, e.g.
`POLY_WATCHLIST="FaZe,G2 Esports,NAVI"`.

## Run interactively

```bash
python -m polymarket_scanner
```

CLI flags (override `scanner.env`):

```bash
python -m polymarket_scanner \
  --max-price 0.30 \
  --min-liquidity 1000 \
  --watchlist FaZe "G2 Esports" NAVI
```

One-shot for cron:

```bash
python -m polymarket_scanner --once
```

## Web UI

A browser dashboard lets you view opportunities and signals live, edit
config, start / stop the scanner, and tail logs — all from your phone or
laptop browser.

```bash
python -m polymarket_scanner.web
```

Prints a URL like `http://127.0.0.1:8787/?token=...` — open it once and the
token is saved in your browser's localStorage. Binds to `127.0.0.1` by
default (local only). For LAN access use `--host 0.0.0.0`; for remote access
use a Tailscale tailnet or an SSH tunnel.

UI tabs:
- **Opportunities** — live forfeit-edge table, sorted by edge %
- **Signals** — price anomalies and stale-open markets (news-as-price-move)
- **Config** — edit every `scanner.env` key. Saving restarts the scanner thread
  with the new values.
- **Logs** — tail the scanner log stream in-browser

Auth token rules:
- First run generates one and writes it to `./.scanner_token` (chmod 600).
- Override with `POLY_AUTH_TOKEN=...` in `scanner.env`.
- Magic URL (`?token=...`) works once; the UI stashes the token in
  localStorage and strips the query string.

## Run 24/7 in the background (macOS)

Install a launchd user agent so the web UI + scanner start at login, restart
on crash, and write logs to `logs/scanner.log`:

```bash
./scripts/install-launchd.sh
```

After install, open the dashboard URL the script prints. Managing the agent:

```bash
./scripts/logs.sh                # tail the log live (Ctrl+C to stop tailing)
launchctl list | grep polymarket # check status
./scripts/uninstall-launchd.sh   # stop and remove
```

Config edits in the web UI take effect immediately (scanner thread restarts
itself). If you edit `scanner.env` by hand, re-run `install-launchd.sh` so
the new env vars are baked into the plist.

## Deploy to Azure (Free with GitHub Student Pack)

Run the scanner 24/7 on a free Azure B1s VM (1 vCPU, 1 GB RAM).

### Step 1: Create the VM

1. Go to [portal.azure.com](https://portal.azure.com) and sign in with your
   GitHub Student account
2. Click **Create a resource** → **Virtual Machine**
3. Configure:
   - **Subscription:** Azure for Students
   - **Image:** Ubuntu Server 24.04 LTS
   - **Size:** Standard_B1s (free tier — 750 hrs/mo)
   - **Authentication:** SSH public key (paste from `cat ~/.ssh/id_rsa.pub`)
   - **Inbound ports:** allow SSH (22)
4. Click **Review + Create** → **Create**
5. Once deployed, go to the VM → **Networking** → **Add inbound port rule**:
   - Port **443** (HTTPS), Protocol TCP, Action Allow
   - Port **80** (HTTP), Protocol TCP, Action Allow
6. Note the VM's **Public IP address**

### Step 2: Deploy

```bash
ssh azureuser@YOUR_VM_IP
sudo su -
git clone -b claude/poly-market-scanner-R3RKz https://github.com/TheLastHope1/Project-.git /opt/polymarket-scanner
cd /opt/polymarket-scanner
bash deploy/setup-droplet.sh
```

The script prints your dashboard URL: `https://YOUR_IP/?token=...`

Your browser will show a security warning (self-signed cert) — click
**Advanced → Proceed** once. After that, the dashboard works from your
phone or any browser, anywhere.

### Cost: $0/month

The B1s VM is free (750 hrs/mo = 24/7). Your $100 Azure credit is not
touched. See [FEASIBILITY.md](FEASIBILITY.md) for full financial analysis.

## Deploy to any Linux VPS (DigitalOcean, etc.)

Same setup script works on any Ubuntu/Debian server:

### Prerequisites

- A VPS (1 CPU, 1 GB RAM, Ubuntu 24.04) — e.g. $5/mo DigitalOcean Droplet
- SSH access (`ssh root@YOUR_IP`)
- (Optional) A domain pointed at the server's IP

### One-command setup

```bash
ssh root@YOUR_IP
git clone -b claude/poly-market-scanner-R3RKz https://github.com/TheLastHope1/Project-.git /opt/polymarket-scanner
cd /opt/polymarket-scanner
bash deploy/setup-droplet.sh
```

Or with a domain (auto Let's Encrypt):

```bash
bash deploy/setup-droplet.sh scanner.yourdomain.com
```

The script prints your dashboard URL with the auth token at the end.
If using IP-only, your browser will show a security warning for the
self-signed cert — accept it once.

### Managing the service

```bash
systemctl status polymarket-scanner    # is it running?
systemctl restart polymarket-scanner   # restart after manual config edit
systemctl stop polymarket-scanner      # stop
journalctl -u polymarket-scanner -f    # tail logs live
nano /opt/polymarket-scanner/scanner.env  # edit config
```

### Updating to latest code

```bash
cd /opt/polymarket-scanner
git pull
.venv/bin/pip install -r requirements.txt
systemctl restart polymarket-scanner
```

### Config changes

Use the Config tab in the web UI (changes take effect immediately), or
edit `scanner.env` on the server and `systemctl restart polymarket-scanner`.

## Layout

```
polymarket_scanner/
  client.py          # Gamma API client + Market dataclass
  scanner.py         # evaluate_market, scan_once, run_forever, ScanConfig
  signals.py         # price-anomaly + stale-open signal watchers
  notifier.py        # console / desktop / webhook sinks
  state.py           # AppState (thread-safe shared state for the web UI)
  __main__.py        # CLI entry point + scanner.env loader
  web/
    app.py           # FastAPI app, /api/*
    auth.py          # token auth
    runner.py        # starts/stops the scanner thread from the UI
    config_file.py   # read/write scanner.env from the UI
    static/index.html  # single-file frontend (vanilla JS)
    __main__.py      # uvicorn entrypoint: python -m polymarket_scanner.web
scripts/
  install-launchd.sh  # installs the web UI + scanner as a macOS LaunchAgent
  uninstall-launchd.sh
  logs.sh
deploy/
  setup-droplet.sh               # one-command server deploy (Ubuntu/Debian)
  polymarket-scanner.service     # systemd unit file
  Caddyfile                      # reverse proxy (auto-TLS)
tests/
  test_scanner.py
Dockerfile              # optional, for Docker / fly.io / Railway
scanner.env.example     # copy to scanner.env and edit
```

## Tests

```bash
python -m pytest tests/
```

Tests cover the evaluator only (no network) - the client is a thin wrapper
over a public REST endpoint.

## Notes

- The scanner reads public data only. You still place trades yourself.
- Polymarket's Gamma API is unauthenticated but rate-limited and occasionally
  blocks non-browser egress (Cloudflare). Run from a residential IP if you
  hit 403s.
- Polymarket can and does change its T&Cs. Re-read the resolution rules
  before trading on any alert.
