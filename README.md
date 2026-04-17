# Polymarket BTC 5-Minute Trading Bot

An autonomous trading bot that trades Bitcoin 5-minute binary outcome markets on Polymarket. The bot analyzes BTC price momentum, detects edges against market odds, and executes trades with built-in risk management.

## How It Works

1. **Market Discovery** - Finds active BTC 5-minute markets on Polymarket (e.g., "Will BTC be above $84,500 at 14:05 UTC?")
2. **Price Analysis** - Fetches real-time BTC price from Binance + computes momentum indicators (EMA, RSI, volatility)
3. **Edge Detection** - Compares our probability estimate against Polymarket's implied odds. Trades only when edge > 10%
4. **Risk Management** - Quarter-Kelly position sizing, daily loss limits, exposure caps
5. **Execution** - Places Fill-or-Kill market orders via Polymarket CLOB API

The bot enters positions at T-45 seconds before each 5-minute window closes, when the current BTC price is most predictive of the outcome.

## Setup

### 1. Prerequisites

- Python 3.10+
- A Polymarket account with funds (USDC on Polygon)
- A wallet private key connected to your Polymarket account

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Credentials

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:

```env
# Required: Your Polygon wallet private key (the one linked to your Polymarket account)
PRIVATE_KEY=0x...

# Optional: API credentials (will be auto-derived from private key if not provided)
POLYMARKET_API_KEY=
POLYMARKET_API_SECRET=
POLYMARKET_API_PASSPHRASE=

# Optional: Funder address for proxy wallets
POLYMARKET_FUNDER_ADDRESS=
```

### 4. Getting Your Credentials

**Private Key:**
- If using MetaMask: Settings > Security & Privacy > Reveal Secret Recovery Phrase, then derive the private key
- If using Polymarket's embedded wallet: Export from your account settings
- This must be the wallet that holds your USDC on Polygon and is connected to Polymarket

**API Key/Secret (Optional):**
- The bot can derive these automatically from your private key
- Or generate them manually at polymarket.com account settings

## Usage

### Paper Trading (Dry Run - Default)

```bash
python run.py
```

This simulates trades without using real money. Use this to verify the bot works correctly before going live.

### Live Trading

```bash
python run.py --live
```

**WARNING:** This uses real money. Start with a small amount and monitor closely.

## Configuration

Key parameters in `config.py`:

| Parameter | Default | Description |
|---|---|---|
| `STARTING_CAPITAL` | $150 | Starting USDC balance |
| `MAX_BET_SIZE` | $20 | Maximum per-trade bet |
| `MIN_BET_SIZE` | $5 | Minimum per-trade bet |
| `MIN_EDGE_THRESHOLD` | 10% | Minimum edge to trigger a trade |
| `MAX_DAILY_LOSS` | $50 | Stop trading after this daily loss |
| `MAX_CONCURRENT_POSITIONS` | 4 | Max open positions at once |
| `MAX_TOTAL_EXPOSURE` | $60 | Max USDC in open positions |
| `KELLY_FRACTION` | 0.25 | Quarter-Kelly position sizing |
| `DRY_RUN` | true | Paper trading mode (env var) |

## Project Structure

```
config.py              - Configuration and environment variables
polymarket_client.py   - Polymarket CLOB API client wrapper
market_scanner.py      - BTC 5-minute market discovery
price_feed.py          - Real-time BTC price from Binance
strategy.py            - Trading signal generation and edge detection
risk_manager.py        - Position sizing and risk gates
executor.py            - Order placement via CLOB
tracker.py             - P&L tracking and trade history
bot.py                 - Main autonomous trading loop
run.py                 - Entry point with CLI arguments
```

## Risk Disclaimer

This bot trades with real money. Cryptocurrency markets are volatile and prediction markets carry additional risk. There is no guarantee of profit. Only trade with money you can afford to lose. Past performance does not indicate future results.
