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

# Risk management
MAX_BET_SIZE = 20.0          # Max USDC per trade
MIN_BET_SIZE = 5.0           # Min USDC per trade
MAX_CONCURRENT_POSITIONS = 4
MAX_TOTAL_EXPOSURE = 60.0    # Max USDC in open positions
MAX_DAILY_LOSS = 50.0        # Stop trading if daily loss exceeds this
DAILY_TRADE_LIMIT = 100
KELLY_FRACTION = 0.25        # Quarter-Kelly for position sizing

# Strategy parameters
MIN_EDGE_THRESHOLD = 0.10    # 10% minimum edge to enter a trade
ENTRY_SECONDS_BEFORE_CLOSE = 45  # Enter at T-45s before window closes
LATEST_ENTRY_SECONDS = 10       # Don't enter after T-10s
LOOKBACK_CANDLES = 30           # 30 x 1-min candles for momentum
EMA_FAST_PERIOD = 5
EMA_SLOW_PERIOD = 15
COOLDOWN_SECONDS = 60           # Min seconds between trades

# Timing
SCAN_INTERVAL_SECONDS = 30      # How often to check for opportunities
MARKET_WINDOW_SECONDS = 300     # 5-minute market windows

# Dry run mode (paper trading)
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
