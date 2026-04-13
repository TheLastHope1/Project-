import logging
import time
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
import config

logger = logging.getLogger("polymarket_bot.client")


class PolymarketClient:
    """Wrapper around py-clob-client for Polymarket CLOB API."""

    def __init__(self):
        self.client = None
        self.api_creds = None

    def initialize(self):
        """Set up the CLOB client with authentication."""
        if not config.PRIVATE_KEY:
            raise ValueError(
                "PRIVATE_KEY not set. Copy .env.example to .env and fill in credentials."
            )

        logger.info("Initializing Polymarket CLOB client...")
        self.client = ClobClient(
            host=config.CLOB_API_URL,
            key=config.PRIVATE_KEY,
            chain_id=config.CHAIN_ID,
        )

        # Derive or use provided API credentials
        if config.POLYMARKET_API_KEY and config.POLYMARKET_API_SECRET:
            self.api_creds = ApiCreds(
                api_key=config.POLYMARKET_API_KEY,
                api_secret=config.POLYMARKET_API_SECRET,
                api_passphrase=config.POLYMARKET_API_PASSPHRASE,
            )
            self.client.set_api_creds(self.api_creds)
            logger.info("Using provided API credentials.")
        else:
            logger.info("Deriving API credentials from private key...")
            self.api_creds = self.client.create_or_derive_api_creds()
            self.client.set_api_creds(self.api_creds)
            logger.info("API credentials derived successfully.")

        # Set funder address if provided (for proxy wallets)
        if config.POLYMARKET_FUNDER_ADDRESS:
            self.client.set_funder(config.POLYMARKET_FUNDER_ADDRESS)

        # Verify connectivity
        if not self._check_connection():
            raise ConnectionError("Failed to connect to Polymarket CLOB API.")

        logger.info("Polymarket client initialized successfully.")

    def _check_connection(self) -> bool:
        """Verify the CLOB API is reachable."""
        for attempt in range(3):
            try:
                resp = self.client.get_ok()
                if resp == "OK":
                    return True
            except Exception as e:
                logger.warning(f"Connection check attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
        return False

    def get_order_book(self, token_id: str) -> dict:
        """Fetch the order book for a token."""
        try:
            return self.client.get_order_book(token_id)
        except Exception as e:
            logger.error(f"Failed to get order book for {token_id}: {e}")
            return {}

    def get_midpoint(self, token_id: str) -> float:
        """Get the midpoint price for a token."""
        try:
            mid = self.client.get_midpoint(token_id)
            return float(mid) if mid else 0.0
        except Exception as e:
            logger.error(f"Failed to get midpoint for {token_id}: {e}")
            return 0.0

    def get_price(self, token_id: str, side: str) -> float:
        """Get the best price for a side (BUY/SELL)."""
        try:
            price = self.client.get_price(token_id, side)
            return float(price) if price else 0.0
        except Exception as e:
            logger.error(f"Failed to get price for {token_id} {side}: {e}")
            return 0.0

    def get_last_trade_price(self, token_id: str) -> float:
        """Get the last trade price for a token."""
        try:
            price = self.client.get_last_trade_price(token_id)
            return float(price) if price else 0.0
        except Exception as e:
            logger.error(f"Failed to get last trade price for {token_id}: {e}")
            return 0.0

    def get_client(self) -> ClobClient:
        """Return the raw ClobClient instance for direct use."""
        return self.client
