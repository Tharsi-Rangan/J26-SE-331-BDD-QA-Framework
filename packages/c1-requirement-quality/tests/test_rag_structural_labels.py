"""Structural IDs affect comparisons only; quotes and safeguards remain literal."""
from types import SimpleNamespace
import pytest
from c1_requirement_quality.rag.fact_extractor import extract_facts
from c1_requirement_quality.rag.verifier import FactVerifier, VerificationOutcome, evidence_applicability


def evidence(text, key='source'):
    return SimpleNamespace(text=text, chunk_id=key)


@pytest.mark.parametrize('prefix', ['', 'FR-01  ', 'NFR-02: ', 'REQ-EX-003 '])
def test_exact_source_label_preserves_provenance(prefix):
    fact = extract_facts('The system shall record audit events.', use_spacy=False)[0]
    item = evidence(prefix + fact.text)
    result = FactVerifier().verify(fact, [item])
    assert result.outcome == VerificationOutcome.SUPPORTED
    assert item.text == prefix + fact.text
    assert result.evidence_ids == ('source',)


def test_label_does_not_merge_entity_ids_or_different_obligations():
    fact = extract_facts('The system shall notify account 1.', use_spacy=False)[0]
    for text in ['FR-02 The system shall notify account 2.', 'FR-02 The system shall retain logs.']:
        assert evidence_applicability(fact, text) == 'UNCERTAIN'
        assert FactVerifier().verify(fact, [evidence(text)]).outcome == VerificationOutcome.INCONCLUSIVE


def test_labelled_contradiction_wins_over_exact_support():
    fact = extract_facts('The system shall retain logs.', use_spacy=False)[0]
    result = FactVerifier().verify(fact, [evidence('FR-01 ' + fact.text),
        evidence('FR-02 The system shall not retain logs.', 'conflict')])
    assert result.outcome == VerificationOutcome.CONTRADICTED
    assert set(result.evidence_ids) == {'source', 'conflict'}


def test_labelled_numeric_conflict_and_conditions_stay_distinct():
    fact = extract_facts('The system shall allow at most 3 attempts.', use_spacy=False)[0]
    result = FactVerifier().verify(fact, [evidence('NFR-01 The system shall allow at least 5 attempts.')])
    assert result.outcome == VerificationOutcome.CONTRADICTED
    fact = extract_facts('The system shall allow login when credentials are valid.', use_spacy=False)[0]
    assert evidence_applicability(fact, 'FR-01 The system shall allow login when credentials are invalid.') == 'UNCERTAIN'


def test_labelled_unrelated_raw_entailment_never_authorizes_support():
    class NLI:
        def classify(self, premise, hypothesis):
            return 'entailment'
    fact = extract_facts('The system shall send email.', use_spacy=False)[0]
    result = FactVerifier(NLI()).verify(fact, [evidence('FR-01 The system shall retain logs.')])
    assert result.outcome == VerificationOutcome.INCONCLUSIVE
    assert not result.evidence_ids
    assert result.evidence_assessments[0]['raw_nli_label'] == 'entailment'
