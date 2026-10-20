"""Structural source comparisons retain quotes and cannot bypass grounding gates."""
from types import SimpleNamespace

import pytest

from c1_requirement_quality.analysis.grounding_analyser import analyse_grounding
from c1_requirement_quality.rag.fact_extractor import extract_facts
from c1_requirement_quality.rag.indexer import SRSIndexer
from c1_requirement_quality.rag.verifier import FactVerifier, VerificationOutcome
from c1_requirement_quality.source_comparison import obligation_text, source_comparisons


class Entailment:
    def classify(self, premise, hypothesis):
        return "entailment"


def verify(claim, source, nli=None):
    fact = extract_facts(claim, use_spacy=False)[0]
    return FactVerifier(nli).verify(fact, [SimpleNamespace(chunk_id="original-chunk", text=source)])


@pytest.mark.parametrize("label", ["LIB-001", "FR-01", "NFR-02", "REQ-EX-003"])
@pytest.mark.parametrize("separator", [" ", "  ", ": ", ". "])
def test_label_comparison_preserves_literal_evidence(label, separator):
    claim = "The system shall record audit events for account LIB-099."
    quote = label + separator + claim
    source = "# Audit\n" + quote
    lexical = analyse_grounding(claim, source)
    assert lexical["status"] == "supported"
    assert lexical["evidence"] == [{"chunk_id": "SRS-L0002-L0002", "text": quote, "section": "Audit"}]
    result = verify(claim, quote)
    assert result.outcome == VerificationOutcome.SUPPORTED
    assert result.evidence_ids == ("original-chunk",)
    assert quote[result.evidence_assessments[0]["start_offset"]:result.evidence_assessments[0]["end_offset"]] == quote
    assert result.evidence_assessments[0]["source_quote"] == quote


@pytest.mark.parametrize("source", [
    "LIB-001 shall record audit events.",
    "LIB-001 controller shall record audit events.",
    "DEVICE-001 The system shall record audit events.",
    "LIB-001 Record audit events.",
])
def test_ambiguous_or_unknown_prefix_is_not_removed(source):
    assert obligation_text(source) == source
    assert analyse_grounding("The system shall record audit events.", source)["status"] == "unsupported"
    assert verify("The system shall record audit events.", source, Entailment()).outcome == VerificationOutcome.INCONCLUSIVE


@pytest.mark.parametrize("source", [
    "LIB-002 The system shall retain audit events.",
    "LIB-002 The system shall record audit events for account LIB-002.",
    "LIB-002 The system shall record audit events when the account is inactive.",
])
def test_entailment_does_not_hide_different_behavior_identifiers_or_conditions(source):
    claim = "The system shall record audit events for account LIB-001."
    assert analyse_grounding(claim, source)["status"] != "supported"
    result = verify(claim, source, Entailment())
    assert result.outcome == VerificationOutcome.INCONCLUSIVE
    assert result.evidence_ids == ()
    assert result.evidence_assessments[0]["raw_nli_label"] == "entailment"


def test_candidate_identifier_is_never_treated_as_a_source_label():
    source = "The system shall retain logs."
    claim = "LIB-002 The system shall retain logs."
    assert analyse_grounding(claim, source)["status"] != "supported"
    assert verify(claim, source, Entailment()).outcome == VerificationOutcome.INCONCLUSIVE


@pytest.mark.parametrize("label", ["LIB-007", "FR-01", "NFR-02", "REQ-EX-003"])
def test_numeric_obligation_preserves_numbers_units_and_operator(label):
    claim = "The system shall allow at most 3 attempts."
    assert verify(claim, label + " " + claim).outcome == VerificationOutcome.SUPPORTED
    for other in ["at most 5 attempts", "at most 3 seconds", "at least 5 attempts"]:
        source = label + " The system shall allow " + other + "."
        assert analyse_grounding(claim, source)["status"] != "supported"
        assert verify(claim, source, Entailment()).outcome != VerificationOutcome.SUPPORTED
    assert verify(claim, label + " The system shall allow at least 5 attempts.").outcome == VerificationOutcome.CONTRADICTED


