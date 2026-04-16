import logging
import time
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON
from eth_account import Account
import config

# Signature type 1 = POLY_PROXY       (older browser-wallet proxy).
# Signature type 2 = POLY_GNOSIS_SAFE  (Polymarket email signup - Magic.link).
# Signature type 0 = EOA               (raw wallet, no proxy).
# Most accounts today are Gnosis Safe (type 2). If orders fail with
# "invalid signature", the type does not match the on-chain contract.
SIG_TYPE_POLY_PROXY = 1
SIG_TYPE_POLY_GNOSIS_SAFE = 2

# USDC on Polygon has 6 decimals.
USDC_DECIMALS = 6

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

        # Startup diagnostics for "invalid signature" debugging. Derive the
        # signer EOA from PRIVATE_KEY so the user can cross-check it against
        # Polymarket's "Signer Address" in account settings. If these two
        # don't match, orders will always be rejected with "invalid signature"
        # because the proxy funder is bound to a different signer.
        try:
            from eth_account import Account  # ships with py-clob-client
            signer_address = Account.from_key(config.PRIVATE_KEY).address
            logger.info(f"Signer EOA (from PRIVATE_KEY): {signer_address}")
            logger.info(
                f"Funder address              : "
                f"{config.POLYMARKET_FUNDER_ADDRESS or '(same as signer - EOA mode)'}"
            )
            if (
                config.POLYMARKET_FUNDER_ADDRESS
                and signer_address.lower()
                == config.POLYMARKET_FUNDER_ADDRESS.lower()
            ):
                logger.warning(
                    "Signer EOA == funder with signature_type=%d. For a "
                    "proxy wallet these SHOULD be different addresses. "
                    "Check Polymarket Settings -> Signer Address.",
                    config.POLYMARKET_SIGNATURE_TYPE,
                )
        except Exception as e:
            logger.warning(f"Could not derive signer EOA for diagnostics: {e}")

        try:
            from importlib.metadata import version as _pkgv
            logger.info(f"py-clob-client version: {_pkgv('py-clob-client')}")
        except Exception:
            pass

        # If a funder address is provided, we're using a Polymarket proxy
        # wallet (either Gnosis Safe from email signup, or the older
        # POLY_PROXY from browser signup). The signature_type must match
        # the actual contract behind your funder address; otherwise
        # Polymarket rejects every order with "invalid signature".
        # Derive the EOA address from the private key and log it.
        # Cross-check this against Polymarket Settings → Signer Address.
        # If they differ, the wrong private key is in .env.
        signer_eoa = Account.from_key(config.PRIVATE_KEY).address
        try:
            from importlib.metadata import version as _pkgv
            clob_ver = _pkgv("py-clob-client")
        except Exception:
            clob_ver = "unknown"
        logger.info(f"py-clob-client version          : {clob_ver}")
        logger.info(f"Signer EOA (from PRIVATE_KEY)   : {signer_eoa}")

        if config.POLYMARKET_FUNDER_ADDRESS:
            sig_type = config.POLYMARKET_SIGNATURE_TYPE
            sig_name = {
                0: "EOA",
                1: "POLY_PROXY",
                2: "POLY_GNOSIS_SAFE",
            }.get(sig_type, f"UNKNOWN({sig_type})")
            logger.info(
                f"Funder address                  : {config.POLYMARKET_FUNDER_ADDRESS}"
            )
            logger.info(
                f"Signature type                  : {sig_type} ({sig_name})"
            )
            if signer_eoa.lower() == config.POLYMARKET_FUNDER_ADDRESS.lower():
                logger.warning(
                    "Signer EOA == funder address. For a proxy wallet (type 1/2) "
                    "the signer should be DIFFERENT from the funder. If orders fail "
                    "with 'invalid signature', re-export the key that Polymarket "
                    "lists as the Signer Address on your account settings page."
                )
            self.client = ClobClient(
                host=config.CLOB_API_URL,
                key=config.PRIVATE_KEY,
                chain_id=config.CHAIN_ID,
                signature_type=sig_type,
                funder=config.POLYMARKET_FUNDER_ADDRESS,
            )
        else:
            # Raw EOA wallet (private key IS the funder).
            logger.info(
                f"Funder address                  : (same as signer — EOA mode)"
            )
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

    @staticmethod
    def _extract_price(resp, *keys) -> float:
        """py-clob-client >=0.34 returns dicts like {"mid": "0.5"} or
        {"price": "0.5"}. Older versions returned the raw string. Handle both."""
        if resp is None:
            return 0.0
        if isinstance(resp, dict):
            for k in keys:
                if k in resp and resp[k] is not None:
                    try:
                        return float(resp[k])
                    except (TypeError, ValueError):
                        return 0.0
            return 0.0
        try:
            return float(resp)
        except (TypeError, ValueError):
            return 0.0

    def get_midpoint(self, token_id: str) -> float:
        """Get the midpoint price for a token."""
        try:
            resp = self.client.get_midpoint(token_id)
            return self._extract_price(resp, "mid", "midpoint", "price")
        except Exception as e:
            logger.error(f"Failed to get midpoint for {token_id}: {e}")
            return 0.0

    def get_price(self, token_id: str, side: str) -> float:
        """Get the best price for a side (BUY/SELL)."""
        try:
            resp = self.client.get_price(token_id, side)
            return self._extract_price(resp, "price", "mid")
        except Exception as e:
            logger.error(f"Failed to get price for {token_id} {side}: {e}")
            return 0.0

    def get_last_trade_price(self, token_id: str) -> float:
        """Get the last trade price for a token."""
        try:
            resp = self.client.get_last_trade_price(token_id)
            return self._extract_price(resp, "price", "mid")
        except Exception as e:
            logger.error(f"Failed to get last trade price for {token_id}: {e}")
            return 0.0

    def get_client(self) -> ClobClient:
        """Return the raw ClobClient instance for direct use."""
        return self.client

    def get_usdc_balance(self) -> float:
        """
        Fetch the live USDC (collateral) balance from Polymarket.

        Returns the balance in USDC (not wei). Returns -1.0 on failure so
        callers can distinguish a failed fetch from a genuine zero balance.
        """
        try:
            # Import lazily so the module still loads if py-clob-client is
            # missing these types (older versions).
            from py_clob_client.clob_types import (
                BalanceAllowanceParams,
                AssetType,
            )

            params = BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=(
                    config.POLYMARKET_SIGNATURE_TYPE
                    if config.POLYMARKET_FUNDER_ADDRESS
                    else 0
                ),
            )
            resp = self.client.get_balance_allowance(params)
            if not resp:
                return -1.0

            raw = resp.get("balance", "0") if isinstance(resp, dict) else "0"
            try:
                wei = int(raw)
            except (TypeError, ValueError):
                return -1.0
            return wei / (10 ** USDC_DECIMALS)

        except ImportError:
            logger.warning(
                "BalanceAllowanceParams not available in this py-clob-client "
                "version; cannot fetch live balance."
            )
            return -1.0
        except Exception as e:
            logger.warning(f"Failed to fetch USDC balance: {e}")
            return -1.0
