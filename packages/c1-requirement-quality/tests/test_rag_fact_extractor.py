"""Unit tests for the structured fact extractor module."""

import pytest

from c1_requirement_quality.rag.fact_extractor import Fact, FactExtractor, extract_facts


def test_extract_facts_empty_input_returns_empty_list():
    assert extract_facts("", use_spacy=False) == []
    assert extract_facts("   \n  ", use_spacy=False) == []


def test_extract_facts_type_error():
    with pytest.raises(TypeError, match="text must be a string"):
        extract_facts(123)  # type: ignore[arg-type]


def test_extract_facts_numeric_thresholds_and_operators():
    text = "Members must be between 18 and 65 years old."
    facts = extract_facts(text, use_spacy=False)

    assert len(facts) == 1
    fact = facts[0]
    assert fact.text == text
    assert fact.numeric_values == ("18", "65")
    assert "between" in fact.comparison_operators
    assert "years" in fact.units
    assert fact.start_offset == 0
    assert fact.end_offset == len(text)


def test_extract_facts_negation_detection():
    text = "The system shall not allow registration."
    facts = extract_facts(text, use_spacy=False)

    assert len(facts) == 1
    assert facts[0].is_negated is True
    assert facts[0].actor == "The system"


def test_negation_distinguishes_grammatical_negation_from_action_verbs():
    """Action verbs with negative polarity (reject, deny, refuse) must NOT be classified
    as grammatical negation (is_negated=False). True grammatical negators (not, no, never, cannot)
    must set is_negated=True."""
    reject_fact = extract_facts("The system shall reject invalid passwords.", use_spacy=False)[0]
    assert reject_fact.is_negated is False
    assert reject_fact.actor == "The system"

    deny_fact = extract_facts("The system shall deny unauthorized access.", use_spacy=False)[0]
    assert deny_fact.is_negated is False

    refuse_fact = extract_facts("The system shall refuse unauthenticated connections.", use_spacy=False)[0]
    assert refuse_fact.is_negated is False

    not_accept_fact = extract_facts("The system shall not accept invalid passwords.", use_spacy=False)[0]
    assert not_accept_fact.is_negated is True

    cannot_fact = extract_facts("The system cannot process expired tokens.", use_spacy=False)[0]
    assert cannot_fact.is_negated is True

    never_fact = extract_facts("The system shall never log plaintext passwords.", use_spacy=False)[0]
    assert never_fact.is_negated is True


def test_extract_facts_conditional_phrases():
    text = "The system shall lock the account when failed attempts exceed 3."
    facts = extract_facts(text, use_spacy=False)

    assert len(facts) == 1
    fact = facts[0]
    assert len(fact.conditions) >= 1
    assert "when failed attempts exceed 3" in fact.conditions[0]
    assert "3" in fact.numeric_values


def test_extract_facts_multiple_clauses_preserves_offsets():
    text = "The system shall send a reset email; the system shall log the attempt."
    facts = extract_facts(text, use_spacy=False)

    assert len(facts) == 2
    assert facts[0].text == "The system shall send a reset email"
    assert facts[0].start_offset == 0
    assert facts[0].end_offset == 35

    assert facts[1].text == "the system shall log the attempt."
    assert facts[1].start_offset == 37
    assert facts[1].end_offset == 70


@pytest.mark.parametrize("text", [
    "   Same clause. Same clause!",
    "  First clause; Second clause.  Third clause?",
])
def test_offsets_slice_exact_clause_spans(text):
    facts = extract_facts(text, use_spacy=False)
    for fact in facts:
        assert text[fact.start_offset:fact.end_offset] == fact.text


def test_numeric_constraints_keep_values_units_and_operators_together():
    text = "Applicants must be between 18 and 65 years, with at most 3 failed attempts."
    fact = extract_facts(text, use_spacy=False)[0]
    assert [(c.operator, c.values, c.unit) for c in fact.constraints] == [
        ("between", ("18", "65"), "years"),
        ("at most", ("3",), "attempts"),
    ]


def test_numeric_constraints_preserve_decimals_and_missing_unit():
    text = "The value must be >= 1.5 and less than 2.75 units."
    fact = extract_facts(text, use_spacy=False)[0]
    assert [(c.operator, c.values, c.unit) for c in fact.constraints] == [
        (">=", ("1.5",), None),
        ("less than", ("2.75",), "units"),
    ]


def test_numeric_constraints_do_not_infer_missing_operator():
    fact = extract_facts("The limit is 4 attempts.", use_spacy=False)[0]
    assert fact.constraints == ()


def test_fact_to_dict_export():
    fact = Fact(
        text="The system shall allow login.",
        actor="The system",
        action="shall allow",
        target="login",
        is_negated=False,
        start_offset=0,
        end_offset=29,
    )

    expected = {
        "text": "The system shall allow login.",
        "actor": "The system",
        "action": "shall allow",
        "target": "login",
        "is_negated": False,
        "start_offset": 0,
        "end_offset": 29,
    }

    assert fact.to_dict() == expected


def test_extractor_deterministic_fallback_mode():
    extractor = FactExtractor(use_spacy=False)
    facts = extractor.extract_facts("The system shall reject invalid passwords.")

    assert len(facts) == 1
    assert facts[0].actor == "The system"
    assert facts[0].is_negated is False  # 'reject' is an action verb, NOT grammatical negation

