from dataclasses import dataclass
import pytest

from c1_requirement_quality.rag.fact_extractor import extract_facts
from c1_requirement_quality.rag.verifier import (
    FactVerifier, LocalNLI, VerificationOutcome, verify_symbolically,
)
from c1_requirement_quality.rag.model_loading import RAGModelLoadError


@dataclass
class Evidence:
    chunk_id: str
    text: str


class FakeNLI:
    def __init__(self, label="entailment"):
        self.label = label

    def classify(self, premise, hypothesis):
        return self.label


def test_exact_fact_is_symbolically_supported():
    fact = extract_facts("The system shall allow login.", use_spacy=False)[0]
    result = FactVerifier().verify(fact, [Evidence("SRS-L1", fact.text)])
    assert result.outcome is VerificationOutcome.SUPPORTED


def test_same_claim_with_negation_is_contradicted():
    fact = extract_facts("The system shall allow login.", use_spacy=False)[0]
    result = verify_symbolically(fact, "The system shall not allow login.", "SRS-L1")
    assert result.outcome is VerificationOutcome.CONTRADICTED


def test_overlapping_numeric_thresholds_are_not_misclassified_as_contradiction():
    fact = extract_facts("The system allows at most 3 attempts.", use_spacy=False)[0]
    result = verify_symbolically(fact, "The system allows at most 5 attempts.", "SRS-L1")
    assert result.outcome is VerificationOutcome.INCONCLUSIVE


def test_narrower_source_numeric_limit_supports_broader_claim():
    fact = extract_facts("The system allows at most 5 attempts.", use_spacy=False)[0]
    result = verify_symbolically(fact, "The system allows at most 3 attempts.", "SRS-L1")
    assert result.outcome is VerificationOutcome.SUPPORTED


def test_disjoint_numeric_bounds_with_same_unit_contradict():
    fact = extract_facts("The system allows at most 3 attempts.", use_spacy=False)[0]
    result = verify_symbolically(fact, "The system allows at least 5 attempts.", "SRS-L1")
    assert result.outcome is VerificationOutcome.CONTRADICTED


def test_missing_evidence_is_inconclusive():
    fact = extract_facts("The system shall allow login.", use_spacy=False)[0]
    assert FactVerifier(FakeNLI()).verify(fact, []).outcome is VerificationOutcome.INCONCLUSIVE


def test_nli_is_injectable_and_used_only_after_symbolic_abstention():
    fact = extract_facts("The system shall allow login.", use_spacy=False)[0]
    result = FactVerifier(FakeNLI("entailment")).verify(fact, [Evidence("SRS-L1", "The system must allow login.")])
    assert result.outcome is VerificationOutcome.SUPPORTED
    assert result.method == "nli"


def test_inference_failure_is_explicit_error():
    class BrokenNLI:
        def classify(self, premise, hypothesis):
            raise RuntimeError("model inference failed")

    fact = extract_facts("Users can sign in.", use_spacy=False)[0]
    result = FactVerifier(BrokenNLI()).verify(fact, [Evidence("SRS-L1", "Users may log in.")])
    assert result.outcome is VerificationOutcome.ERROR
    assert "model inference failed" in result.diagnostic


def test_local_nli_sends_a_premise_hypothesis_pair():
    nli = LocalNLI()
    received = {}

    def fake_pipeline(inputs, **kwargs):
        received.update(inputs)
        return [{"label": "entailment"}]

    nli._pipeline = fake_pipeline
    assert nli.classify("Source evidence", "Requirement claim") == "entailment"
    assert received == {"text": "Source evidence", "text_pair": "Requirement claim"}


def test_nli_model_load_failure_names_component_and_model():
    class BrokenNLI:
        model_name = "cross-encoder/test-model"

        def classify(self, premise, hypothesis):
            raise RAGModelLoadError(
                "nli", self.model_name, OSError("weights are not cached")
            )

    fact = extract_facts("Users may sign in.", use_spacy=False)[0]
    result = FactVerifier(BrokenNLI()).verify(fact, [Evidence("SRS-L1", "Users can sign in.")])
    assert result.outcome is VerificationOutcome.ERROR
    assert result.component == "nli"
    assert result.model_name == "cross-encoder/test-model"
    assert "weights are not cached" in result.diagnostic


