# polymarket-edge

Polymarket live-data, edge-detection, arbitrage-scanning, backtesting, paper-trading, and guarded tiny-live-trading system.

Public market data works without keys. Live trading is off by default, uses limit orders only, and remains blocked unless local risk controls, credentials, promotion checks, and manual confirmation all pass. Real money can be lost. Use paper trading first, and never commit `.env.local`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env.local
docker compose up -d postgres
```

## Paper-First Runbook

```bash
python -m polymarket_edge.cli init-db
python -m polymarket_edge.cli discover-markets --max-events 500
python -m polymarket_edge.cli poll-orderbooks --once
python -m polymarket_edge.cli scan-binary-arb
python -m polymarket_edge.cli scan-edges --latest
python -m polymarket_edge.cli paper-trade --from-latest-edges
python -m polymarket_edge.cli backtest --holding-period 3600
python -m polymarket_edge.cli dashboard
```

## Optional Trading Setup

Run these only after paper trading works:

```bash
python -m polymarket_edge.cli setup-secrets
python -m polymarket_edge.cli derive-api-creds
python -m polymarket_edge.cli auth-check
python -m polymarket_edge.cli balances
python -m polymarket_edge.cli promotion-check
python -m polymarket_edge.cli live-preflight
python -m polymarket_edge.cli live-tiny --once
```

`live-tiny --once` places at most one manually confirmed limit order, and only after `live-preflight` and `RiskManager` pass. With the default `.env.local`, live commands fail closed and place no orders.

## Safety Commands

```bash
python -m polymarket_edge.cli kill-switch
python -m polymarket_edge.cli disable-live
python -m polymarket_edge.cli check-secrets
```

`check-secrets` reports present/missing status only and redacts sensitive values.

## Local API

The deployable API is separate from the local Streamlit dashboard:

```bash
uvicorn polymarket_edge.web.app:app --host 127.0.0.1 --port 8000
```

Public read-only endpoints:

- `GET /health`
- `GET /api/status`
- `GET /api/edges`
- `GET /api/binary-arb`
- `GET /api/paper-orders`
- `GET /api/live-preflight`

Admin endpoints require `POLYMARKET_EDGE_API_TOKEN` as `Authorization: Bearer ...`, `x-api-token`, or `?token=...`. If the token is unset, admin endpoints return `503`.

## Vercel + Supabase Deployment

Use Supabase Postgres for `DATABASE_URL` and Vercel for the FastAPI serverless entrypoint at `api/index.py`. Keep live trading disabled in hosted environments until paper-trading promotion checks pass and credentials are configured intentionally.

Minimum Vercel environment variables:

```text
DATABASE_URL=postgresql+psycopg://...
POLYMARKET_EDGE_API_TOKEN=<generated-admin-token>
DATA_MODE=public
TRADING_MODE=paper
LIVE_TRADING_ENABLED=false
REAL_MONEY_ACKNOWLEDGED=false
ALLOW_MARKET_ORDERS=false
```

Generate the admin token with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

After deployment, initialize and refresh the hosted database through token-protected admin calls, or run the CLI locally against the Supabase `DATABASE_URL`. Never put Polymarket private keys, API secrets, or wallet seed phrases in frontend-visible variables.

## Legacy Scanner

The original read-only scanner remains available:

```bash
python -m polymarket_scanner --once
python -m polymarket_scanner.web
```
