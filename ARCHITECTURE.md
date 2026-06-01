# Polymarket Forfeit-Edge Scanner — Architecture & Technical Documentation

## Table of Contents

1. [What This Project Does](#what-this-project-does)
2. [The Exploit Explained](#the-exploit-explained)
3. [System Architecture](#system-architecture)
4. [File-by-File Breakdown](#file-by-file-breakdown)
5. [Data Flow](#data-flow)
6. [Detection Logic](#detection-logic)
7. [Signal System](#signal-system)
8. [Web UI](#web-ui)
9. [Authentication](#authentication)
10. [Deployment Options](#deployment-options)
11. [Configuration Reference](#configuration-reference)
12. [API Reference](#api-reference)

---

## What This Project Does

This is an automated scanner that monitors Polymarket — a prediction market
platform where users bet on outcomes of real-world events. The scanner
identifies specific opportunities where Polymarket's forfeit resolution
rules create a guaranteed profit for anyone buying the underdog side.

The scanner runs 24/7, polls Polymarket's public API every 2 minutes, and
alerts you (via console, desktop notification, Discord/Slack webhook, or
a browser dashboard) when it finds a profitable setup so you can place a
trade manually.

---

## The Exploit Explained

### How Polymarket Works (Normally)

On Polymarket, users buy shares in binary outcomes (e.g., "FaZe wins" vs
"eyeballers wins"). Share prices reflect implied probabilities — if FaZe
is favored, FaZe shares cost $0.80 and eyeballers shares cost $0.20. If
your side wins, each share pays $1.00. If it loses, you get $0.

### What Happens When an Event is Forfeited

In traditional sports betting, forfeited or canceled events result in all
bets being refunded. Polymarket does it differently: **forfeited events
resolve as a 50/50 split**. Every share, regardless of which side, pays out
exactly $0.50.

### Where the Edge Comes From

If you buy the underdog at price P (where P < 0.50), a forfeit resolution
gives you $0.50 per share — an instant profit of (0.50 - P) per share.

**Example (real case):**
- FaZe Clan CS2 was scheduled in two tournaments simultaneously
- Market: FaZe vs eyeballers, prices: FaZe $0.80 / eyeballers $0.20
- FaZe couldn't make it (double-booked) → match forfeited → 50/50 split
- Anyone holding eyeballers shares bought at $0.20 received $0.50 (150% gross return)
- Anyone holding FaZe shares bought at $0.80 received $0.50 (37.5% loss)

### What the Scanner Looks For

The scanner identifies markets where:
1. The underdog trades cheaply (below a configurable threshold, default $0.40)
2. The market is in a forfeit-prone category (esports, combat sports, tennis)
3. The market structure is head-to-head (not "will X win the season")
4. There's a timing signal (event is imminent or already past its scheduled end)

Signal #4 is critical — it's the FaZe/eyeballers pattern: the event time
has passed but the market is still accepting trades, meaning a forfeit is
likely imminent.

---

## System Architecture

```
                    +------------------+
                    |   Polymarket     |
                    |   Gamma API      |
                    +--------+---------+
                             |
                    HTTP GET /markets (every 2 min)
                             |
                    +--------v---------+
                    |  PolymarketClient|  (client.py)
                    |  iter_active_    |
                    |  markets()       |
                    +--------+---------+
                             |
              raw Market objects (dataclass)
                             |
              +--------------+---------------+
              |                              |
     +--------v---------+          +--------v---------+
     |   Scanner Loop   |          | PriceAnomaly     |
     |   (scanner.py)   |          | Watcher          |
     |   evaluate_market |          | (signals.py)     |
     |   _classify()    |          | observe()        |
     +--------+---------+          +--------+---------+
              |                              |
     Opportunity objects            Signal objects
              |                              |
     +--------v------------------------------v---------+
     |                  AppState                       |
     |              (state.py)                         |
     |  thread-safe: opportunities, signals, logs      |
     +--------+------------------------------+---------+
              |                              |
     +--------v---------+          +--------v---------+
     |    Notifier       |          |    FastAPI       |
     |  (notifier.py)   |          |  (web/app.py)    |
     |  console/desktop/ |          |  /api/*          |
     |  webhook          |          |  index.html      |
     +-------------------+          +------------------+
```

### Threading Model

The web app runs two threads:
- **Main thread**: FastAPI/uvicorn handling HTTP requests
- **Scanner thread**: daemon thread running the polling loop

They communicate through `AppState`, which is protected by a `threading.Lock`.
The scanner thread writes opportunities, signals, and logs; the web thread
reads snapshots of them.

---

## File-by-File Breakdown

### Core Scanner (`polymarket_scanner/`)

| File | Lines | Purpose |
|------|-------|---------|
| `client.py` | 146 | Polymarket Gamma API client. `Market` dataclass + paginated fetcher. |
| `scanner.py` | 239 | Core logic: `ScanConfig`, `Opportunity`, `evaluate_market()`, `run_forever()` |
| `signals.py` | 168 | Price-anomaly + stale-open detectors. Surfaces "news-as-price-move". |
| `notifier.py` | 90 | Console, desktop (macOS/Linux), and webhook (Discord/Slack) sinks. |
| `state.py` | 146 | Thread-safe `AppState` shared between scanner thread and web handlers. |
| `__main__.py` | 101 | CLI entry point. Loads `scanner.env`, parses args, runs scanner. |

### Web UI (`polymarket_scanner/web/`)

| File | Lines | Purpose |
|------|-------|---------|
| `app.py` | 136 | FastAPI app factory. REST endpoints for opportunities, signals, config, logs, start/stop. |
| `auth.py` | 60 | Token-based auth. Bearer header or `?token=` query param. Constant-time comparison. |
| `runner.py` | 99 | `ScannerRunner` — starts/stops the scanner as a daemon thread. |
| `config_file.py` | 95 | Reads/writes `scanner.env` from the web UI. Preserves comments on save. |
| `__main__.py` | 55 | Uvicorn entry point. Prints dashboard URL + token on startup. |
| `static/index.html` | ~350 | Single-file frontend: HTML + CSS + vanilla JS. Dark theme, 4 tabs. |

### Tests (`tests/`)

| File | Lines | Purpose |
|------|-------|---------|
| `test_scanner.py` | 122 | 11 unit tests for `evaluate_market()`. No network needed. |

### Deployment (`deploy/`)

| File | Lines | Purpose |
|------|-------|---------|
| `setup-droplet.sh` | 166 | One-command DigitalOcean/Ubuntu bootstrap. Idempotent. |
| `polymarket-scanner.service` | 28 | systemd unit. Runs as `scanner` user with hardening. |
| `Caddyfile` | 16 | Reverse proxy. IP-only (self-signed) or domain (auto Let's Encrypt). |

### macOS Scripts (`scripts/`)

| File | Lines | Purpose |
|------|-------|---------|
| `install-launchd.sh` | 131 | Installs macOS LaunchAgent. Auto-start at login. |
| `uninstall-launchd.sh` | 20 | Removes LaunchAgent + kills stray processes. |
| `logs.sh` | 12 | `tail -F` on the scanner log. |

### Root Files

| File | Purpose |
|------|---------|
| `requirements.txt` | Python deps: requests, python-dateutil, fastapi, uvicorn, pydantic |
| `scanner.env.example` | Config template with all supported environment variables |
| `Dockerfile` | Optional Docker image (python:3.12-slim) for portability |
| `.gitignore` | Excludes .venv, scanner.env, .scanner_token, logs/ |

---

## Data Flow

### 1. API Polling

`PolymarketClient.iter_active_markets()` hits Polymarket's Gamma API:

```
GET https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=200&offset=0
```

Response is a JSON array. Each row is parsed into a `Market` dataclass.
Only binary markets (exactly 2 outcome prices) are yielded.

### 2. Opportunity Evaluation

Each `Market` passes through `evaluate_market()` which checks:

```python
# 1. Market must be accepting orders and not closed
# 2. Liquidity >= min_liquidity AND volume >= min_volume
# 3. Cheapest outcome price (underdog) <= max_underdog_price
# 4. _classify() returns non-empty reasons list:
#    a. Question contains H2H pattern (vs/beat/defeat) OR watchlist hit
#    b. Category/title matches a forfeit-prone keyword (\b word boundary)
#    c. Timing: event imminent (<6h) or past end (still open)
```

### 3. Signal Detection

Separately, `PriceAnomalyWatcher.observe()` tracks price history and flags:
- **price_anomaly**: underdog price moved >= 20% between scans
- **liquidity_drop**: liquidity dropped >= 40% between scans
- **stale_open**: event past scheduled end but market still taking orders

### 4. Notification

Opportunities trigger the notifier chain (console -> desktop -> webhook).
Both opportunities and signals are stored in `AppState` for the web UI.

---

## Detection Logic

### Why Word-Boundary Matching Matters

Early version used substring matching for category keywords. This caused
"mma" to match "E**mma** Raducanu" and "Co**mma**nders". Fixed by using
`\b` regex word boundaries: `re.search(r"\bmma\b", haystack)`.

### Why Head-to-Head Is Required

"Will LNG Esports win the LPL 2026 season?" has a cheap underdog and an
esports tag, but season-winner markets don't resolve by forfeit. Forfeit
only applies to individual matches ("A vs B"). The scanner requires the
question to contain "vs", "v.", "beat", "defeat", or "win against/over"
patterns, OR a team from the user's watchlist.

### Why Timing Is Required

Without a timing gate, every esports H2H market with a cheap underdog would
fire — even ones scheduled 6 months out. The scanner requires either:
- Event starts within `imminent_window` (default 6 hours), or
- Event end time already passed but market is still open (`stale_grace`,
  default 48 hours) — this is the strongest forfeit signal.

---

## Signal System

The `PriceAnomalyWatcher` addresses the user's question: "How would the
scanner know a team dropped out without reading news?"

**Answer: news moves prices before it's published.** When insiders or fast
readers trade on a team's withdrawal announcement, the underdog price
jumps. The watcher detects this as a "price anomaly" signal even before the
scanner's next scheduled evaluation.

Signal types:
- `price_anomaly` (severity: warn at 20%, alert at 40%)
- `liquidity_drop` (severity: warn at 40%)
- `stale_open` (severity: alert — strongest forfeit indicator)

Signals are stored in a bounded deque (max 200) and surfaced in the web
UI's Signals tab independently of opportunities.

---

## Web UI

### Frontend (static/index.html)

Single HTML file with embedded CSS and vanilla JavaScript. No build step,
no framework, no npm. Dark theme optimized for trading dashboards.

**Tabs:**
- **Opportunities**: sortable table with edge %, market question (links to
  Polymarket), underdog name/price, liquidity, volume, time to end, reasons
- **Signals**: chronological feed of price anomalies and stale-open alerts
- **Config**: form with all `scanner.env` keys, save button restarts scanner
- **Logs**: scrollable pre-formatted log tail

**Polling**: fetches `/api/stats`, `/api/opportunities`, `/api/signals`
every 5 seconds. Logs fetched only when the Logs tab is visible.

### Backend (web/app.py)

FastAPI with these endpoints (all `/api/*` require auth):

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serves index.html (no auth) |
| GET | `/api/stats` | Scanner health: running, scan count, last error |
| GET | `/api/opportunities` | Current opportunity list |
| GET | `/api/signals` | Recent signals |
| GET | `/api/logs` | Log tail (default 500 lines) |
| GET | `/api/config` | Current scanner.env values |
| PUT | `/api/config` | Update scanner.env + restart scanner |
| POST | `/api/start` | Start scanner thread |
| POST | `/api/stop` | Stop scanner thread |

---

## Authentication

Simple token-based auth designed for personal use:

1. On first run, a 24-char URL-safe token is generated via `secrets.token_urlsafe(24)`
2. Token is written to `.scanner_token` (chmod 600) in the working directory
3. Override with `POLY_AUTH_TOKEN` env var or in `scanner.env`
4. Token accepted via `Authorization: Bearer <token>` header or `?token=<token>` query param
5. Comparison uses `secrets.compare_digest()` (constant-time, prevents timing attacks)
6. Frontend stores token in `localStorage`, strips it from the URL after first use

---

## Deployment Options

### Option 1: macOS (local, launchd)

```
scripts/install-launchd.sh → ~/Library/LaunchAgents/com.polymarket.scanner.plist
```
- Runs at login, restarts on crash, logs to `./logs/`
- Access via `http://127.0.0.1:8787`

### Option 2: DigitalOcean Droplet (Linux, systemd + Caddy)

```
deploy/setup-droplet.sh → /etc/systemd/system/polymarket-scanner.service
                        → /etc/caddy/Caddyfile
```
- Runs 24/7, restarts on crash/reboot
- HTTPS via Caddy reverse proxy (self-signed or Let's Encrypt)
- Dedicated `scanner` system user with hardened permissions

### Option 3: Docker (any platform)

```
docker build -t scanner .
docker run -d -p 8787:8787 -v ./scanner.env:/app/scanner.env scanner
```

---

## Configuration Reference

All settings can be placed in `scanner.env` or passed as environment variables.
The web UI's Config tab edits `scanner.env` directly.

| Variable | Default | Description |
|----------|---------|-------------|
| `POLY_WEB_HOST` | `127.0.0.1` | Web UI bind address |
| `POLY_WEB_PORT` | `8787` | Web UI port |
| `POLY_AUTH_TOKEN` | (auto-generated) | Override the auth token |
| `POLY_AUTOSTART` | `1` | Auto-start scanner when web UI launches |
| `POLY_DESKTOP` | `0` | Enable desktop notifications |
| `POLY_WEBHOOK_URL` | (empty) | Discord/Slack webhook URL |
| `POLY_WATCHLIST` | (empty) | Comma-separated team substrings |
| `POLY_MAX_PRICE` | `0.40` | Max underdog price threshold |
| `POLY_MIN_LIQUIDITY` | `500` | Min market liquidity (USDC) |
| `POLY_MIN_VOLUME` | `100` | Min 24h volume (USDC) |
| `POLY_INTERVAL` | `120` | Seconds between scans |

---

## API Reference

Base URL: `http://localhost:8787` (or your deployed URL)

All `/api/*` endpoints require authentication via:
- Header: `Authorization: Bearer <token>`
- Query: `?token=<token>`

### GET /api/stats
```json
{
  "running": true,
  "started_at": "2026-04-19T22:48:00+00:00",
  "last_scan_at": "2026-04-19T22:50:00+00:00",
  "total_scans": 5,
  "last_error": null,
  "opportunity_count": 2,
  "signal_count": 3
}
```

### GET /api/opportunities
```json
{
  "opportunities": [
    {
      "market_id": "0x...",
      "question": "FaZe vs eyeballers - winner?",
      "url": "https://polymarket.com/event/faze-eyeballers",
      "underdog_outcome": "eyeballers",
      "underdog_price": 0.20,
      "edge_pct": 1.5,
      "reasons": ["category:cs2", "past_end:30m_still_open", "h2h"],
      "liquidity": 10000,
      "volume": 5000,
      "end_date": "2026-04-19T21:00:00+00:00",
      "detected_at": "2026-04-19T22:48:00+00:00"
    }
  ]
}
```

### GET /api/signals
```json
{
  "signals": [
    {
      "kind": "price_anomaly",
      "market_id": "0x...",
      "question": "FaZe vs eyeballers",
      "url": "https://polymarket.com/event/...",
      "detail": "underdog price moved up 35% (0.200 -> 0.270)",
      "severity": "warn",
      "detected_at": "2026-04-19T22:49:00+00:00"
    }
  ]
}
```

### PUT /api/config
```json
// Request
{"POLY_WATCHLIST": "FaZe,G2,NAVI", "POLY_MAX_PRICE": "0.35"}

// Response
{"config": {"POLY_WATCHLIST": "FaZe,G2,NAVI", ...}, "scanner_restarted": true}
```

### POST /api/start / /api/stop
```json
// POST /api/start response
{"running": true, "started": true}

// POST /api/stop response
{"running": false, "stopped": true}
```
