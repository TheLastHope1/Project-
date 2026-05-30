"""Structured classification of Polymarket resolution rules.

The PDF review (``Polymarket forfeit and no-show edge discovery review``)
flagged that the original regex screener was too coarse: words like
"forfeit", "walkover", and "no contest" can map to *several* materially
different fallback resolutions, only some of which produce the
guaranteed-50/50 outcome that the underdog thesis depends on.

This module replaces the broad keyword match with a deterministic classifier
that reads each market's ``rule_text`` and returns:

    1. a ``FallbackRuleClass`` -- the most specific actionable class
    2. a ``confidence`` in [0, 1] based on how many supporting phrases match
       and whether any contradicting phrases were also found
    3. the matched snippet(s) so a human can audit a decision

The classifier is intentionally rule-based, not ML. Every promotion or
demotion of a market should be explainable from the rule wording.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class FallbackRuleClass(str, Enum):
    """How this market is expected to resolve if the headline event is
    cancelled, forfeited, abandoned, or otherwise doesn't play out cleanly.

    Ordered from most-actionable (top) to avoid-this (bottom).
    """

    FIFTY_FIFTY_EXPLICIT = "fifty_fifty_explicit"
    """Rules explicitly state the market resolves 50/50 in this scenario."""

    WALKOVER_FIFTY_FIFTY = "walkover_fifty_fifty"
    """Walkover/forfeit/disqualification specifically resolves 50/50."""

    CLINCHING_EXCEPTION = "clinching_exception"
    """Incomplete-match 50/50, but a clinching-map forfeit counts as a
    completed match. The base 50/50 thesis still applies most of the time,
    but the exception flips sign on a specific sub-event class."""

    ADVANCES_IF_STARTED = "advances_if_started"
    """50/50 only if play never began. Once play begins and one side wins by
    retirement/default/disqualification, the advancing side wins. Tennis
    moneylines are the canonical example."""

    CRICKET_TIE_FIFTY = "cricket_tie_fifty"
    """A tied match without an on-field tiebreak resolves 50/50."""

    UNKNOWN_EXPLICIT = "unknown_explicit"
    """A discrete ``Unknown`` outcome exists as a tradable leg. The
    binary-underdog thesis does not apply; needs a different model."""

    OTHER_OUTCOME = "other_outcome"
    """Cancellation/no-result routes to an ``Other`` outcome, not 50/50."""

    REFUND_VOID = "refund_void"
    """All bets refunded / market voided. Not tradable as an edge."""

    TIE_ONLY = "tie_only"
    """Equality/data-tie 50/50 (stock up/down ties, polling ties). Not a
    forfeit-edge market; lives in a different research bucket."""

    UNSAFE_AMBIGUOUS = "unsafe_ambiguous"
    """Has fallback wording but multiple resolution paths matched and they
    contradict. Treat as research-only; never auto-trade."""

    NO_FALLBACK_LANGUAGE = "no_fallback_language"
    """No relevant phrases matched. Outside the scanner's edge thesis."""


# Phrase pools. Each entry is (regex, weight). Higher weight = more
# diagnostic of the class. Weights aggregate, capped at 1.0 in the result.
_FIFTY_FIFTY_CORE = [
    (re.compile(r"\bresolv\w*\s+(?:to\s+)?50[-\s/]50\b", re.I), 0.7),
    (re.compile(r"\b50[-\s/]50\s+(?:split|resolution|outcome)\b", re.I), 0.6),
    (re.compile(r"\bsettle\s+(?:at|to)\s+(?:\$?0?\.5(?:0)?|fifty)\b", re.I), 0.6),
    (re.compile(r"\bfifty[-\s]fifty\b", re.I), 0.4),
    (re.compile(r"\beach\s+(?:token|share|outcome)\s+(?:redeems|resolves)\s+(?:to|at)\s+\$?0?\.5\b", re.I), 0.7),
]

_WALKOVER_FIFTY = [
    (re.compile(r"\b(?:walkover|forfeit|w/?o|w\.o\.)\b[^.]{0,120}?\b50[-\s/]50\b", re.I), 0.8),
    (re.compile(r"\b50[-\s/]50\b[^.]{0,120}?\b(?:walkover|forfeit|w/?o)\b", re.I), 0.7),
    (re.compile(r"\b(?:disqualif\w+|withdrawal|withdraws?|retire(?:s|d|ment)?)\b[^.]{0,120}?\b50[-\s/]50\b", re.I), 0.6),
    (re.compile(r"\bincomplete\s+(?:match|game|series)\b[^.]{0,120}?\b50[-\s/]50\b", re.I), 0.7),
]

