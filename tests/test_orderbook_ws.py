from __future__ import annotations

import pytest

from polymarket_edge.ingestion.orderbook_ws import _decode_events, orderbook_from_ws_event


def test_orderbook_ws_normalizes_book_event():
    book = orderbook_from_ws_event(
        {
            "event_type": "book",
            "asset_id": "tok",
            "bids": [{"price": "0.48", "size": "10"}],
            "asks": [{"price": "0.51", "size": "12"}],
        }
    )

    assert book is not None
    assert book.token_id == "tok"
    assert book.best_bid == 0.48
    assert book.best_ask == 0.51
    assert book.spread == pytest.approx(0.03)


def test_orderbook_ws_normalizes_best_bid_ask_event():
    book = orderbook_from_ws_event(
        {
            "event_type": "best_bid_ask",
            "asset_id": "tok",
            "best_bid": "0.47",
            "best_ask": "0.50",
        }
    )

    assert book is not None
    assert book.token_id == "tok"
    assert book.best_bid == 0.47
    assert book.best_ask == 0.50
    assert book.bids == []
    assert book.asks == []


def test_orderbook_ws_decode_heartbeat_and_list_payload():
    assert _decode_events("PONG") == []
    assert _decode_events('[{"event_type":"book"},{"event_type":"price_change"}]') == [
        {"event_type": "book"},
        {"event_type": "price_change"},
    ]
