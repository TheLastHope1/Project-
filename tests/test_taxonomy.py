"""Unit tests for the structured rule classifier.

Fixture wording is intentionally drawn from real Polymarket rule snippets
cited in the review PDF (CS2 map markets, ITF tennis moneylines, boxing
no-contest rules, method-of-victory markets, AI competition markets, etc.)
so the classifier is being checked against the same evidence that motivated
its design.
"""
from polymarket_scanner.taxonomy import (
    FallbackRuleClass,
    classify_rules,
)


def test_explicit_fifty_fifty_walkover():
    text = (
        "If the match is incomplete due to forfeiture, disqualification, "
        "or walkover, the market resolves 50/50. Both tokens redeem at $0.50."
    )
    r = classify_rules(text)
    assert r.rule_class is FallbackRuleClass.WALKOVER_FIFTY_FIFTY
    assert r.probability_fifty >= 0.85
    assert r.is_tradable_fifty_fifty


def test_clinching_map_exception_is_not_pure_walkover():
    # The CS2-style "clinching map forfeit counts as completed" wording is
    # the canonical false-positive trap for the simple walkover regex.
    text = (
        "An incomplete match due to forfeiture, disqualification, or walkover "
        "resolves 50/50. However, a clinching map forfeit is counted as a "
        "completed match for resolution purposes."
    )
    r = classify_rules(text)
    assert r.rule_class is FallbackRuleClass.CLINCHING_EXCEPTION
    # Still mostly fifty-fifty, but lower than a pure WALKOVER case.
    assert 0.55 <= r.probability_fifty <= 0.75


def test_tennis_advancing_player_overrides_fifty():
    # Pre-match walkover yields 50/50, but once play begins the advancing
    # player wins on retirement/default. The classifier should pick the
    # advancing-player class, NOT WALKOVER_FIFTY_FIFTY.
    text = (
        "If the match is cancelled, tied, or delayed before play begins, the "
        "market resolves 50/50. Once play has begun, the player who advances "
        "through retirement, default, or disqualification is declared the winner."
    )
    r = classify_rules(text)
    assert r.rule_class is FallbackRuleClass.ADVANCES_IF_STARTED
    assert r.probability_fifty <= 0.40
    assert not r.is_tradable_fifty_fifty


def test_other_outcome_routing_takes_precedence():
    text = (
        "If no winner is announced or the fight is cancelled or delayed "
        "beyond October 1, the market resolves to Other."
    )
    r = classify_rules(text, outcomes=["Knockout", "Decision", "Other"])
    assert r.rule_class is FallbackRuleClass.OTHER_OUTCOME
    assert r.probability_fifty == 0.0


def test_unknown_outcome_in_outcome_list():
    # Multi-outcome competition markets sometimes carry a literal "Unknown"
    # leg. That's structural, not text, so classification should respect it.
    r = classify_rules(
        "Winner of the AI trading competition.",
        outcomes=["Team A", "Team B", "Unknown"],
    )
    assert r.rule_class is FallbackRuleClass.UNKNOWN_EXPLICIT
    assert r.confidence >= 0.9


def test_refund_void_overrides_everything():
    text = (
        "If the event does not occur, the market will be voided and all "
        "trades will be refunded. The market will not resolve 50/50."
    )
    r = classify_rules(text)
    assert r.rule_class is FallbackRuleClass.REFUND_VOID
    assert r.probability_fifty == 0.0


def test_cricket_tie_class():
    text = (
        "If the cricket match ends in a tie and no super over is used, the "
        "market resolves 50/50."
    )
    r = classify_rules(text)
    assert r.rule_class is FallbackRuleClass.CRICKET_TIE_FIFTY
    assert r.probability_fifty >= 0.80


def test_tie_only_stock_market_style():
    text = (
        "If the closing price is equal to the previous close, the market "
        "resolves 50/50."
    )
    r = classify_rules(text)
    assert r.rule_class is FallbackRuleClass.TIE_ONLY
    # Tradable as a 50/50 in the abstract, but not a forfeit-edge market.
    assert not r.is_tradable_fifty_fifty


def test_no_fallback_language_returns_marker_class():
    r = classify_rules("Will FaZe beat eyeballers in IEM Katowice?")
    assert r.rule_class is FallbackRuleClass.NO_FALLBACK_LANGUAGE
    assert r.confidence == 0.0
    assert r.probability_fifty == 0.0


def test_empty_rule_text_handled():
    r = classify_rules("")
    assert r.rule_class is FallbackRuleClass.NO_FALLBACK_LANGUAGE


def test_classification_to_dict_is_jsonable():
    import json
    r = classify_rules("This market resolves 50/50 on walkover.")
    d = r.to_dict()
    json.dumps(d)  # must not raise
    assert d["rule_class"] == r.rule_class.value
    assert 0 <= d["confidence"] <= 1
