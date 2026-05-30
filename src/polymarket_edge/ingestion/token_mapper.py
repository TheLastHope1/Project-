from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from polymarket_edge.db.models import Market, Token, utc_now


@dataclass(frozen=True)
class TokenInput:
    token_id: str
    condition_id: str | None
    market_id: str
    outcome: str | None
    outcome_index: int
    raw_json: dict[str, Any] = field(default_factory=dict)


def parse_maybe_json(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if "," in text:
                return [part.strip() for part in text.split(",") if part.strip()]
            return [text]
    return []


def _as_list(value: Any) -> list[Any]:
    parsed = parse_maybe_json(value)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return list(parsed.values())
    return []


def _market_id(raw: dict[str, Any]) -> str:
    return str(raw.get("id") or raw.get("market_id") or raw.get("conditionId") or raw.get("condition_id") or "")


def _condition_id(raw: dict[str, Any]) -> str | None:
    val = raw.get("conditionId") or raw.get("condition_id")
    return str(val) if val not in (None, "") else None


def _outcomes(raw: dict[str, Any]) -> list[str]:
    return [str(outcome) for outcome in _as_list(raw.get("outcomes"))]


def _token_ids(raw: dict[str, Any]) -> list[str]:
    for key in ("clobTokenIds", "clob_token_ids", "tokenIds", "token_ids"):
        values = [str(value) for value in _as_list(raw.get(key)) if value not in (None, "")]
        if values:
            return values
    for key in ("tokens", "outcomeTokens"):
        parsed = parse_maybe_json(raw.get(key))
        if isinstance(parsed, list):
            values = []
            for item in parsed:
                if isinstance(item, dict):
                    token_id = item.get("token_id") or item.get("tokenId") or item.get("id")
                    if token_id:
                        values.append(str(token_id))
                elif item:
                    values.append(str(item))
            if values:
                return values
    for key, value in raw.items():
        if "token" in key.lower() and "id" in key.lower():
            values = [str(item) for item in _as_list(value) if item not in (None, "")]
            if values:
                return values
    return []


def extract_tokens_from_market_raw(market_raw: Any) -> list[TokenInput]:
    if not isinstance(market_raw, dict):
        return []
    market_id = _market_id(market_raw)
    if not market_id:
        return []
    condition_id = _condition_id(market_raw)
    outcomes = _outcomes(market_raw)
    token_ids = _token_ids(market_raw)
    if not token_ids:
        return []
    tokens: list[TokenInput] = []
    for idx, token_id in enumerate(token_ids):
        tokens.append(
            TokenInput(
                token_id=token_id,
                condition_id=condition_id,
                market_id=market_id,
                outcome=outcomes[idx] if idx < len(outcomes) else None,
                outcome_index=idx,
                raw_json={"market": market_raw},
            )
        )
    return tokens


def upsert_tokens_for_market(session: Session, market: Market) -> int:
    count = 0
    for item in extract_tokens_from_market_raw(market.raw_json):
        existing = session.scalar(select(Token).where(Token.token_id == item.token_id))
        if existing is None:
            session.add(
                Token(
                    token_id=item.token_id,
                    market_id=market.market_id,
                    condition_id=item.condition_id,
                    outcome=item.outcome,
                    outcome_index=item.outcome_index,
                    raw_json=item.raw_json,
                )
            )
        else:
            existing.market_id = market.market_id
            existing.condition_id = item.condition_id
            existing.outcome = item.outcome
            existing.outcome_index = item.outcome_index
            existing.raw_json = item.raw_json
            existing.updated_at = utc_now()
        count += 1
    return count

