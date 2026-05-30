"""Unit tests for the official Polymarket fee model."""
import pytest

from polymarket_scanner.fees import (
    CATEGORY_FEE_RATES,
    DEFAULT_FEE_RATE,
    breakeven_ask,
    category_fee_rate,
    depth_weighted_ask,
    net_ev_per_share,
    net_ev_pct,
    resolve_fee_rate,
    taker_fee,
)


def test_taker_fee_matches_official_formula():
    # fee = C * r * p * (1-p). Sports rate 0.03, ask 0.40, 100 shares.
    quote = taker_fee(price=0.40, shares=100, rate=0.03)
    # 100 * 0.03 * 0.40 * 0.60 = 0.72 USDC
    assert quote.per_share == pytest.approx(0.0072)
    assert quote.total == pytest.approx(0.72)


def test_taker_fee_clamps_negative_inputs():
    # Negative or out-of-range price/size should clamp, not crash, and should
    # produce a non-negative fee.
    quote = taker_fee(price=-0.1, shares=-5, rate=0.03)
    assert quote.total >= 0
    assert quote.shares == 0


def test_category_fee_rate_basic_lookups():
    assert category_fee_rate("Sports") == 0.03
    assert category_fee_rate("Crypto") == 0.07
    assert category_fee_rate("Geopolitics") == 0.00
    # Unknown -> default.
    assert category_fee_rate("Made-up-category") == DEFAULT_FEE_RATE
    # Empty / None -> default.
    assert category_fee_rate(None) == DEFAULT_FEE_RATE
    assert category_fee_rate("") == DEFAULT_FEE_RATE


def test_category_fee_rate_handles_compound_strings():
    # Real Gamma categories often include qualifiers like "Politics, US".
    assert category_fee_rate("Politics, US") == 0.04
    assert category_fee_rate("Tennis (ITF)") == 0.03
    assert category_fee_rate("CS2 esports") == 0.03


def test_resolve_fee_rate_precedence():
    # override beats CLOB beats category.
    rate, src = resolve_fee_rate("sports", token_fee_rate=0.04, override=0.10)
    assert (rate, src) == (0.10, "override")
    rate, src = resolve_fee_rate("sports", token_fee_rate=0.04)
    assert (rate, src) == (0.04, "clob_fee_rate")
    rate, src = resolve_fee_rate("sports")
    assert (rate, src) == (0.03, "category")


def test_breakeven_ask_matches_pdf_table():
    # Derived breakevens for a guaranteed 50/50 (from the review PDF):
    # sports 0.03 -> ~0.4925, finance 0.04 -> ~0.49, other 0.05 -> ~0.4875,
    # crypto 0.07 -> ~0.4825, geo 0.0 -> 0.50.
    assert breakeven_ask(0.03) == pytest.approx(0.4925, abs=0.0005)
    assert breakeven_ask(0.04) == pytest.approx(0.49, abs=0.0005)
    assert breakeven_ask(0.05) == pytest.approx(0.4875, abs=0.0005)
    assert breakeven_ask(0.07) == pytest.approx(0.4825, abs=0.0005)
    assert breakeven_ask(0.00) == pytest.approx(0.5, abs=1e-9)


def test_net_ev_per_share_at_breakeven_is_zero():
    # By construction, EV at the breakeven ask under a guaranteed 50/50 is 0.
    for rate in (0.0, 0.03, 0.04, 0.05, 0.07):
        a = breakeven_ask(rate)
        assert net_ev_per_share(a, rate, p_fifty=1.0) == pytest.approx(0.0, abs=1e-6)


def test_net_ev_pct_sports_example():
    # PDF sample: best ask 0.40, sports rate 0.03, guaranteed 50/50.
    # Fee per share = 0.03 * 0.40 * 0.60 = 0.0072
    # Net per share = 0.5 - 0.40 - 0.0072 = 0.0928
    # Cost basis = 0.40 + 0.0072 = 0.4072
    # ROI = 0.0928 / 0.4072 ~= 0.228
    ev = net_ev_pct(0.40, 0.03, p_fifty=1.0)
    assert ev == pytest.approx(0.228, abs=0.005)


def test_net_ev_pct_handles_zero_ask():
    assert net_ev_pct(0.0, 0.03) == 0.0


def test_depth_weighted_ask_walks_levels():
    levels = [(0.40, 50), (0.42, 100), (0.45, 200)]
    vwap, filled = depth_weighted_ask(levels, target_shares=200)
    # 50 @ 0.40 + 100 @ 0.42 + 50 @ 0.45 = 20 + 42 + 22.5 = 84.5 / 200 = 0.4225
    assert filled == pytest.approx(200)
    assert vwap == pytest.approx(0.4225, abs=1e-4)


def test_depth_weighted_ask_partial_fill():
    levels = [(0.40, 10)]
    vwap, filled = depth_weighted_ask(levels, target_shares=100)
    assert filled == 10
    assert vwap == 0.40


def test_depth_weighted_ask_empty_book():
    assert depth_weighted_ask([], target_shares=100) == (0.0, 0.0)
    assert depth_weighted_ask([(0.40, 50)], target_shares=0) == (0.0, 0.0)


def test_category_fee_rates_cover_pdf_categories():
    # Spot-check that every category named in the PDF review is mapped.
    for cat in ("sports", "finance", "politics", "tech", "economics",
                "culture", "weather", "crypto", "geopolitics"):
        assert cat in CATEGORY_FEE_RATES, f"missing fee rate for {cat}"
