"""News -> market relevance adjudication (precision + direction).

The deterministic linker (``news.linker``) produces a high-recall shortlist
of candidate markets for each news item. This module decides, per candidate,
whether the news *actually* moves that market and in which direction, and
emits an independent probability estimate for the YES token -- the ``p_hat``
the edge engine otherwise lacks.

Two engines, selected by ``Settings.NEWS_RELEVANCE_MODE``:

  * ``deterministic`` -- rules-only. Marks candidates relevant by linker
    overlap but leaves direction NONE and ``implied_p`` unset. Free, no key,
    always available. Conservative by design.
  * ``hybrid`` / ``llm`` -- calls the configured LLM provider to score
    relevance + direction + confidence + implied probability per candidate.
    ``NEWS_LLM_PROVIDER=auto`` prefers DeepSeek, Azure OpenAI, generic
    OpenAI-compatible, then Anthropic if their explicit keys are present. On
    any failure, hybrid mode degrades to the deterministic verdict so the
    pipeline never hard-fails on the LLM.

The Messages API is called directly via httpx (already a dependency) rather
than the Anthropic SDK, to keep the Vercel serverless bundle slim. The static
instructions sit in a cached system block; the volatile news + candidate
payload goes in the user turn.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from polymarket_edge.config import Settings, get_settings
from polymarket_edge.logging import get_logger
from polymarket_edge.news.linker import Candidate
from polymarket_edge.news.models import RawNewsItem

log = get_logger(__name__)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"

_VALID_DIRECTIONS = {"YES_UP", "YES_DOWN", "NONE"}

# Static, cacheable system prompt. Keep this byte-stable so prompt caching can
# kick in once it exceeds the model's minimum cacheable prefix.
_SYSTEM_PROMPT = """You are a prediction-market analyst. You are given one news item and a \
short list of candidate Polymarket markets that a keyword matcher flagged as \
possibly related. For each candidate market, decide whether THIS news item \
materially changes the probability that the market's YES outcome occurs.

For each candidate, return:
- relevant: true only if the news is genuinely about the same underlying \
event/entity as the market AND plausibly moves it. Reject coincidental \
keyword overlap.
- direction: "YES_UP" if the news makes YES more likely, "YES_DOWN" if less \
likely, "NONE" if relevant but directionally neutral or unclear.
- confidence: 0.0-1.0, how sure you are about relevance AND direction.
- implied_probability: your best estimate (0.0-1.0) of the probability the \
YES outcome resolves true, conditioned on this news plus general priors. If \
you cannot estimate, repeat the market's current implied price if given, else 0.5.
- rationale: one concise sentence.

