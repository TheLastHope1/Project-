"""Unit tests for the new /book, /fee-rate, /tick-size client paths."""
from datetime import timezone
from unittest.mock import MagicMock

import pytest

from polymarket_scanner.client import (
    BookLevel,
    OrderBook,
    PolymarketClient,
    _parse_book,
)


def _resp(json_payload, ok=True, status=200):
    r = MagicMock()
    r.ok = ok
    r.status_code = status
    r.json.return_value = json_payload
    r.raise_for_status = MagicMock(return_value=None) if ok else MagicMock(side_effect=Exception("http"))
    return r


def test_parse_book_normalises_ordering():
    raw = {
        "bids": [
            {"price": "0.25", "size": "100"},
            {"price": "0.30", "size": "50"},
            {"price": "0.27", "size": "80"},
        ],
        "asks": [
            {"price": "0.42", "size": "100"},
            {"price": "0.35", "size": "200"},
            {"price": "0.38", "size": "100"},
        ],
        "tick_size": "0.01",
        "min_order_size": "5",
    }
    book = _parse_book("tokA", raw)
    # Bids descending, asks ascending.
    assert [b.price for b in book.bids] == [0.30, 0.27, 0.25]
    assert [a.price for a in book.asks] == [0.35, 0.38, 0.42]
    assert book.best_bid == 0.30
    assert book.best_ask == 0.35
    assert book.spread == 0.05
    assert book.tick_size == 0.01
    assert book.min_order_size == 5


def test_parse_book_drops_zero_or_invalid_levels():
    raw = {
        "bids": [{"price": "0.30", "size": "0"}, {"price": "0.25", "size": "100"}],
        "asks": [{"price": None, "size": "100"}, {"price": "0.40", "size": "10"}],
    }
    book = _parse_book("tokA", raw)
    assert [b.price for b in book.bids] == [0.25]
    assert [a.price for a in book.asks] == [0.40]


def test_book_vwap_handles_thin_book():
    book = OrderBook(
        token_id="t",
        bids=[],
        asks=[BookLevel(0.40, 5)],
    )
    vwap, filled = book.vwap_ask(target_shares=100)
    assert filled == 5
    assert vwap == 0.40


def test_get_book_single_token():
    client = PolymarketClient()
    client.session = MagicMock()
    client.session.get.return_value = _resp({
        "bids": [{"price": "0.30", "size": "100"}],
        "asks": [{"price": "0.35", "size": "200"}],
    })
    book = client.get_book("tokA")
    assert book is not None
    assert book.best_ask == 0.35
    client.session.get.assert_called_once()
    args, kwargs = client.session.get.call_args
    assert args[0].endswith("/book")
    assert kwargs["params"] == {"token_id": "tokA"}


def test_get_books_batch_then_fallback_per_token():
    client = PolymarketClient()
    client.session = MagicMock()
    # Batch returns only tokA. tokB should fall through to per-token GET.
    client.session.post.return_value = _resp([
        {"asset_id": "tokA", "bids": [{"price": "0.20", "size": "100"}], "asks": [{"price": "0.25", "size": "100"}]},
    ])
    client.session.get.return_value = _resp({
        "bids": [{"price": "0.40", "size": "50"}],
        "asks": [{"price": "0.45", "size": "50"}],
    })
    books = client.get_books_batch(["tokA", "tokB"])
    assert set(books.keys()) == {"tokA", "tokB"}
    assert books["tokA"].best_ask == 0.25
    assert books["tokB"].best_ask == 0.45


def test_get_fee_rate_normalises_bps_responses():
    client = PolymarketClient()
    client.session = MagicMock()
    # Polymarket has shipped fee rates as both decimals and bps; we normalise.
    client.session.get.return_value = _resp({"base_fee": "300"})  # 300 bps = 0.03
    rate = client.get_fee_rate("tokA")
    assert rate == pytest.approx(0.03)
    # Second call uses cache and doesn't refetch.
    client.session.get.reset_mock()
    rate2 = client.get_fee_rate("tokA")
    assert rate2 == pytest.approx(0.03)
    client.session.get.assert_not_called()


