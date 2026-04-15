import logging
import time
from dataclasses import dataclass
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

import config

# py-clob-client >=0.15 ships PartialCreateOrderOptions which is how you
# tell the builder to sign for the Neg Risk CTF Exchange instead of the
# regular CTF Exchange. Not all installed versions have it - we detect
# lazily and fall back if missing.
try:
    from py_clob_client.clob_types import PartialCreateOrderOptions  # type: ignore
except Exception:  # pragma: no cover
    PartialCreateOrderOptions = None  # type: ignore

logger = logging.getLogger("polymarket_bot.executor")


@dataclass
class OrderResult:
    """Result of an order placement attempt."""
    success: bool
    order_id: Optional[str] = None
    fill_price: Optional[float] = None
    fill_size: Optional[float] = None
    cost: Optional[float] = None
    error: Optional[str] = None


class OrderExecutor:
    """Handles order placement and management via Polymarket CLOB."""

    def __init__(self, clob_client: ClobClient, dry_run: bool = True):
        self.client = clob_client
        self.dry_run = dry_run

    def place_market_order(
        self,
        token_id: str,
        amount: float,
        neg_risk: bool = False,
    ) -> OrderResult:
        """
        Place a Fill-or-Kill market order to buy tokens.

        Args:
            token_id: The token to buy (YES or NO token ID)
            amount: USDC amount to spend
            neg_risk: True if this market lives on Polymarket's Neg Risk
                CTF Exchange (e.g. the 5-min BTC up/down series). Orders
                for neg-risk markets must be signed against that
                contract's EIP-712 domain or the server rejects them
                with "invalid signature".

        If the first attempt is rejected with "invalid signature", we
        retry ONCE with the opposite neg_risk flag - this self-corrects
        when Gamma's metadata lies about which exchange hosts the
        market.
        """
        if self.dry_run:
            return self._simulate_market_order(token_id, amount)

        result = self._try_market_order(token_id, amount, neg_risk)
        if (
            not result.success
            and result.error
            and "invalid signature" in result.error.lower()
        ):
            logger.warning(
                f"Retrying with neg_risk={not neg_risk} "
                f"after 'invalid signature'."
            )
            result = self._try_market_order(token_id, amount, not neg_risk)
        return result

    def _try_market_order(
        self, token_id: str, amount: float, neg_risk: bool
    ) -> OrderResult:
        """One attempt at placing a market order. Returns an OrderResult."""
        try:
            logger.info(
                f"Placing market order: BUY {token_id[:8]}... for "
                f"${amount:.2f}"
                + (" [neg_risk]" if neg_risk else "")
            )

            order_args = MarketOrderArgs(
                token_id=token_id,
                amount=amount,
                side=BUY,
            )

            if neg_risk and PartialCreateOrderOptions is not None:
                options = PartialCreateOrderOptions(neg_risk=True)
                signed_order = self.client.create_market_order(
                    order_args, options=options
                )
            else:
                signed_order = self.client.create_market_order(order_args)
            result = self.client.post_order(signed_order, OrderType.FOK)

            if result and result.get("success"):
                order_id = result.get("orderID", "unknown")
                logger.info(f"Market order filled. Order ID: {order_id}")
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    cost=amount,
                )
            else:
                error_msg = result.get("errorMsg", "Unknown error") if result else "No response"
                logger.warning(f"Market order failed: {error_msg}")
                return OrderResult(success=False, error=error_msg)

        except Exception as e:
            msg = str(e)
            # Let the caller decide what to do with "invalid signature"
            # (place_market_order retries once with flipped neg_risk).
            if "invalid signature" not in msg.lower():
                logger.error(f"Market order exception: {e}")
            return OrderResult(success=False, error=msg)

    def place_limit_order(
        self, token_id: str, price: float, size: float
    ) -> OrderResult:
        """
        Place a Good-Till-Cancelled limit order.

        Args:
            token_id: The token to buy
            price: Limit price (0.01 - 0.99)
            size: Number of shares to buy
        """
        if self.dry_run:
            return self._simulate_limit_order(token_id, price, size)

        try:
            logger.info(
                f"Placing limit order: BUY {size:.1f} shares of "
                f"{token_id[:8]}... @ ${price:.2f}"
            )

            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=BUY,
            )

            signed_order = self.client.create_order(order_args)
            result = self.client.post_order(signed_order, OrderType.GTC)

            if result and result.get("success"):
                order_id = result.get("orderID", "unknown")
                logger.info(f"Limit order placed. Order ID: {order_id}")
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    fill_price=price,
                    fill_size=size,
                    cost=price * size,
                )
            else:
                error_msg = result.get("errorMsg", "Unknown error") if result else "No response"
                logger.warning(f"Limit order failed: {error_msg}")
                return OrderResult(success=False, error=error_msg)

        except Exception as e:
            logger.error(f"Limit order exception: {e}")
            return OrderResult(success=False, error=str(e))

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would cancel order {order_id}")
            return True

        try:
            result = self.client.cancel(order_id)
            success = bool(result)
            if success:
                logger.info(f"Order {order_id} cancelled.")
            else:
                logger.warning(f"Failed to cancel order {order_id}")
            return success
        except Exception as e:
            logger.error(f"Cancel order exception: {e}")
            return False

    def cancel_all_orders(self) -> bool:
        """Cancel all open orders."""
        if self.dry_run:
            logger.info("[DRY RUN] Would cancel all orders")
            return True

        try:
            result = self.client.cancel_all()
            logger.info(f"Cancel all orders result: {result}")
            return True
        except Exception as e:
            logger.error(f"Cancel all orders exception: {e}")
            return False

    def _simulate_market_order(self, token_id: str, amount: float) -> OrderResult:
        """Simulate a market order in dry-run mode."""
        sim_id = f"dry-run-{int(time.time())}"
        logger.info(
            f"[DRY RUN] Market order: BUY {token_id[:8]}... "
            f"for ${amount:.2f} | Order ID: {sim_id}"
        )
        return OrderResult(
            success=True,
            order_id=sim_id,
            cost=amount,
        )

    def _simulate_limit_order(
        self, token_id: str, price: float, size: float
    ) -> OrderResult:
        """Simulate a limit order in dry-run mode."""
        sim_id = f"dry-run-{int(time.time())}"
        logger.info(
            f"[DRY RUN] Limit order: BUY {size:.1f} @ ${price:.2f} "
            f"{token_id[:8]}... | Order ID: {sim_id}"
        )
        return OrderResult(
            success=True,
            order_id=sim_id,
            fill_price=price,
            fill_size=size,
            cost=price * size,
        )