_CLINCHING_EXCEPTION = [
    (re.compile(r"\bclinch\w*\s+(?:map|game|set)\b[^.]{0,160}?(?:complet\w+|count\w+\s+as)", re.I), 0.9),
    (re.compile(r"\bseries\s+is\s+already\s+(?:decided|determined)\b", re.I), 0.7),
    (re.compile(r"\b(?:already\s+(?:decided|determined))\b[^.]{0,80}?\bforfeit\b", re.I), 0.6),
]

_ADVANCES_IF_STARTED = [
    (re.compile(r"\b(?:player|team|fighter|side)\s+(?:who|that|which)\s+advanc\w+", re.I), 0.7),
    (re.compile(r"\badvanc\w+\s+(?:player|team|fighter|side|to\s+the\s+next)\b", re.I), 0.7),
    (re.compile(r"\b(?:once|when|after|if)\s+(?:play|the\s+match|the\s+game)\s+(?:has\s+|have\s+|had\s+|will\s+have\s+)?(?:begin\w*|begun|started)\b", re.I), 0.6),
    (re.compile(r"\b(?:if|once|when)\s+play\s+(?:has\s+|will\s+have\s+)?(?:begun|started)\b[^.]{0,160}?\b(?:retire|default|disqualif|withdraw)", re.I), 0.8),
    (re.compile(r"\b(?:retire(?:ment|s|d)?|default|disqualif\w+)\b[^.]{0,120}?\b(?:advanc\w+|winner\s+of\s+the\s+match)\b", re.I), 0.7),
    (re.compile(r"\badvanc\w+\s+through\s+(?:retire|default|disqualif|withdraw)", re.I), 0.8),
]

_CRICKET_TIE = [
    (re.compile(r"\b(?:cricket|odi|test\s+match|t20)\b[^.]{0,160}?\btie(?:d)?\b[^.]{0,120}?\b50[-\s/]50\b", re.I), 0.9),
    (re.compile(r"\bsuper\s+over\s+(?:is\s+)?not\s+used\b", re.I), 0.6),
    (re.compile(r"\btied\s+match\b[^.]{0,120}?\b50[-\s/]50\b", re.I), 0.7),
]

_UNKNOWN_EXPLICIT_TEXT = [
    (re.compile(r'"?unknown"?\s+outcome\b', re.I), 0.7),
    (re.compile(r"\bresolv\w*\s+(?:to|as)\s+unknown\b", re.I), 0.8),
]

_OTHER_OUTCOME = [
    (re.compile(r"\bresolv\w*\s+(?:to|as)\s+(?:the\s+)?[\"']?other[\"']?\b", re.I), 0.8),
    (re.compile(r"\bcancel\w*\b[^.]{0,80}?\bresolv\w*\s+(?:to|as)\s+other\b", re.I), 0.9),
    (re.compile(r"\bno\s+winner\s+is\s+announced\b[^.]{0,160}?\bother\b", re.I), 0.8),
]

_REFUND_VOID = [
    (re.compile(r"\ball\s+(?:bets|trades|orders)\s+(?:are\s+)?(?:voided|refunded)\b", re.I), 0.9),
    (re.compile(r"\bmarket\s+will\s+be\s+(?:voided|cancel(?:led|ed))\b", re.I), 0.8),
    (re.compile(r"\brefund\w*\s+(?:all\s+)?(?:traders|positions|holders)\b", re.I), 0.7),
    (re.compile(r"\bnot\s+resolve\s+50[-\s/]50\b", re.I), 0.9),
]

_TIE_ONLY = [
    (re.compile(r"\b(?:closing|final)\s+price\b[^.]{0,80}?\b(?:equal|tie|tied|unchanged)\b", re.I), 0.7),
    (re.compile(r"\bup\s+or\s+down\b[^.]{0,80}?\bequal\b", re.I), 0.6),
    (re.compile(r"\bpoll\s+(?:result|average)\b[^.]{0,120}?\btie(?:d)?\b", re.I), 0.6),
]


