"""Bounded numeric/policy reasoning; no models, providers or policy selection."""
import pytest

from c1_requirement_quality.analysis.consistency_analyser import analyse_consistency, consistency_for_requirement
from c1_requirement_quality.tier_classifier import classify_tier
from c1_requirement_quality.bdd_readiness import evaluate_bdd_readiness

LOAN = "A student shall be allowed to borrow a maximum of {} books at a time."
DEFINITION = "The maximum simultaneous loan count shall be {} books."


def pair(left, right):
    return analyse_consistency([{"requirement_id": "LIB-007", "text": left}, {"requirement_id": "LIB-008", "text": right}])["pairs"][0]


@pytest.mark.parametrize("left,right", [("three", "five"), ("3", "5"), ("three", "5"), ("3", "five")])
@pytest.mark.parametrize("reverse", [False, True])
def test_library_policy_disagreement_in_both_orders(left, right, reverse):
    texts = [LOAN.format(left), LOAN.format(right)]
    if reverse:
        texts.reverse()
    result = pair(*texts)
    assert result["classification"] == "conflict"
    assert result["conflict_kind"] == "policy_definition_disagreement"
    assert result["human_resolution_required"] is True
    assert "Neither value" in result["explanation"]
    assert [e["text"] for e in result["evidence"]] == texts
    for e, text in zip(result["evidence"], texts, strict=True):
        assert text[e["start_offset"]:e["end_offset"]] == e["text"]


@pytest.mark.parametrize("template", [LOAN, DEFINITION])
@pytest.mark.parametrize("word,digit", [("zero", "0"), ("three", "3"), ("five", "5"), ("twenty", "20")])
def test_number_words_equal_digits_only_in_supported_definition(template, word, digit):
    assert pair(template.format(word), template.format(digit))["classification"] == "consistent"


def test_exact_policy_assignment_is_not_an_overlapping_upper_bound():
    assert pair(DEFINITION.format("three"), DEFINITION.format("5"))["conflict_kind"] == "policy_definition_disagreement"
    for left, right in [("three", "5"), ("3", "five")]:
        result = pair(f"The system shall allow at most {left} attempts.", f"The system shall allow at most {right} attempts.")
        assert result["classification"] == "consistent"
        assert "conflict_kind" not in result
    assert pair("The age must be at least eighteen years.", "The age must be at most 17 years.")["classification"] == "conflict"
    assert pair(DEFINITION.format("9007199254740992"), DEFINITION.format("9007199254740993"))["classification"] == "conflict"
    assert pair(DEFINITION.format("three"), DEFINITION.format("3.0"))["classification"] == "consistent"


@pytest.mark.parametrize("replacement", [
    "A librarian shall be allowed to borrow a maximum of five books at a time.",
    "A student shall be allowed to reserve a maximum of five books at a time.",
    "A student shall be allowed to borrow a maximum of five loans at a time.",
    "A student shall be allowed to borrow a maximum of five books at a time when registered.",
    "A student shall be allowed to borrow a maximum of five books at a time except during holidays.",
    "A student should be allowed to borrow a maximum of five books at a time.",
    "A student shall be allowed to borrow a maximum of twenty-one books at a time.",
])
def test_uncertain_policy_scope_does_not_become_a_confirmed_conflict(replacement):
    assert pair(LOAN.format("three"), replacement)["classification"] == "unassessed"


@pytest.mark.parametrize("value", ["twenty-one", "several", "one hundred", "-3", "3e2"])
def test_unsupported_policy_values_abstain(value):
    assert pair(DEFINITION.format(value), DEFINITION.format("five"))["classification"] == "unassessed"


def test_unknown_unit_and_nonnumeric_word_contexts_are_not_normalized():
    assert pair("The system shall allow at most three widgets.", "The system shall allow at most 5 widgets.")["classification"] == "unassessed"
    assert pair("The system shall display three books.", "The system shall display 3 books.")["classification"] == "unassessed"
    assert pair("The maximum response time shall be three seconds.", "The maximum response time shall be 5 minutes.")["classification"] == "unassessed"


@pytest.mark.parametrize("left,right", [
    (LOAN.format("three").replace("A student", "A group-3 student"), LOAN.format("five").replace("A student", "A group3 student")),
    (LOAN.format("three")[:-1] + " when group-3 is active.", LOAN.format("five")[:-1] + " when group3 is active."),
    ("The maximum model-3 count shall be three books.", "The maximum model3 count shall be five books."),
])
def test_policy_identifiers_remain_literal(left, right):
    assert pair(left, right)["classification"] == "unassessed"
    assert pair(left, right.replace("five", "three"))["classification"] == "unassessed"


@pytest.mark.parametrize("template", [LOAN, DEFINITION])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("left,right", [("three", "three"), ("three", "3")])
def test_policy_definition_does_not_hide_explicit_negation(template, reverse, left, right):
    texts = [template.format(left), template.format(right).replace("shall be", "shall not be")]
    result = pair(*(texts[::-1] if reverse else texts))
    assert result["classification"] == "conflict"
    assert "negation" in result["explanation"]
    assert "conflict_kind" not in result  # A grammatical contradiction, not competing limits.


def test_negative_assignment_does_not_choose_an_alternative_limit():
    assert pair(DEFINITION.format("three"), DEFINITION.format("five").replace("shall be", "shall not be"))["classification"] == "unassessed"


@pytest.mark.parametrize("reverse", [False, True])
def test_policy_rule_preserves_disjoint_bound_contradictions(reverse):
    texts = [LOAN.format("three"), LOAN.format("five").replace("maximum", "minimum")]
    result = pair(*(texts[::-1] if reverse else texts))
    assert result["classification"] == "conflict"
    assert "no overlapping value" in result["explanation"]
    assert "conflict_kind" not in result


def test_conflicting_policies_block_tier1_and_readiness_even_with_source_support():
    text = LOAN.format("three")
    analysis = analyse_consistency([{"requirement_id": "LIB-007", "text": text}, {"requirement_id": "LIB-008", "text": LOAN.format("five")}])
    for rid in ("LIB-007", "LIB-008"):
        result = consistency_for_requirement(rid, analysis)
        assert (result["status"], result["check"]) == ("conflict", "fail")
        tier = classify_tier([], {"status": "supported", "evidence": [{"text": text}]}, result,
                             original_text=text, candidate_text=text, human_reviewed=True)
        assert tier["tier"] == "TIER_3_ESCALATE"
        assert tier["reasons"][0]["kind"] == "confirmed_policy_conflict"
        ready = evaluate_bdd_readiness(text, quality_check="pass", grounding_check="pass", consistency_check="fail",
                                     consistency_result=result, tier=tier["tier"])
        assert ready["check"] == "fail"
