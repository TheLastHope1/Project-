import os
from dotenv import load_dotenv

load_dotenv()

# ── Polymarket Credentials ──────────────────────────────────────────
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", "")
POLYMARKET_API_SECRET = os.getenv("POLYMARKET_API_SECRET", "")
POLYMARKET_API_PASSPHRASE = os.getenv("POLYMARKET_API_PASSPHRASE", "")
POLYMARKET_FUNDER_ADDRESS = os.getenv("POLYMARKET_FUNDER_ADDRESS", "")

# ── API Endpoints ───────────────────────────────────────────────────
CLOB_API_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"
BINANCE_API_URL = "https://api.binance.com"
CHAIN_ID = 137  # Polygon mainnet

# ── Trading Parameters ──────────────────────────────────────────────
STARTING_CAPITAL = 150.0

# Risk management - small & frequent: spread risk across many bets
MAX_BET_SIZE = 12.0          # Max USDC per trade (hard ceiling)
MIN_BET_SIZE = 3.0           # Min USDC per trade (above Polymarket's $1 floor)
MAX_CONCURRENT_POSITIONS = 6 # More concurrent because each is smaller
MAX_BET_FRACTION = 0.05      # Max 5% of capital per trade - diversify across windows
KELLY_FRACTION = 0.20        # Fifth-Kelly - keeps sizing conservative

# Compounding: trade sizes grow with capital
COMPOUND_PROFITS = True       # Reinvest all profits into larger trades
GROWTH_TARGET_DAILY = 0.10    # Target 10% daily growth (informational)

# Strategy parameters - looser filters to catch more tradeable windows
MIN_EDGE_THRESHOLD = 0.06    # 6% min edge (smaller bets tolerate slimmer edges)
ENTRY_SECONDS_BEFORE_CLOSE = 60  # Wider entry window -> more opportunities
LATEST_ENTRY_SECONDS = 8        # Don't enter after T-8s
# Only take the "winning" side when its price is in this band.
# Below MIN: market disagrees with the tape - don't fight it.
# Above MAX: upside too small - one loss wipes out too many wins.
MIN_TAKE_PRICE = 0.50
MAX_TAKE_PRICE = 0.88
LOOKBACK_CANDLES = 30           # 30 x 1-min candles for momentum
EMA_FAST_PERIOD = 5
EMA_SLOW_PERIOD = 15
COOLDOWN_SECONDS = 0            # No cooldown - trade every window

# Timing
SCAN_INTERVAL_SECONDS = 15      # Check more frequently for opportunities
MARKET_WINDOW_SECONDS = 300     # 5-minute market windows

# Dry run mode (paper trading)
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