@pytest.mark.parametrize("reverse", [False, True])
def test_symbolic_support_cannot_hide_contradictory_passage(reverse):
    fact = extract_facts("The system shall allow login.", use_spacy=False)[0]
    evidence = [Evidence("support", fact.text),
                Evidence("conflict", "The system shall not allow login.")]
    result = FactVerifier().verify(fact, list(reversed(evidence)) if reverse else evidence)
    assert result.outcome is VerificationOutcome.CONTRADICTED
    assert set(result.evidence_ids) == {"support", "conflict"}
    assert dict(result.evidence_outcomes) == {"support": "SUPPORTED", "conflict": "CONTRADICTED"}


@pytest.mark.parametrize("reverse", [False, True])
def test_nli_aggregates_all_passages_and_attributes_only_matched_evidence(reverse):
    class PerPassageNLI:
        def classify(self, premise, hypothesis):
            return {"The system must allow login.": "entailment", "The system must not allow login.": "contradiction",
                    "unrelated topic": "neutral"}[premise]

    fact = extract_facts("The system shall allow login.", use_spacy=False)[0]
    evidence = [Evidence("support", "The system must allow login."), Evidence("conflict", "The system must not allow login."),
                Evidence("neutral", "unrelated topic")]
    result = FactVerifier(PerPassageNLI()).verify(fact, list(reversed(evidence)) if reverse else evidence)
    assert result.outcome is VerificationOutcome.CONTRADICTED
    assert set(result.evidence_ids) == {"support", "conflict"}
    assert dict(result.evidence_outcomes)["neutral"] == "INCONCLUSIVE"


def test_symbolic_support_does_not_skip_nli_contradiction():
    fact = extract_facts("The system shall allow login.", use_spacy=False)[0]
    result = FactVerifier(FakeNLI("contradiction")).verify(fact, [
        Evidence("support", fact.text), Evidence("conflict", "The system must not allow login.")])
    assert result.outcome is VerificationOutcome.CONTRADICTED
    assert dict(result.evidence_outcomes) == {"support": "SUPPORTED", "conflict": "CONTRADICTED"}


def test_neutral_passage_is_not_attributed_as_support():
    class PerPassageNLI:
        def classify(self, premise, hypothesis):
            return "entailment" if premise == "The system must allow login." else "neutral"

    fact = extract_facts("The system shall allow login.", use_spacy=False)[0]
    result = FactVerifier(PerPassageNLI()).verify(fact, [
        Evidence("support", "The system must allow login."), Evidence("neutral", "Audit logging.")])
    assert result.outcome is VerificationOutcome.SUPPORTED
    assert result.evidence_ids == ("support",)


def test_partial_inference_failure_preserves_conflict_and_prevents_success():
    class BrokenNLI:
        def classify(self, premise, hypothesis):
            raise RuntimeError("failed passage")

    fact = extract_facts("The system shall allow login.", use_spacy=False)[0]
    result = FactVerifier(BrokenNLI()).verify(fact, [
        Evidence("support", fact.text), Evidence("error", "Other wording."),
        Evidence("conflict", "The system shall not allow login.")])
    assert result.outcome is VerificationOutcome.ERROR
    assert "failed passage" in result.diagnostic
    assert dict(result.evidence_outcomes) == {
        "support": "SUPPORTED", "error": "ERROR", "conflict": "CONTRADICTED"}


