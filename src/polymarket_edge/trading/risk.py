from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from polymarket_edge.config import Settings, get_settings
from polymarket_edge.db.models import RiskEvent


@dataclass(frozen=True)
class OrderIntent:
    order_type: str
    side: str
    price: float
    size: float
    token_id: str
    market_id: str
    client_order_id: str | None
    strategy_id: str | None

    @property
    def notional(self) -> float:
        return abs(float(self.price) * float(self.size))


@dataclass(frozen=True)
class MarketState:
    spread: float
    sigma: float
    staleness_seconds: float
    token_stale: bool = False
    active: bool = True
    closed: bool = False
    max_slippage_price: float | None = None


@dataclass(frozen=True)
class AccountState:
    market_exposure_after: float = 0.0
    open_exposure_after: float = 0.0
    daily_volume_after: float = 0.0
    daily_realized_pnl: float = 0.0
    daily_unrealized_pnl: float = 0.0

    @property
    def daily_pnl(self) -> float:
        return float(self.daily_realized_pnl) + float(self.daily_unrealized_pnl)


@dataclass(frozen=True)
class EdgeState:
    net_edge: float


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: list[str] = field(default_factory=list)


class RiskManager:
    def __init__(self, settings: Settings | None = None, session: Session | None = None) -> None:
        self.settings = settings or get_settings()
        self.session = session

    def _reject(self, reasons: list[str]) -> RiskDecision:
        if self.session is not None:
            for reason in reasons:
                self.session.add(
                    RiskEvent(
                        severity="error",
                        event_type="order_rejected",
                        message=reason,
                        raw_json={},
                    )
                )
        return RiskDecision(False, reasons)

    def validate_order(
        self,
        order: OrderIntent,
        market_state: MarketState,
        account_state: AccountState,
        edge_snapshot: EdgeState,
    ) -> RiskDecision:
        cfg = self.settings
        reasons: list[str] = []
        if cfg.LIVE_TRADING_HALTED:
            reasons.append("live trading halted by kill switch")
        if not cfg.LIVE_TRADING_ENABLED:
            reasons.append("LIVE_TRADING_ENABLED is false")
        if not cfg.REAL_MONEY_ACKNOWLEDGED:
            reasons.append("REAL_MONEY_ACKNOWLEDGED is false")
        if cfg.TRADING_MODE != "live_tiny":
            reasons.append("TRADING_MODE is not live_tiny")
        if order.order_type.lower() != "limit":
            reasons.append("order type is not limit")
        if not cfg.ALLOW_MARKET_ORDERS and order.order_type.lower() == "market":
            reasons.append("market orders are disabled")
        if order.notional > cfg.MAX_ORDER_USD:
            reasons.append("order notional exceeds MAX_ORDER_USD")
        if account_state.market_exposure_after > cfg.MAX_MARKET_EXPOSURE_USD:
            reasons.append("market exposure exceeds MAX_MARKET_EXPOSURE_USD")
        if account_state.open_exposure_after > cfg.MAX_OPEN_EXPOSURE_USD:
            reasons.append("open exposure exceeds MAX_OPEN_EXPOSURE_USD")
        if account_state.daily_volume_after > cfg.MAX_DAILY_VOLUME_USD:
            reasons.append("daily volume exceeds MAX_DAILY_VOLUME_USD")
        if account_state.daily_pnl <= -cfg.MAX_DAILY_LOSS_USD:
            reasons.append("daily loss limit exceeded")
        if edge_snapshot.net_edge < cfg.MIN_NET_EDGE:
            reasons.append("net edge below MIN_NET_EDGE")
        if market_state.spread > cfg.MAX_SPREAD:
            reasons.append("spread exceeds MAX_SPREAD")
        if market_state.sigma > cfg.MAX_MODEL_SIGMA:
            reasons.append("sigma exceeds MAX_MODEL_SIGMA")
        if market_state.staleness_seconds > cfg.MAX_ORDERBOOK_STALENESS_SECONDS:
            reasons.append("orderbook stale")
        if market_state.token_stale:
            reasons.append("token is stale")
        if market_state.closed or not market_state.active:
            reasons.append("token is closed or inactive")
        if market_state.max_slippage_price is not None and order.side.upper() == "BUY" and order.price > market_state.max_slippage_price:
            reasons.append("order price exceeds slippage limit")
        if not order.client_order_id:
            reasons.append("order missing client_order_id")
        if not order.strategy_id:
            reasons.append("order missing strategy_id")
        if reasons:
            return self._reject(reasons)
        return RiskDecision(True, [])

