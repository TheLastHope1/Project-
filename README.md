# Polymarket Edge Scanner

Read-only scanner for finding Polymarket markets where the displayed price,
the executable order-book price, the rules text, and timing disagree in a
potentially profitable way. The base thesis is still the forfeit/no-show
case (a 50/50 resolution makes any share bought below $0.50, after fees, a
positive-EV trade), but every alert now carries:

- a structured **rule classification** (`fifty_fifty_explicit`,
  `walkover_fifty_fifty`, `advances_if_started`, `clinching_exception`,
  `other_outcome`, `refund_void`, `unknown_explicit`, `tie_only`,
  `unsafe_ambiguous`, or `no_fallback_language`)
- the **executable order-book** snapshot (top bids/asks, depth, spread,
  tick size, min order size)
- a **depth-aware VWAP** fill price for the configured paper-trade notional
- the **official Polymarket fee** (`C × r × p × (1-p)`) for the relevant
  category, with optional per-token override from CLOB `/fee-rate`
- a **modelled EV** in cost-basis-adjusted %, replacing the old bps haircut
- a row in a **SQLite paper-trade journal** so realised PnL can be
  reconciled against the model once the underlying market resolves

## What's new in the edge-detection refactor

Compared to the previous keyword-and-bps version, the scanner has been
restructured around five new modules:

| Module | Purpose |
| --- | --- |
| `polymarket_scanner/fees.py` | Official Polymarket fee formula, per-category rates, depth-weighted VWAP, breakeven-ask solver |
| `polymarket_scanner/taxonomy.py` | Structured `FallbackRuleClass` classification of resolution rules with confidence + matched-snippet evidence |
| `polymarket_scanner/journal.py` | SQLite-backed append-only journal of opportunity snapshots, resolutions, and `/price` vs `/book` contract checks |
| `polymarket_scanner/client.py` (extended) | New `/book`, `/books`, `/fee-rate`, `/tick-size`, and `/events/keyset` paths, plus a `validate_price_side_semantics` helper |
| `polymarket_scanner/scanner.py` (extended) | Wires fees + taxonomy + book together; `Opportunity` now carries `rule_class`, `model_ev_pct`, `vwap_buy`, etc. |

## How the scanner decides

A market becomes an opportunity when it clears every layer below. If any
layer fails the market is dropped (or, with `strict_rule_class=False`,
dropped only from the alert list but still persisted for journal analysis).

1. **Active, open, accepting orders.** Closed markets are skipped.
2. **Liquidity and 24h volume floors.** Configurable; defaults to $500 / $100.
3. **Gamma screen price < `POLY_MAX_SCREEN_PRICE`.** Coarse pre-filter so we
   only pay for CLOB calls on plausible candidates.
4. **Domain match.** Either an H2H structure plus an esports/tennis/combat
   sports category keyword, or a hit on `POLY_WATCHLIST`.
5. **Timing actionable.** Event starts within `imminent_window`, or its
   scheduled end has passed within `stale_grace` but the market is still
   accepting orders (the strongest forfeit tell).
6. **Executable order book.** `/book` is fetched and becomes the
   canonical executable-price source. If `/book` is unavailable, the
   scanner falls back to `/price` (SELL = best ask, BUY = best bid).
7. **Rule classification.** `taxonomy.classify_rules` runs against the
   market's concatenated question/description/rules/resolution-source
   text and returns a `FallbackRuleClass` plus `probability_fifty`.
8. **Strict-class gate** (optional). When `POLY_STRICT_RULE_CLASS=1` the
   never-trade classes (`other_outcome`, `refund_void`, `unknown_explicit`,
   `tie_only`) are dropped.
9. **Confidence / probability gates** (optional). `POLY_MIN_RULE_CONFIDENCE`
   and `POLY_MIN_P50` are off by default; tighten them when moving from
   research to paper-trading.
10. **Final price gate.** Underdog VWAP (or top-of-book ask) ≤
    `POLY_MAX_PRICE`.
11. **Persist.** The snapshot is written to the SQLite journal with the
    book, fee rate, modelled EV, and target shares, regardless of score.

## Install

```bash
git clone -b claude/poly-market-scanner-R3RKz https://github.com/TheLastHope1/Project-.git
cd Project-
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Run

```bash
# Single scan, exit
python -m polymarket_scanner --once

# Continuous polling, default config (research mode)
python -m polymarket_scanner

# Strict mode for paper trading
python -m polymarket_scanner \
  --strict-rule-class \
  --min-rule-confidence 0.6 \
  --min-p50 0.85 \
  --use-book \
  --paper-notional 100

# Validate /price vs /book for one token (contract test)
python -m polymarket_scanner --validate-side-semantics 0xTOKEN_ID

# Realised PnL from the journal
python -m polymarket_scanner --journal-pnl