Be skeptical and precise. Most keyword matches are NOT real signals. A market \
resolving on a long horizon is barely moved by a single news item; reflect \
that in confidence. Never invent facts beyond the provided news text."""

# Structured-output schema. Note: structured outputs reject numeric min/max
# constraints, so ranges are enforced client-side after parsing.
_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "market_id": {"type": "string"},
                    "relevant": {"type": "boolean"},
                    "direction": {"type": "string", "enum": ["YES_UP", "YES_DOWN", "NONE"]},
                    "confidence": {"type": "number"},
                    "implied_probability": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "market_id", "relevant", "direction",
                    "confidence", "implied_probability", "rationale",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


@dataclass
class RelevanceVerdict:
    market_id: str
    relevant: bool
    direction: str            # YES_UP | YES_DOWN | NONE
    confidence: float
    implied_p: float | None
    rationale: str
    model: str                # "deterministic" | the Claude model id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp01(value: Any, default: float | None = None) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, v))


def deterministic_verdict(candidate: Candidate, max_score: float) -> RelevanceVerdict:
    """Linker-only verdict: relevance from overlap, no directional claim."""
    relevance = candidate.score / max_score if max_score > 0 else 0.0
    return RelevanceVerdict(
        market_id=candidate.market_id,
        relevant=bool(candidate.shared_entities) or len(candidate.shared_keywords) >= 2,
        direction="NONE",
        confidence=min(0.5, relevance),  # deterministic mode never claims high confidence
        implied_p=None,
        rationale=(
            f"keyword overlap (entities={candidate.shared_entities}, "
            f"keywords={candidate.shared_keywords})"
        ),
        model="deterministic",
    )


def _build_user_payload(news: RawNewsItem, candidates: list[Candidate]) -> str:
    return json.dumps(
        {
            "news": {
                "title": news.title,
                "summary": news.summary,
                "source": news.source_name or news.source,
                "published_at": news.published_at.isoformat() if news.published_at else None,
            },
            "candidate_markets": [
                {"market_id": c.market_id, "question": c.question}
                for c in candidates
            ],
        },
        ensure_ascii=False,
    )


def _call_anthropic(
    news: RawNewsItem,
    candidates: list[Candidate],
    settings: Settings,
    timeout: float,
) -> list[dict[str, Any]] | None:
    """POST the Messages API via httpx. Returns the parsed verdicts list, or
    None on any failure (caller falls back to deterministic)."""
    headers = {
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body = {
        "model": settings.ANTHROPIC_MODEL,
        "max_tokens": 2048,
        "system": [
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {"role": "user", "content": _build_user_payload(news, candidates)}
        ],
        "output_config": {
            "format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA}
        },
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(_ANTHROPIC_URL, headers=headers, json=body)
        if resp.status_code != 200:
            log.warning("anthropic_status_error", status=resp.status_code)
            return None
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("anthropic_request_failed", error=str(exc))
        return None

    usage = data.get("usage") or {}
    log.info(
        "anthropic_adjudicated",
        candidates=len(candidates),
        cache_read=usage.get("cache_read_input_tokens"),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
    )

    # With output_config.format the first text block is guaranteed valid JSON.
    blocks = data.get("content") or []
    text = next((b.get("text") for b in blocks if b.get("type") == "text"), None)
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        log.warning("anthropic_json_parse_failed")
        return None
    verdicts = parsed.get("verdicts")
    return verdicts if isinstance(verdicts, list) else None


@dataclass(frozen=True)
class _ChatProviderConfig:
    provider: str
    base_url: str
    model: str
    api_key: str
    auth_header: str
    extra_body: dict[str, Any]


def _chat_provider_config(settings: Settings) -> _ChatProviderConfig | None:
    provider = settings.resolved_news_llm_provider
    if provider == "deepseek":
        return _ChatProviderConfig(
            provider="deepseek",
            base_url=settings.DEEPSEEK_BASE_URL,
            model=settings.DEEPSEEK_MODEL,
            api_key=settings.DEEPSEEK_API_KEY,
            auth_header="authorization",
            extra_body={"thinking": {"type": "disabled"}},
        )
    if provider == "openai_compatible":
        return _ChatProviderConfig(
            provider="openai_compatible",
            base_url=settings.OPENAI_COMPATIBLE_BASE_URL,
            model=settings.OPENAI_COMPATIBLE_MODEL,
            api_key=settings.OPENAI_COMPATIBLE_API_KEY,
            auth_header="authorization",
            extra_body={},
        )
    if provider == "azure_openai":
        return _ChatProviderConfig(
            provider="azure_openai",
            base_url=settings.AZURE_OPENAI_BASE_URL,
            model=settings.AZURE_OPENAI_MODEL,
            api_key=settings.AZURE_OPENAI_API_KEY,
            auth_header="api-key",
            extra_body={},
        )
    return None


def _chat_url(config: _ChatProviderConfig) -> str:
    base = config.base_url.rstrip("/")
    if config.provider == "azure_openai":
        if base.endswith("/openai/v1"):
            return f"{base}/chat/completions"
        if "/openai/deployments/" in base:
            return f"{base}/chat/completions"
        return f"{base}/openai/v1/chat/completions"
    return f"{base}/chat/completions"


def _chat_headers(config: _ChatProviderConfig) -> dict[str, str]:
    headers = {"content-type": "application/json"}
    if config.auth_header == "api-key":
        headers["api-key"] = config.api_key
    else:
        headers["authorization"] = f"Bearer {config.api_key}"
    return headers


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    return cleaned


def _call_openai_compatible(
    news: RawNewsItem,
    candidates: list[Candidate],
    settings: Settings,
    timeout: float,
) -> list[dict[str, Any]] | None:
    config = _chat_provider_config(settings)
    if config is None:
        return None
    body = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_payload(news, candidates)},
        ],
        "temperature": 0,
        "max_tokens": 2048,
        "stream": False,
        "response_format": {"type": "json_object"},
        **config.extra_body,
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(_chat_url(config), headers=_chat_headers(config), json=body)
        if resp.status_code != 200:
            log.warning("chat_provider_status_error", provider=config.provider, status=resp.status_code)
            return None
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("chat_provider_request_failed", provider=config.provider, error=str(exc))
        return None

    usage = data.get("usage") or {}
    log.info(
        "chat_provider_adjudicated",
        provider=config.provider,
        model=config.model,
        candidates=len(candidates),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
    )
    choices = data.get("choices") or []
    if not choices:
        return None
    message = choices[0].get("message") or {}
    text = message.get("content")
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        parsed = json.loads(_strip_json_fence(text))
    except (ValueError, json.JSONDecodeError):
        log.warning("chat_provider_json_parse_failed", provider=config.provider)
        return None
    verdicts = parsed.get("verdicts")
    return verdicts if isinstance(verdicts, list) else None


def _call_llm_provider(
    news: RawNewsItem,
    candidates: list[Candidate],
    settings: Settings,
    timeout: float,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    provider = settings.resolved_news_llm_provider
    if provider == "anthropic":
        return _call_anthropic(news, candidates, settings, timeout), settings.ANTHROPIC_MODEL
    if provider in {"deepseek", "openai_compatible", "azure_openai"}:
        return _call_openai_compatible(news, candidates, settings, timeout), settings.resolved_news_llm_model
    return None, None


def llm_verdicts(
    news: RawNewsItem,
    candidates: list[Candidate],
    settings: Settings,
    timeout: float | None = None,
) -> list[RelevanceVerdict]:
    """Adjudicate via the configured LLM. Returns [] if unavailable/failed."""
    if not settings.llm_relevance_enabled or not candidates:
        return []
    raw, model = _call_llm_provider(news, candidates, settings, timeout=timeout or settings.REQUEST_TIMEOUT_SECONDS)
    if raw is None:
        return []
    by_id = {c.market_id: c for c in candidates}
    out: list[RelevanceVerdict] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        market_id = str(row.get("market_id") or "")
        if market_id not in by_id:
            continue
        direction = str(row.get("direction") or "NONE").upper()
        if direction not in _VALID_DIRECTIONS:
            direction = "NONE"
        out.append(
            RelevanceVerdict(
                market_id=market_id,
                relevant=bool(row.get("relevant")),
                direction=direction,
                confidence=_clamp01(row.get("confidence"), 0.0) or 0.0,
                implied_p=_clamp01(row.get("implied_probability")),
                rationale=str(row.get("rationale") or "")[:500],
                model=model or "llm",
            )
        )
    return out


def adjudicate(
    news: RawNewsItem,
    candidates: list[Candidate],
    settings: Settings | None = None,
) -> list[RelevanceVerdict]:
    """Dispatch by NEWS_RELEVANCE_MODE.

    - deterministic: linker-only verdicts.
    - hybrid: LLM verdicts; per-candidate deterministic fallback for any the
      LLM didn't return (or if the LLM is unavailable).
    - llm: LLM verdicts only; empty if the LLM is unavailable.
    """
    settings = settings or get_settings()
    if not candidates:
        return []
    max_score = max((c.score for c in candidates), default=1.0)
    mode = settings.NEWS_RELEVANCE_MODE

    if mode == "deterministic" or not settings.llm_relevance_enabled:
        if mode == "llm":
            return []  # llm explicitly requested but unavailable
        return [deterministic_verdict(c, max_score) for c in candidates]

    llm = llm_verdicts(news, candidates, settings)
    if mode == "llm":
        return llm

    # hybrid: merge, deterministic fallback for any candidate the LLM skipped
    scored_ids = {v.market_id for v in llm}
    merged = list(llm)
    for c in candidates:
        if c.market_id not in scored_ids:
            merged.append(deterministic_verdict(c, max_score))
    return merged
