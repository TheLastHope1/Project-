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
MAX_BET_SIZE = 30.0          # Max USDC per trade
MIN_BET_SIZE = 5.0           # Min USDC per trade
MAX_CONCURRENT_POSITIONS = 3 # One per window is enforced separately
MAX_BET_FRACTION = 0.20      # Max 20% of capital per trade
KELLY_FRACTION = 0.25        # Quarter-Kelly - tape-following is new, stay humble

# Compounding: trade sizes grow with capital
COMPOUND_PROFITS = True       # Reinvest all profits into larger trades
GROWTH_TARGET_DAILY = 0.10    # Target 10% daily growth (informational)

# Strategy parameters
MIN_EDGE_THRESHOLD = 0.08    # 8% min edge (tape must clearly beat market)
ENTRY_SECONDS_BEFORE_CLOSE = 45  # Enter in final 45s - tape is most reliable late
LATEST_ENTRY_SECONDS = 10       # Don't enter after T-10s
LOOKBACK_CANDLES = 30           # 30 x 1-min candles for momentum
EMA_FAST_PERIOD = 5
EMA_SLOW_PERIOD = 15
COOLDOWN_SECONDS = 0            # No cooldown - trade every window

# Timing
SCAN_INTERVAL_SECONDS = 15      # Check more frequently for opportunities
MARKET_WINDOW_SECONDS = 300     # 5-minute market windows

# Dry run mode (paper trading)
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