# Export the opportunities table as JSONL
python -m polymarket_scanner --journal-export out.jsonl
```

## Web UI

```bash
python -m polymarket_scanner.web
```

Open the printed URL. The dashboard surfaces:

- **Opportunities** — score, **model EV %**, **rule class** + confidence,
  ask/bid/VWAP, fee rate, P(50/50), liquidity, timing, reasons.
- **Signals** — price anomalies and stale-open markets.
- **Config** — edit `scanner.env` from the browser.
- **Logs** — live scanner output.

New endpoints:

- `GET /api/journal/pnl` — realised PnL summary by rule class.
- `GET /api/journal/latest?limit=100` — latest journal rows.
- `POST /api/validate-side-semantics?token_id=…` — runs the `/price` vs
  `/book` contract test and persists the result.

## Configuration

See [`scanner.env.example`](scanner.env.example) for the full reference.
Key new variables:

| key | meaning |
| --- | --- |
| `POLY_USE_BOOK` | `1` (default) uses `/book` as the canonical price source. |
| `POLY_USE_CLOB_FEE_RATE` | `1` fetches the per-token fee rate from CLOB. Defaults to the category heuristic in `fees.py`. |
| `POLY_FEE_RATE_OVERRIDE` | Force a single fee rate (e.g. `0.03`) for backtests. |
| `POLY_PAPER_NOTIONAL` | USDC notional per simulated entry. Drives VWAP. Default 100. |
| `POLY_STRICT_RULE_CLASS` | `1` drops never-trade classes. |
| `POLY_MIN_RULE_CONFIDENCE` | Drop candidates below this classifier confidence. |
| `POLY_MIN_P50` | Drop candidates below this modelled P(50/50). |
| `POLY_PERSIST` | `1` (default in CLI/web) writes every snapshot to the journal. |
| `POLY_JOURNAL_PATH` | SQLite file path. Default `journal.db`. Override to `/tmp/journal.db` on read-only filesystems. |
| `POLY_JOURNAL_URL` | Postgres connection string (`postgres://...`) for the durable backend. Required for Vercel / serverless. Supports Supabase, Vercel Postgres, Neon, or self-hosted. When set, takes precedence over `POLY_JOURNAL_PATH`. |

## Paper-trade workflow

The PDF review's recommended four-week protocol is supported end-to-end:

1. **Week 1 — instrumentation.** Run `python -m polymarket_scanner` with
   defaults. Use `--validate-side-semantics` against a few known tokens to
   confirm the `/price` semantics in your environment.
2. **Week 2 — taxonomy hardening.** Manually label 100–150 flagged markets
   from the dashboard. When the classifier consistently misclassifies a
   wording pattern, add a regex to `taxonomy.py` and rerun
   `python -m pytest tests/test_taxonomy.py`.
3. **Week 3 — paper-trade simulation.** Set `POLY_PAPER_NOTIONAL=100`,
   `POLY_MIN_P50=0.8`, `POLY_MIN_RULE_CONFIDENCE=0.6`. As markets resolve,
   record outcomes via `journal.record_resolution(...)` (or call the
   forthcoming `/api/journal/resolve` endpoint).
4. **Week 4 — review.** Run `python -m polymarket_scanner --journal-pnl`
   for realised PnL by rule class. Tighten thresholds based on per-class
   ROI.

## Deploy

The repo supports three deployment modes:

- **Local / VM** (recommended for research). Use the existing
  `deploy/setup-droplet.sh` script or run `python -m polymarket_scanner.web`
  under systemd / launchd.
- **Vercel serverless.** `vercel.json` sets `maxDuration=60`, redirects
  the SQLite fallback to `/tmp`, and disables autostart. Required Vercel
  environment variables:
  - `POLY_AUTH_TOKEN` — any stable random string (the dashboard auth token).
    Without this, different lambda containers see different tokens.
  - `POLY_JOURNAL_URL` — Postgres connection string (Supabase session
    pooler / Vercel Postgres / Neon). Without this, the journal lives in
    per-instance `/tmp` and is wiped on cold start.
  - `POLY_WEBHOOK_URL` (optional) — Discord/Slack webhook for alerts.

  The in-memory scanner thread does not survive between requests, so
  alerts only fire from `/api/scan-now` invocations. Wire it to Vercel
  Cron for periodic scanning.
- **Docker** via the included `Dockerfile`.

## Tests

```bash
python -m pytest tests/
```

Current local status: **68 tests passing.** Coverage includes the fee
model (breakevens for every category, depth-weighted VWAP, official-formula
parity), the rule classifier (each `FallbackRuleClass` is asserted from
real Polymarket-style rule snippets), the journal (insert/read, realised
PnL across resolutions, `/price` vs `/book` audit log, JSONL export), and
the scanner integration (book-driven EV, advancing-player rule killing
apparent edge, strict-mode gating, persistence opt-in).

## Important edge mindset

Do **not** blindly trust the scanner, the docs, the UI price, or the
market comments. Treat every alert as a research ticket:

- Is the event actually over, postponed, cancelled, forfeited, or
  unresolved?
- Does the rule classifier's class match what you read in the rules?
- Does any market in the same event carry an `Other` or `Unknown` leg?
- Is the executable VWAP still below your target after fees and slippage?
- Is there enough depth to matter? Watch `target_shares` vs
  `shares_fillable`.
- Could this resolve as refund/void instead of split/Unknown?

See [`EDGE_PLAYBOOK.md`](EDGE_PLAYBOOK.md) for the longer research
workflow and the recommendations from the PDF review.