@dataclass(frozen=True)
class RuleClassification:
    """Result of classifying one market's rules.

    ``probability_fifty`` is the classifier's modelled probability that the
    market settles 50/50 conditional on a no-show/forfeit event. This drives
    the EV calculation; the canonical 50/50 thesis sets it to ~0.95 for
    explicit cases and degrades for ambiguous ones.
    """

    rule_class: FallbackRuleClass
    confidence: float
    probability_fifty: float
    matched: list[str] = field(default_factory=list)
    contradicting: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_tradable_fifty_fifty(self) -> bool:
        return self.rule_class in (
            FallbackRuleClass.FIFTY_FIFTY_EXPLICIT,
            FallbackRuleClass.WALKOVER_FIFTY_FIFTY,
            FallbackRuleClass.CRICKET_TIE_FIFTY,
            FallbackRuleClass.CLINCHING_EXCEPTION,
        )

    def to_dict(self) -> dict:
        return {
            "rule_class": self.rule_class.value,
            "confidence": round(self.confidence, 3),
            "probability_fifty": round(self.probability_fifty, 3),
            "matched": list(self.matched),
            "contradicting": list(self.contradicting),
            "notes": list(self.notes),
        }


def _scan(patterns: list[tuple[re.Pattern[str], float]], text: str) -> tuple[float, list[str]]:
    """Return aggregated weight (capped 1.0) and matched snippets."""
    if not text:
        return (0.0, [])
    total = 0.0
    matched: list[str] = []
    for pattern, weight in patterns:
        m = pattern.search(text)
        if m:
            total += weight
            snippet = m.group(0)
            if len(snippet) > 160:
                snippet = snippet[:157] + "..."
            matched.append(snippet)
    return (min(1.0, total), matched)


