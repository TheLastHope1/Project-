import logging
import time
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON
from eth_account import Account
import config

USDC_DECIMALS = 6

logger = logging.getLogger("polymarket_bot.client")


def _get_balance_with_sig_type(client: ClobClient, sig_type: int) -> float:
    """Try fetching USDC balance with a specific signature type. Returns -1 on failure."""
    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        params = BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
            signature_type=sig_type,
        )
        resp = client.get_balance_allowance(params)
        if not resp:
            return -1.0
        raw = resp.get("balance", "0") if isinstance(resp, dict) else "0"
        return int(raw) / (10 ** USDC_DECIMALS)
    except Exception:
        return -1.0


class PolymarketClient:
    """Wrapper around py-clob-client for Polymarket CLOB API."""

    def __init__(self):
        self.client = None
        self.api_creds = None
        self.effective_sig_type = None

    def initialize(self):
        """Set up the CLOB client with authentication."""
        if not config.PRIVATE_KEY:
            raise ValueError(
                "PRIVATE_KEY not set. Copy .env.example to .env and fill in credentials."
            )

        logger.info("Initializing Polymarket CLOB client...")

        signer_eoa = Account.from_key(config.PRIVATE_KEY).address
        try:
            from importlib.metadata import version as _pkgv
            clob_ver = _pkgv("py-clob-client")
        except Exception:
            clob_ver = "unknown"

        logger.info(f"py-clob-client version : {clob_ver}")
        logger.info(f"Signer EOA (PRIVATE_KEY): {signer_eoa}")
        logger.info(f"Funder address          : {config.POLYMARKET_FUNDER_ADDRESS or '(same as signer)'}")

        if config.POLYMARKET_FUNDER_ADDRESS:
            if signer_eoa.lower() == config.POLYMARKET_FUNDER_ADDRESS.lower():
                logger.warning(
                    "Signer EOA == funder address. For proxy wallets the "
                    "signer should be DIFFERENT from the funder."
                )

            sig_type = self._auto_detect_sig_type(signer_eoa)
            self.effective_sig_type = sig_type

            sig_name = {0: "EOA", 1: "POLY_PROXY", 2: "POLY_GNOSIS_SAFE"}.get(
                sig_type, f"UNKNOWN({sig_type})"
            )
            logger.info(f"Signature type          : {sig_type} ({sig_name})")

            self.client = ClobClient(
                host=config.CLOB_API_URL,
                key=config.PRIVATE_KEY,
                chain_id=config.CHAIN_ID,
                signature_type=sig_type,
                funder=config.POLYMARKET_FUNDER_ADDRESS,
            )
        else:
            self.effective_sig_type = 0
            logger.info("Signature type          : 0 (EOA — no proxy)")
            self.client = ClobClient(
                host=config.CLOB_API_URL,
                key=config.PRIVATE_KEY,
                chain_id=config.CHAIN_ID,
            )

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

        if not self._check_connection():
            raise ConnectionError("Failed to connect to Polymarket CLOB API.")

        logger.info("Polymarket client initialized successfully.")

    def _auto_detect_sig_type(self, signer_eoa: str) -> int:
        """Try signature types 0, 1, 2 and pick whichever returns a real balance.

        This eliminates the most common setup mistake — users selecting the
        wrong signature type in .env and seeing $0 balance forever.
        """
        configured = config.POLYMARKET_SIGNATURE_TYPE
        candidates = [configured] + [t for t in (1, 2, 0) if t != configured]

        # We need a temporary client just to probe balance.
        for sig_type in candidates:
            try:
                probe = ClobClient(
                    host=config.CLOB_API_URL,
                    key=config.PRIVATE_KEY,
                    chain_id=config.CHAIN_ID,
                    signature_type=sig_type,
                    funder=config.POLYMARKET_FUNDER_ADDRESS,
                )
                # Derive creds so the probe can authenticate.
                creds = probe.create_or_derive_api_creds()
                probe.set_api_creds(creds)

                balance = _get_balance_with_sig_type(probe, sig_type)
                sig_name = {0: "EOA", 1: "POLY_PROXY", 2: "POLY_GNOSIS_SAFE"}.get(
                    sig_type, str(sig_type)
                )
                if balance > 0:
                    if sig_type != configured:
                        logger.warning(
                            f"Auto-detected signature_type={sig_type} ({sig_name}) "
                            f"— balance ${balance:.2f}. Your .env says type "
                            f"{configured}, which returned $0. Using {sig_type} instead."
                        )
                    else:
                        logger.info(
                            f"Confirmed signature_type={sig_type} ({sig_name}) "
                            f"— balance ${balance:.2f}"
                        )
                    return sig_type
            except Exception as e:
                logger.debug(f"Probe sig_type={sig_type} failed: {e}")
                continue

        logger.warning(
            f"Could not auto-detect signature type (all returned $0). "
            f"Falling back to configured type {configured}."
        )
        return configured

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
        try:
            resp = self.client.get_midpoint(token_id)
            return self._extract_price(resp, "mid", "midpoint", "price")
        except Exception as e:
            logger.error(f"Failed to get midpoint for {token_id}: {e}")
            return 0.0

    def get_price(self, token_id: str, side: str) -> float:
        try:
            resp = self.client.get_price(token_id, side)
            return self._extract_price(resp, "price", "mid")
        except Exception as e:
            logger.error(f"Failed to get price for {token_id} {side}: {e}")
            return 0.0

    def get_last_trade_price(self, token_id: str) -> float:
        try:
            resp = self.client.get_last_trade_price(token_id)
            return self._extract_price(resp, "price", "mid")
        except Exception as e:
            logger.error(f"Failed to get last trade price for {token_id}: {e}")
            return 0.0

    def get_client(self) -> ClobClient:
        return self.client

    def get_usdc_balance(self) -> float:
        """Fetch the live USDC balance. Returns -1.0 on failure."""
        sig_type = self.effective_sig_type if self.effective_sig_type is not None else (
            config.POLYMARKET_SIGNATURE_TYPE if config.POLYMARKET_FUNDER_ADDRESS else 0
        )
        return _get_balance_with_sig_type(self.client, sig_type)
