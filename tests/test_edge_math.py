from __future__ import annotations

import numpy as np
import pytest

from polymarket_edge.arbitrage.finite_state_lp import finite_state_arbitrage_lp
from polymarket_edge.config import Settings
from polymarket_edge.models.costs import multiple_testing_penalty, total_cost, vwap_slippage
from polymarket_edge.models.edge_engine import score_market
from polymarket_edge.models.probability import confidence_adjusted_probability, logit, market_mid_probability, sigmoid


class Snapshot:
    token_id = "tok"
    best_bid = 0.4
    best_ask = 0.42
    spread = 0.02


def test_multiple_testing_penalty_formula():
    assert multiple_testing_penalty(0.05, 10) == pytest.approx(0.05 * np.sqrt(2 * np.log(10)))


def test_total_cost_formula():
    got = total_cost(0.001, 0.02, 0.002, 0.004, 1.96, 0.05, 10)
    expected = 0.001 + 0.02 + 0.002 + 0.004 + 1.96 * 0.05 + 0.05 * np.sqrt(2 * np.log(10))
    assert got == pytest.approx(expected)


def test_vwap_slippage_buy_and_sell():
    buy = vwap_slippage([{"price": 0.4, "size": 10}, {"price": 0.5, "size": 10}], 15, 0.4, "BUY")
    assert buy.executable_size == 15
    assert buy.vwap == pytest.approx((4 + 2.5) / 15)
    assert buy.slippage == pytest.approx(buy.vwap - 0.4)
    sell = vwap_slippage([(0.6, 10), (0.55, 10)], 15, 0.6, "SELL")
    assert sell.slippage == pytest.approx(0.6 - sell.vwap)


def test_probability_helpers():
    assert market_mid_probability(0.4, 0.6) == 0.5
    assert sigmoid(logit(0.3)) == pytest.approx(0.3)
    assert confidence_adjusted_probability(0.6, 0.1, 2) == pytest.approx(0.4)


def test_buy_edge_positive_and_kelly_size():
    settings = Settings(
        DEFAULT_FEE=0,
        DEFAULT_LATENCY_COST=0,
        DEFAULT_ADVERSE_SELECTION_COST=0,
        Z_ALPHA=0,
        MODEL_SIGMA_DEFAULT=0,
        MAX_POSITION_FRACTION=0.5,
        _env_file=None,
    )
    score = score_market(Snapshot(), p_hat=0.7, sigma=0, config=settings, n_markets=1)
    assert score.action == "BUY"
    assert score.buy_net_edge == pytest.approx(0.26)
    assert score.kelly_size > 0


def test_buy_edge_negative_after_uncertainty_penalty():
    settings = Settings(_env_file=None)
    score = score_market(Snapshot(), p_hat=0.43, sigma=0.1, config=settings, n_markets=100)
    assert score.action == "NONE"
    assert score.buy_net_edge < 0


def test_sell_edge_positive():
    settings = Settings(
        DEFAULT_FEE=0,
        DEFAULT_LATENCY_COST=0,
        DEFAULT_ADVERSE_SELECTION_COST=0,
        Z_ALPHA=0,
        MAX_POSITION_FRACTION=0.5,
        _env_file=None,
    )
    score = score_market(Snapshot(), p_hat=0.2, sigma=0, config=settings, n_markets=1)
    assert score.action == "SELL"
    assert score.sell_net_edge == pytest.approx(0.18)


def test_finite_state_lp_binary_arb_and_no_arb():
    V = np.array([[1, 0], [0, 1]], dtype=float)
    arb = finite_state_arbitrage_lp(V, np.array([0.49, 0.49]), np.array([0.48, 0.48]), max_exposure=2)
    assert arb.success
    assert arb.arbitrage_exists
    fair = finite_state_arbitrage_lp(V, np.array([0.5, 0.5]), np.array([0.49, 0.49]), max_exposure=2)
    assert fair.success
    assert not fair.arbitrage_exists


def test_finite_state_lp_subset_arb():
    V = np.array([[1, 1], [0, 1], [0, 0]], dtype=float)
    result = finite_state_arbitrage_lp(V, np.array([0.65, 0.5]), np.array([0.6, 0.49]), max_exposure=2)
    assert result.success
    assert result.arbitrage_exists