@pytest.mark.parametrize("reverse", [False, True])
def test_unrelated_nli_contradiction_is_audited_as_uncertain(reverse):
    fact = extract_facts("The system shall send a confirmation email after registration.", use_spacy=False)[0]
    evidence = [Evidence("support", fact.text), Evidence("unrelated", "The system shall retain audit logs for at most 7 days.")]
    result = FactVerifier(FakeNLI("contradiction")).verify(fact, evidence[::-1] if reverse else evidence)
    assert result.outcome is VerificationOutcome.INCONCLUSIVE
    assert result.evidence_ids == ("support",)
    audit = next(r for r in result.evidence_assessments if r["chunk_id"] == "unrelated")
    assert audit["applicability"] == "UNCERTAIN" and audit["raw_nli_label"] == "contradiction"
    assert audit["outcome"] == "INCONCLUSIVE"


@pytest.mark.parametrize("claim", ["The system shall respond within [RESPONSE_TIME].",
    "The system shall respond within TBD.", "The system shall respond within TBC.",
    "The system shall respond within a value to be determined."])
def test_placeholder_self_support_abstains_before_symbolic_or_nli(claim):
    class ForbiddenNLI:
        def classify(self, *args):
            pytest.fail("Placeholder claims must abstain before inference")
    fact = extract_facts(claim, use_spacy=False)[0]
    assert verify_symbolically(fact, claim, "self").outcome is VerificationOutcome.INCONCLUSIVE
    result = FactVerifier(ForbiddenNLI()).verify(fact, [Evidence("self", claim)])
    assert result.outcome is VerificationOutcome.INCONCLUSIVE and result.evidence_ids == ()
    assert result.evidence_assessments[0]["applicability"] == "INCOMPLETE"


def test_placeholder_evidence_cannot_support_concrete_value():
    fact = extract_facts("The system shall respond within 2 seconds.", use_spacy=False)[0]
    result = FactVerifier(FakeNLI("entailment")).verify(fact, [Evidence("missing", "The system shall respond within [RESPONSE_TIME].")])
    assert result.outcome is VerificationOutcome.INCONCLUSIVE and not result.evidence_ids


def test_unrelated_entailment_is_not_factual_support():
    fact = extract_facts("The system shall send email.", use_spacy=False)[0]
    result = FactVerifier(FakeNLI("entailment")).verify(fact, [Evidence("audit", "The system shall retain logs.")])
    assert result.outcome is VerificationOutcome.INCONCLUSIVE and not result.evidence_ids
    assert result.evidence_assessments[0]["raw_nli_label"] == "entailment"


def test_genuine_numeric_contradiction_retains_precedence_over_uncertain_nli():
    fact = extract_facts("The system shall allow at most 3 attempts.", use_spacy=False)[0]
    result = FactVerifier(FakeNLI("contradiction")).verify(fact, [
        Evidence("support", fact.text), Evidence("conflict", "The system shall allow at least 5 attempts."),
        Evidence("unrelated", "The system shall send email.")])
    assert result.outcome is VerificationOutcome.CONTRADICTED
    assert dict(result.evidence_outcomes)["conflict"] == "CONTRADICTED"


def test_applicability_does_not_merge_different_conditions():
    fact = extract_facts("The system shall allow login when credentials are valid.", use_spacy=False)[0]
    result = FactVerifier(FakeNLI("contradiction")).verify(fact, [
        Evidence("other_condition", "The system must not allow login when credentials are invalid.")])
    assert result.outcome is VerificationOutcome.INCONCLUSIVE


def test_retention_days_are_compared_symbolically_with_matching_units():
    fact = extract_facts("The system shall retain audit logs for at least 30 days.", use_spacy=False)[0]
    result = FactVerifier().verify(fact, [Evidence("policy", "The system shall retain audit logs for at most 7 days.")])
    assert fact.constraints[0].unit == "days"
    assert result.outcome is VerificationOutcome.CONTRADICTED and result.method == "symbolic_numeric"


def test_nli_applicability_preserves_literal_quantities_and_entity_numbers():
    from c1_requirement_quality.rag.verifier import evidence_applicability
    fact = extract_facts("The system shall notify account 1 within 2 seconds.", use_spacy=False)[0]
    assert evidence_applicability(fact, "The system must notify account 2 within 2 seconds.") == "UNCERTAIN"
    assert evidence_applicability(fact, "The system must notify account 1 within 5 seconds.") == "UNCERTAIN"
