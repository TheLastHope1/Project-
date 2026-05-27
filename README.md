# Polymarket Edge Scanner

Read-only scanner for finding **manual-review** Polymarket situations where market
microstructure, stale timing, rule wording, and domain context may create an
edge. The original idea was a forfeit/no-show scanner. This version keeps that
thesis, but treats 50/50 settlement as a **hypothesis to test per market**, not a
rule to trust blindly.

## Core thesis

The edge is not "the docs say X". The edge is usually in the gap between:

- the displayed Gamma/outcome price,
- the executable CLOB ask/bid,
- the event's actual status and timing,
- the market's messy rule/resolution wording,
- and how slowly other traders react.

The scanner therefore works like a radar, not an autopilot. It surfaces markets
where a below-$0.50 underdog plus stale/imminent timing could make a split,
Unknown, no-contest, walkover, withdrawal, or ambiguous-resolution outcome worth
manual investigation.

## What changed in the edge-hunting version

- **CLOB executable-price enrichment:** Gamma prices are used as a broad radar,
  then candidate underdogs are probed against public CLOB BUY/SELL prices. The
  dashboard now shows screen price, ask/price, spread, source, net edge, and a
  score.
- **Outcome-price mapping fix:** blank Gamma prices no longer shift the outcome
  mapping. This prevents buying the wrong side because `outcomePrices` had a
  missing value.
- **Single-snapshot web scan:** the web runner no longer crawls Gamma twice per
  cycle. Signals and opportunities use the same market snapshot, cutting API load
  and reducing rate-limit/Cloudflare risk.
- **Rule-text sniffing:** market description/rules/resolution-source text is
  scanned for edge/danger keywords such as forfeit, no-show, no contest,
  walkover, withdrawal, cancelled, postponed, void, Unknown, refund.
- **Scored alerts:** candidates are ranked by an internal 0-100 score using stale
  market timing, watchlist hits, executable ask availability, spread, price, rule
  keywords, and net edge.
- **Research-first config:** you can keep Gamma fallback on while researching, or
  require CLOB prices once deploying seriously.

## How it decides

A market becomes an opportunity when it clears these layers:

1. Active, open, accepting orders.
2. Liquidity and 24h volume clear configured floors.
3. Gamma/display underdog price is below `POLY_MAX_SCREEN_PRICE` so it is worth
   probing.
4. It looks like a forfeit/ambiguous-resolution domain: H2H structure plus
   esports/tennis/combat-sports keywords or a watchlist hit.
5. Timing is actionable: event starts soon or scheduled end has already passed
   while the market is still open.
6. If CLOB probing is enabled, the scanner tries to replace the screen price
   with the executable BUY ask and compute net edge from that.

## Important edge mindset

Do **not** blindly trust the scanner, the docs, the UI price, or the market
comments. Treat every alert as a research ticket:

- Is the event actually over, postponed, cancelled, forfeited, or unresolved?
- Does the market wording mention what happens in cancellation/no-contest cases?
- Is there a clear resolution source?
- Is the executable ask still below your target after spread, fees, and slippage?
- Is there enough depth to matter?
- Could this resolve as refund/void instead of a split/Unknown?

See [`EDGE_PLAYBOOK.md`](EDGE_PLAYBOOK.md) for the next upgrades and research
workflow.

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

```bash
cp scanner.env.example scanner.env
```

Key settings:

| key | meaning |
| --- | --- |
| `POLY_WATCHLIST` | comma-separated teams/entities to force closer review |
| `POLY_MAX_PRICE` | final alert threshold for executable/screen underdog price |
| `POLY_MAX_SCREEN_PRICE` | broad Gamma radar threshold before CLOB probing |
| `POLY_USE_CLOB_PRICES` | `1` probes public CLOB BUY/SELL prices for candidates |
| `POLY_REQUIRE_CLOB_PRICE` | `1` drops candidates unless executable ask is fetched |
| `POLY_MAX_CLOB_PROBES` | max token IDs to probe per scan |
| `POLY_FEE_BPS` | conservative fee haircut for displayed net edge |
| `POLY_SLIPPAGE_BUFFER_BPS` | conservative slippage haircut for displayed net edge |
| `POLY_MIN_LIQUIDITY` | minimum market liquidity |
| `POLY_MIN_VOLUME` | minimum 24h volume |
| `POLY_INTERVAL` | seconds between scans |
| `POLY_WEBHOOK_URL` | Discord/Slack webhook URL |
| `POLY_DESKTOP` | `1` enables desktop notifications |

## Run

```bash
python -m polymarket_scanner --once
python -m polymarket_scanner
```

Useful research mode:

```bash
python -m polymarket_scanner \
  --max-screen-price 0.49 \
  --max-price 0.40 \
  --use-clob-prices \
  --watchlist FaZe "G2 Esports" NAVI
```

Strict deploy mode, after you know CLOB is stable from your server:

```bash
python -m polymarket_scanner \
  --require-clob-price \
  --fee-bps 0 \
  --slippage-buffer-bps 50
```

## Web UI

```bash
python -m polymarket_scanner.web
```

Open the printed URL. The dashboard shows:

- **Opportunities:** score, net edge, market, underdog, ask/price, screen price,
  spread, liquidity, timing, and reasons.
- **Signals:** price anomalies, stale-open markets, and liquidity drops.
- **Config:** edit scanner settings from browser.
- **Logs:** live scanner logs.

## Deploy

Keep it private first. Use Tailscale or an SSH tunnel. Only expose it publicly
behind HTTPS and the token gate if you really need to.

The existing Azure/VPS scripts still work, but the recommended deployment path is:

1. Run locally for a few sessions and confirm CLOB probing works.
2. Deploy to a cheap/free VM as read-only.
3. Turn on paper-trade logging before risking capital.
4. Only then consider stronger automation.

## Tests

```bash
python -m pytest tests/
```

Current local status: 15 tests passing.