def test_wrapped_labelled_source_keeps_exact_multiline_quote_and_chunk():
    source = "LIB-001 The system shall retain logs\nfor at least 3 days."
    claim = "The system shall retain logs for at least 3 days."
    lexical = analyse_grounding(claim, source)
    assert lexical["status"] == "supported"
    assert lexical["evidence"] == [{"chunk_id": "SRS-L0001-L0002", "text": source}]
    chunks = SRSIndexer(source).chunk_document()
    before = [c.to_dict() for c in chunks]
    result = FactVerifier().verify(extract_facts(claim, use_spacy=False)[0], chunks)
    assert result.outcome == VerificationOutcome.SUPPORTED
    assert result.evidence_ids == ("SRS-L0001-L0002",)
    assert [c.to_dict() for c in chunks] == before


def table(*rows):
    return "| ID | Statement |\n| --- | --- |\n" + "\n".join("| " + label + " | " + body + " |" for label, body in rows)


def test_verified_table_rows_keep_quotes_offsets_and_original_chunk():
    claim = "The system shall retain logs for at least 3 days."
    source = table(("LIB-001", claim), ("FR-02", "The system shall send email."))
    views = source_comparisons(source)
    assert len(views) == 2
    for view in views:
        assert source[view.start_offset:view.end_offset] == view.text
    lexical = analyse_grounding(claim, source)
    assert lexical["status"] == "supported"
    assert lexical["evidence"] == [{"chunk_id": "SRS-L0001-L0004", "text": views[0].text}]
    result = verify(claim, source, Entailment())
    assert result.outcome == VerificationOutcome.SUPPORTED
    assert result.evidence_ids == ("original-chunk",)
    assert [a["outcome"] for a in result.evidence_assessments] == ["SUPPORTED", "INCONCLUSIVE"]
    for audit in result.evidence_assessments:
        assert source[audit["start_offset"]:audit["end_offset"]] == audit["source_quote"]


@pytest.mark.parametrize("source", [
    "| LIB-001 | The system shall retain logs. |",
    "| Actor | Statement |\n| --- | --- |\n| LIB-001 | The system shall retain logs. |",
    "| ID | Statement |\n| --- | --- |\n| LIB-001 | The system shall retain logs. |\n| unknown | Other text |",
    "| ID | Statement | Extra |\n| --- | --- | --- |\n| LIB-001 | The system shall retain logs. | unless disabled |",
])
def test_unverified_or_extra_column_tables_cannot_supply_selected_cells(source):
    assert source_comparisons(source)[0].comparison_text == source
    assert verify("The system shall retain logs.", source, Entailment()).outcome == VerificationOutcome.INCONCLUSIVE


@pytest.mark.parametrize("reverse", [False, True])
def test_table_support_cannot_hide_conflicting_row(reverse):
    claim = "The system shall allow login."
    rows = [("LIB-001", claim), ("LIB-002", "The system shall not allow login.")]
    source = table(*(rows[::-1] if reverse else rows))
    result = verify(claim, source, Entailment())
    assert result.outcome == VerificationOutcome.CONTRADICTED
    assert set(outcome for _, outcome in result.evidence_outcomes) == {"SUPPORTED", "CONTRADICTED"}
    lexical = analyse_grounding(claim, source)
    assert lexical["status"] == "partially_supported"
    assert len(lexical["evidence"]) == 2


def test_table_view_does_not_bypass_whole_passage_placeholder_guard():
    claim = "The system shall allow login."
    source = table(("LIB-001", claim), ("LIB-002", "The system shall retain logs for [DAYS] days."))
    assert verify(claim, source, Entailment()).outcome == VerificationOutcome.INCONCLUSIVE
