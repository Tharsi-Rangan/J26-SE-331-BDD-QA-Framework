from dataclasses import dataclass

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
    fact = extract_facts("Users can sign in.", use_spacy=False)[0]
    result = FactVerifier(FakeNLI("entailment")).verify(fact, [Evidence("SRS-L1", "Users may log in.")])
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
