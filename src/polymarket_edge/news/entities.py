"""Deterministic entity / keyword extraction.

No ML dependency (keeps the serverless bundle small and the output stable and
auditable). We pull two things from any text:

  * entities  -- capitalized 1-4 word proper-noun phrases ("Federal Reserve",
                 "Donald Trump", "Bitcoin"), lowercased
  * keywords  -- significant single content words, stopwords removed

Both market questions and news items run through the same extractor so the
linker can score overlap on a like-for-like basis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_PROPER_RE = re.compile(r"[A-Z][a-zA-Z0-9.&'’-]*(?:\s+[A-Z][a-zA-Z0-9.&'’-]*){0,3}")
_WORD_RE = re.compile(r"[a-z0-9$][a-z0-9$.,']*")
_MONEY_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?[kmbt]?", re.I)

_STOPWORDS = frozenset(
    """
    a an the this that these those and or but if then else when while of for to in on at by with
    from into over under above below up down out off as is are was were be been being do does did
    will would shall should can could may might must have has had not no nor so than too very just
    about after before between during through against amid per via vs versus it its he she they them
    his her their our your my we you i who whom whose which what where why how will-it does-it
    new latest update report says say said amid more most less least new
    """.split()
)

# Common sentence-initial / interrogative words that get capitalized but are
# not entities.
_NON_ENTITY_WORDS = frozenset(
    w.lower()
    for w in (
        "Will", "Who", "What", "When", "Where", "Why", "How", "The", "A", "An",
        "Is", "Are", "Do", "Does", "Did", "Can", "Could", "Should", "Would",
        "This", "That", "By", "In", "On", "At", "Of", "For", "To", "And", "Or",
        "It", "He", "She", "They", "We", "You", "I", "Breaking", "Live", "News",
    )
)

# Small domain lexicon so lowercased mentions still register as entities.
_DOMAIN_TERMS = frozenset(
    {
        "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto", "dogecoin",
        "fed", "fomc", "cpi", "gdp", "nasdaq", "s&p", "openai", "nvidia", "tesla",
        "trump", "biden", "harris", "putin", "zelensky", "netanyahu", "powell",
        "ukraine", "russia", "israel", "gaza", "china", "taiwan", "nato",
    }
)


@dataclass
class Extracted:
    entities: list[str] = field(default_factory=list)  # lowercased phrases
    keywords: set[str] = field(default_factory=set)    # lowercased words

    def tokens(self) -> set[str]:
        """Match surface: entity phrases + their component words + keywords."""
        out: set[str] = set(self.keywords)
        for ent in self.entities:
            out.add(ent)
            out.update(ent.split())
        return {t for t in out if len(t) >= 2}


_MAX_WORD_LEN = 24  # anything longer is almost always a URL slug / base64 noise


def _clean_money(token: str) -> str:
    return token.strip(".,")


def _is_noise(token: str) -> bool:
    """Reject URL slugs / base64 blobs that survive HTML stripping."""
    return len(token) > _MAX_WORD_LEN


def extract(text: str) -> Extracted:
    if not text:
        return Extracted()
    entities: list[str] = []
    seen_entities: set[str] = set()
    for match in _PROPER_RE.finditer(text):
        phrase = match.group(0).strip()
        words = phrase.split()
        # Drop leading non-entity words (e.g. "Will Bitcoin" -> "Bitcoin").
        while words and words[0].lower() in _NON_ENTITY_WORDS:
            words = words[1:]
        while words and words[-1].lower() in _NON_ENTITY_WORDS:
            words = words[:-1]
        if not words:
            continue
        norm = " ".join(words).lower()
        if norm in _NON_ENTITY_WORDS or len(norm) < 2:
            continue
        if any(_is_noise(word) for word in words):
            continue
        if norm not in seen_entities:
            seen_entities.add(norm)
            entities.append(norm)

    lowered = text.lower()
    keywords: set[str] = set()
    for raw in _WORD_RE.findall(lowered):
        word = _clean_money(raw)
        if len(word) < 3 or _is_noise(word):
            continue
        if word in _STOPWORDS:
            continue
        keywords.add(word)
    # Money/level tokens are high-signal for threshold markets.
    for raw in _MONEY_RE.findall(text):
        tok = _clean_money(raw.lower())
        if len(tok) >= 2:
            keywords.add(tok)
    # Domain terms present anywhere become entities even if lowercased.
    for term in _DOMAIN_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", lowered) and term not in seen_entities:
            seen_entities.add(term)
            entities.append(term)

    return Extracted(entities=entities, keywords=keywords)
