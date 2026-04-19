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

## Run 24/7 in the background (macOS)

Install a launchd user agent so the scanner starts at login, restarts on
crash, and writes logs to `logs/scanner.log`:

```bash
./scripts/install-launchd.sh
```

Managing the agent:

```bash
./scripts/logs.sh                # tail the log live (Ctrl+C to stop tailing)
launchctl list | grep polymarket # check status
./scripts/uninstall-launchd.sh   # stop and remove
```

Config changes (`scanner.env` edits) take effect after re-running
`install-launchd.sh`, which reloads the agent with the new values.

## Layout

```
polymarket_scanner/
  client.py          # Gamma API client + Market dataclass
  scanner.py         # evaluate_market, scan_once, run_forever, ScanConfig
  notifier.py        # console / desktop / webhook sinks
  __main__.py        # CLI entry point + scanner.env loader
scripts/
  install-launchd.sh
  uninstall-launchd.sh
  logs.sh
tests/
  test_scanner.py
scanner.env.example  # copy to scanner.env and edit
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