def classify_rules(rule_text: str, outcomes: list[str] | None = None) -> RuleClassification:
    """Classify a market's resolution rules.

    ``rule_text`` should be the concatenation of question, description,
    rules, and resolution-source text (``Market.rule_text`` does this).
    ``outcomes`` is the list of tradable outcome names; if any outcome is
    literally ``"Unknown"`` or ``"Other"`` we promote those classifications
    even when the rule text is sparse.
    """
    text = rule_text or ""
    outcomes_norm = [str(o).strip().lower() for o in (outcomes or [])]

    # First pass: outcome-list-driven classifications. These are the most
    # reliable because the existence of an "Unknown" outcome is a structural
    # fact about the market, not a wording quirk.
    if any(o == "unknown" for o in outcomes_norm):
        return RuleClassification(
            rule_class=FallbackRuleClass.UNKNOWN_EXPLICIT,
            confidence=0.95,
            probability_fifty=0.0,
            matched=["outcome:Unknown"],
            notes=["explicit_unknown_outcome"],
        )
    if any(o == "other" for o in outcomes_norm):
        # "Other" as a tradable outcome usually replaces the 50/50 fallback
        # with a discrete resolution -- still mark it specially.
        # Continue scanning text to see if there's *also* explicit 50/50
        # language (rare but possible).
        pass

    # Text-driven classifications, scored independently then reconciled.
    refund_w, refund_m = _scan(_REFUND_VOID, text)
    if refund_w >= 0.7:
        return RuleClassification(
            rule_class=FallbackRuleClass.REFUND_VOID,
            confidence=refund_w,
            probability_fifty=0.0,
            matched=refund_m,
            notes=["refund_or_void_language"],
        )

    fifty_core_w, fifty_core_m = _scan(_FIFTY_FIFTY_CORE, text)
    walkover_w, walkover_m = _scan(_WALKOVER_FIFTY, text)
    clinch_w, clinch_m = _scan(_CLINCHING_EXCEPTION, text)
    advances_w, advances_m = _scan(_ADVANCES_IF_STARTED, text)
    cricket_w, cricket_m = _scan(_CRICKET_TIE, text)
    unknown_w, unknown_m = _scan(_UNKNOWN_EXPLICIT_TEXT, text)
    other_w, other_m = _scan(_OTHER_OUTCOME, text)
    tie_w, tie_m = _scan(_TIE_ONLY, text)

    # If "Other" is both an outcome AND we matched routing-to-other phrases,
    # this is the OTHER_OUTCOME class with high confidence.
    other_outcome_present = any(o == "other" for o in outcomes_norm)
    if other_w >= 0.7 or (other_outcome_present and other_w >= 0.4):
        return RuleClassification(
            rule_class=FallbackRuleClass.OTHER_OUTCOME,
            confidence=min(1.0, other_w + (0.2 if other_outcome_present else 0.0)),
            probability_fifty=0.0,
            matched=other_m + (["outcome:Other"] if other_outcome_present else []),
            notes=["cancellation_routes_to_other"],
        )

    # Cricket tie has its own bucket because the language is distinctive.
    if cricket_w >= 0.6:
        return RuleClassification(
            rule_class=FallbackRuleClass.CRICKET_TIE_FIFTY,
            confidence=cricket_w,
            probability_fifty=0.85,
            matched=cricket_m,
            notes=["cricket_tie_resolves_fifty"],
        )

    # The interesting reconciliation: walkover + advancing-player language
    # together. If both fire strongly, the advancing-player branch wins --
    # the underdog thesis collapses to "loser if play started".
    if advances_w >= 0.6 and walkover_w >= 0.4:
        return RuleClassification(
            rule_class=FallbackRuleClass.ADVANCES_IF_STARTED,
            confidence=min(1.0, advances_w + 0.1),
            probability_fifty=0.30,  # 50/50 only if play never started
            matched=advances_m,
            contradicting=walkover_m,
            notes=["pre_match_fifty_only_post_match_advances"],
        )

    # Pure advances-if-started with no walkover-50/50 to anchor on. Still
    # a real class, but probability_fifty stays low.
    if advances_w >= 0.6:
        return RuleClassification(
            rule_class=FallbackRuleClass.ADVANCES_IF_STARTED,
            confidence=advances_w,
            probability_fifty=0.25,
            matched=advances_m,
            notes=["advancing_player_clause_present"],
        )

    # Clinching exception is dangerous specifically because it looks like
    # WALKOVER_FIFTY_FIFTY in the headline phrase but reverses sign on a
    # sub-case. Surface it as its own class so the operator can sub-filter.
    if clinch_w >= 0.6 and (walkover_w >= 0.4 or fifty_core_w >= 0.4):
        return RuleClassification(
            rule_class=FallbackRuleClass.CLINCHING_EXCEPTION,
            confidence=min(1.0, clinch_w + 0.2),
            probability_fifty=0.65,
            matched=clinch_m + walkover_m,
            notes=["clinching_map_counts_as_completed"],
        )

    # Walkover + 50/50 in the same neighbourhood: the canonical
    # forfeit-edge class.
    if walkover_w >= 0.6:
        return RuleClassification(
            rule_class=FallbackRuleClass.WALKOVER_FIFTY_FIFTY,
            confidence=walkover_w,
            probability_fifty=0.92,
            matched=walkover_m,
            notes=["walkover_forfeit_resolves_fifty"],
        )

    # Equality/tie 50/50 (stock up/down, polling). Checked BEFORE the generic
    # 50/50 branch because the qualifying language is more specific: a stock
    # market with "closes equal -> 50/50" should land in TIE_ONLY, not the
    # forfeit-edge actionable class.
    if tie_w >= 0.5 and fifty_core_w >= 0.4:
        return RuleClassification(
            rule_class=FallbackRuleClass.TIE_ONLY,
            confidence=min(1.0, tie_w + 0.1),
            probability_fifty=0.50,
            matched=tie_m + fifty_core_m,
            notes=["tie_only_fifty_pattern_with_fifty_anchor"],
        )

    # Explicit 50/50 with no qualifying language.
    if fifty_core_w >= 0.6:
        return RuleClassification(
            rule_class=FallbackRuleClass.FIFTY_FIFTY_EXPLICIT,
            confidence=fifty_core_w,
            probability_fifty=0.90,
            matched=fifty_core_m,
            notes=["explicit_fifty_fifty_language"],
        )

    # Unknown-in-text (not outcome-list).
    if unknown_w >= 0.6:
        return RuleClassification(
            rule_class=FallbackRuleClass.UNKNOWN_EXPLICIT,
            confidence=unknown_w,
            probability_fifty=0.0,
            matched=unknown_m,
            notes=["explicit_unknown_text"],
        )

    # Equality/tie 50-50 (stock up/down, polling). Real but not a forfeit edge.
    if tie_w >= 0.5:
        return RuleClassification(
            rule_class=FallbackRuleClass.TIE_ONLY,
            confidence=tie_w,
            probability_fifty=0.50,
            matched=tie_m,
            notes=["tie_only_fifty_pattern"],
        )

    # Weak fifty signal with conflicting walkover/advance language: ambiguous.
    weak_fifty_total = fifty_core_w + walkover_w
    if 0 < weak_fifty_total < 0.6 and (advances_w > 0 or refund_w > 0):
        return RuleClassification(
            rule_class=FallbackRuleClass.UNSAFE_AMBIGUOUS,
            confidence=0.4,
            probability_fifty=0.20,
            matched=fifty_core_m + walkover_m,
            contradicting=advances_m + refund_m,
            notes=["weak_fifty_language_with_contradictions"],
        )

    # Nothing diagnostic matched.
    return RuleClassification(
        rule_class=FallbackRuleClass.NO_FALLBACK_LANGUAGE,
        confidence=0.0,
        probability_fifty=0.0,
        matched=[],
        notes=["no_fallback_language_matched"],
    )
