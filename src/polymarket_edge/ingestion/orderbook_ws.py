from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StreamSummary:
    subscribed_tokens: int
    message: str


async def stream_orderbooks(max_tokens: int = 200) -> StreamSummary:
    return StreamSummary(
        subscribed_tokens=max_tokens,
        message=(
            "WebSocket streaming scaffold is installed. Use REST polling for the "
            "local paper-trading bring-up; live trading remains blocked until "
            "preflight passes."
        ),
    )