def test_get_tick_size_caches_per_token():
    client = PolymarketClient()
    client.session = MagicMock()
    client.session.get.return_value = _resp({"minimum_tick_size": "0.01"})
    assert client.get_tick_size("tokA") == 0.01
    client.session.get.reset_mock()
    assert client.get_tick_size("tokA") == 0.01
    client.session.get.assert_not_called()


def test_validate_price_side_semantics_happy_path():
    client = PolymarketClient()
    client.session = MagicMock()

    def fake_get(url, **kwargs):
        if url.endswith("/book"):
            return _resp({
                "bids": [{"price": "0.30", "size": "100"}],
                "asks": [{"price": "0.35", "size": "100"}],
            })
        if url.endswith("/price"):
            side = kwargs["params"]["side"]
            # The PDF-flagged convention: BUY returns best bid, SELL returns best ask.
            return _resp({"price": "0.30" if side == "BUY" else "0.35"})
        if url.endswith("/tick-size"):
            return _resp({"minimum_tick_size": "0.01"})
        raise AssertionError(f"unexpected GET to {url}")

    client.session.get.side_effect = fake_get
    # /price batch endpoint will fail; per-token fallback supplies the value.
    client.session.post.return_value = _resp([], ok=False, status=404)

    result = client.validate_price_side_semantics("tokA")
    assert result["ok"] is True
    assert result["best_bid"] == 0.30
    assert result["best_ask"] == 0.35
    assert result["buy_price"] == 0.30
    assert result["sell_price"] == 0.35


def test_validate_price_side_semantics_flags_disagreement():
    # If the docs interpretation were reversed (BUY returns ask, SELL returns
    # bid), the validator should fail and surface that. The PDF identified
    # this as the most error-prone integration point in the codebase.
    client = PolymarketClient()
    client.session = MagicMock()

    def fake_get(url, **kwargs):
        if url.endswith("/book"):
            return _resp({
                "bids": [{"price": "0.30", "size": "100"}],
                "asks": [{"price": "0.35", "size": "100"}],
            })
        if url.endswith("/price"):
            side = kwargs["params"]["side"]
            # Reversed semantics: BUY returns ask, SELL returns bid.
            return _resp({"price": "0.35" if side == "BUY" else "0.30"})
        if url.endswith("/tick-size"):
            return _resp({"minimum_tick_size": "0.01"})
        raise AssertionError(url)

    client.session.get.side_effect = fake_get
    client.session.post.return_value = _resp([], ok=False, status=404)
    result = client.validate_price_side_semantics("tokA")
    assert result["ok"] is False
    assert "buy_side_disagrees_with_best_bid" in result["notes"]
    assert "sell_side_disagrees_with_best_ask" in result["notes"]


def test_iter_active_events_keyset_yields_unique_markets():
    client = PolymarketClient()
    client.session = MagicMock()

    market_a = {
        "id": "1",
        "question": "A vs B",
        "slug": "a-b",
        "outcomes": '["A","B"]',
        "outcomePrices": '["0.7","0.3"]',
        "clobTokenIds": '["tokA","tokB"]',
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "volume": 1000,
        "liquidity": 1000,
    }
    market_b = {**market_a, "id": "2", "question": "C vs D", "slug": "c-d"}
    page1 = {"data": [{"title": "Event 1", "markets": [market_a]}], "next_cursor": "abc"}
    page2 = {"data": [{"title": "Event 2", "markets": [market_b, market_a]}], "next_cursor": None}

    responses = [_resp(page1), _resp(page2)]
    client.session.get.side_effect = responses

    markets = list(client.iter_active_events_keyset(max_pages=3))
    # market_a appears in both pages; should be deduped.
    assert [m.id for m in markets] == ["1", "2"]
