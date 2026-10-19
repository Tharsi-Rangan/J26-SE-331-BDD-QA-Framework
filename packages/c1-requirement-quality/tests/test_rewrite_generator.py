"""Tests for automated multi-candidate requirement rewrite generator."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from c1_requirement_quality.cli import _validate_contract_artifact, main
from c1_requirement_quality.refinement import (
    clarification_questions_for,
    process_refinement_actions,
    stable_candidate_id,
)
from c1_requirement_quality.rewrite_generator import (
    DeterministicSubstitutionBackend,
    check_eligibility,
    generate_candidate_suggestions,
    generate_candidates_run,
)
from c1_requirement_quality.tier_classifier import TIER_1, TIER_2, TIER_3


def _minimal_artifact(requirements: list[dict[str, Any]], srs_name: str = "test.srs") -> dict[str, Any]:
    return {
        "contract": "c1.validated-requirements",
        "schema_version": "1.0.0",
        "producer": {"component": "C1", "tool_version": "0.1.0"},
        "run_id": "RUN-20261009-181600-ab12",
        "generated_at": "2026-10-09T18:16:00Z",
        "source_document": {
            "name": srs_name,
            "project_code": "EX",
            "path": srs_name,
            "redaction_applied": False,
        },
        "requirements": requirements,
    }


def _req(
    req_id: str,
    text: str,
    tier: str = TIER_1,
    defects: list[dict[str, Any]] | None = None,
    consistency_status: str = "consistent",
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "requirement_id": req_id,
        "source": {"section": "Requirements", "line": 1},
        "original_text": text,
        "final_text": text,
        "human_decision": "pending",
        "selected_candidate_id": None,
        "bdd_ready": False,
        "defects": defects or [],
        "grounding": {
            "status": "supported",
            "evidence": evidence or [{
                "chunk_id": f"SRS-{req_id}",
                "text": text,
            }],
        },
        "consistency": {
            "status": consistency_status,
            "related_requirement_ids": [],
            "conflicts": [],
        },
        "tier": tier,
        "validation": {
            "status": "needs_review",
            "checks": {
                "quality": "fail" if defects else "pass",
                "grounding": "pass",
                "consistency": "pass" if consistency_status == "consistent" else "skipped",
                "bdd_readiness": "skipped",
            },
        },
        "candidates": [],
    }


# T-01: Generates candidates when SRS evidence supports substitution
def test_generates_candidates_when_srs_evidence_supports_substitution():
    srs = "The service shall respond within 2 seconds. The service may respond within 2 seconds."
    req = _req(
        "REQ-EX-001",
        "The service may respond within 2 seconds.",
        tier=TIER_1,
        defects=[{"type": "ambiguous", "detector": "rule", "explanation": "uses weak modal may"}],
    )
    artifact = _minimal_artifact([req])
    sidecar = generate_candidate_suggestions(artifact, srs)

    req_out = sidecar["requirements"][0]
    assert req_out["blocked"] is False
    assert len(req_out["ranked_candidates"]) >= 1
    assert any("shall" in c["text"] for c in req_out["ranked_candidates"])


# T-02: All generated candidates have distinct texts
def test_all_generated_candidates_have_different_texts():
    srs = "The service shall respond within 2 seconds. The service may respond quickly within 2 seconds."
    req = _req("REQ-EX-001", "The service may respond quickly within 2 seconds.", tier=TIER_1)
    artifact = _minimal_artifact([req])
    sidecar = generate_candidate_suggestions(artifact, srs)

    cands = sidecar["requirements"][0]["ranked_candidates"]
    texts = [c["text"] for c in cands]
    assert len(texts) == len(set(texts))


# T-03: Unsupported facts are rejected
def test_unsupported_facts_are_rejected():
    class HallucinatingBackend:
        def generate(self, text, defects, evidence_chunks, clarification_answers, *, max_candidates=3):
            return [{
                "text": "The service shall respond within 9999 gigawatts.",
                "strategy": "hallucination",
                "source_evidence": {"kind": "srs_chunk", "chunk_id": "FAKE", "text": "not in srs", "source": "lexical"},
            }]

    srs = "The service may respond within 2 seconds."
    req = _req("REQ-EX-001", "The service may respond within 2 seconds.")
    artifact = _minimal_artifact([req])
    sidecar = generate_candidate_suggestions(artifact, srs, backend=HallucinatingBackend())

    req_out = sidecar["requirements"][0]
    assert len(req_out["ranked_candidates"]) == 0
    assert len(req_out["rejected_candidates"]) >= 1
    assert req_out["rejected_candidates"][0]["rejected_reason"] == "unsupported_facts"


# T-04: Quality regression candidate is rejected
def test_quality_regression_candidate_is_rejected():
    class RegressingBackend:
        def generate(self, text, defects, evidence_chunks, clarification_answers, *, max_candidates=3):
            return [{
                "text": "The service shall respond within 2 seconds and [TBD].",
                "strategy": "bad_rewrite",
                "source_evidence": {"kind": "srs_chunk", "chunk_id": "SRS-1", "text": text, "source": "lexical"},
            }]

    srs = "The service may respond within 2 seconds."
    req = _req("REQ-EX-001", "The service may respond within 2 seconds.", defects=[{"type": "ambiguous", "detector": "rule", "explanation": "ambiguous"}])
    artifact = _minimal_artifact([req])
    sidecar = generate_candidate_suggestions(artifact, srs, backend=RegressingBackend())

    req_out = sidecar["requirements"][0]
    assert len(req_out["ranked_candidates"]) == 0
    assert any(c["rejected_reason"] == "quality_regression" for c in req_out["rejected_candidates"])


# T-05: Tier 2 open questions block generation
def test_tier2_open_questions_blocks_generation():
    srs = "The system shall timeout after [timeout]."
    req = _req("REQ-EX-001", "The system shall timeout after [timeout].", tier=TIER_2)
    artifact = _minimal_artifact([req])
    sidecar = generate_candidate_suggestions(artifact, srs)

    req_out = sidecar["requirements"][0]
    assert req_out["blocked"] is True
    assert req_out["blocked_reason"] == "tier2_open_questions"
    assert len(req_out["open_questions"]) == 1
    assert len(req_out["ranked_candidates"]) == 0


# T-06: Tier 2 with all questions answered is eligible
def test_tier2_with_all_questions_answered_is_eligible():
    srs = "The system shall timeout after [timeout]."
    req = _req("REQ-EX-001", "The system shall timeout after [timeout].", tier=TIER_2)
    artifact = _minimal_artifact([req])
    q = clarification_questions_for("The system shall timeout after [timeout].")[0]
    answers = [{"question": q, "answer": "2 seconds"}]
    sidecar = generate_candidate_suggestions(artifact, srs, clarification_answers=answers)

    req_out = sidecar["requirements"][0]
    assert req_out["blocked"] is False
    assert len(req_out["ranked_candidates"]) >= 1
    assert req_out["ranked_candidates"][0]["text"] == "The system shall timeout after 2 seconds."


# T-07: Tier 3 conflict blocks generation
def test_tier3_conflict_blocks_generation():
    srs = "Requirements with conflict."
    req = _req("REQ-EX-001", "The system shall lock after 3 attempts.", tier=TIER_3, consistency_status="conflict")
    artifact = _minimal_artifact([req])
    sidecar = generate_candidate_suggestions(artifact, srs)

    req_out = sidecar["requirements"][0]
    assert req_out["blocked"] is True
    assert req_out["blocked_reason"] == "tier3_conflict"
    assert len(req_out["ranked_candidates"]) == 0


# T-08: Human approval is never set automatically
def test_human_approval_never_set_automatically():
    srs = "The service shall respond within 2 seconds. The service may respond within 2 seconds."
    req = _req("REQ-EX-001", "The service may respond within 2 seconds.")
    artifact = _minimal_artifact([req])
    sidecar = generate_candidate_suggestions(artifact, srs)

    assert "human_decision" not in sidecar
    assert "bdd_ready" not in sidecar
    for r in sidecar["requirements"]:
        for c in r["ranked_candidates"]:
            assert c["validation"]["bdd_readiness"]["bdd_ready"] is False


# T-09: Ranking has explicit score breakdown
def test_ranking_has_explicit_score_breakdown():
    srs = "The service shall respond within 2 seconds. The service may respond within 2 seconds."
    req = _req(
        "REQ-EX-001",
        "The service may respond within 2 seconds.",
        defects=[{"type": "ambiguous", "detector": "rule", "explanation": "ambiguous"}],
    )
    artifact = _minimal_artifact([req])
    sidecar = generate_candidate_suggestions(artifact, srs)

    cands = sidecar["requirements"][0]["ranked_candidates"]
    assert len(cands) >= 1
    cand = cands[0]
    assert "rank" in cand
    assert "score" in cand
    assert "score_breakdown" in cand
    bd = cand["score_breakdown"]
    for key in (
        "defects_eliminated",
        "grounding_pass",
        "consistency_pass",
        "bdd_readiness_pass",
        "tier_improvement",
        "length_penalty",
        "downstream",
    ):
        assert key in bd


# T-10: Original requirement preserved in sidecar
def test_original_requirement_preserved_in_sidecar():
    srs = "The service may respond within 2 seconds."
    req = _req("REQ-EX-001", "The service may respond within 2 seconds.", tier=TIER_1, defects=[{"type": "ambiguous", "detector": "rule", "explanation": "ambiguous"}])
    artifact = _minimal_artifact([req])
    sidecar = generate_candidate_suggestions(artifact, srs)

    out_req = sidecar["requirements"][0]
    assert out_req["requirement_id"] == "REQ-EX-001"
    assert out_req["original_text"] == "The service may respond within 2 seconds."
    assert out_req["original_tier"] == TIER_1
    assert len(out_req["original_defects"]) == 1


# T-11: CLI generate-candidates writes sidecar
def test_cli_generate_candidates_writes_sidecar(tmp_path: Path, archive_test_source):
    srs_file = tmp_path / "test.srs"
    srs_file.write_text("The service shall respond within 2 seconds. The service may respond within 2 seconds.", encoding="utf-8")

    req = _req("REQ-EX-001", "The service may respond within 2 seconds.")
    artifact = _minimal_artifact([req])
    _validate_contract_artifact(artifact)

    input_file = tmp_path / "validated_requirements.json"
    input_file.write_text(json.dumps(artifact), encoding="utf-8")
    archive_test_source(input_file, srs_file)

    out_file = tmp_path / "candidate_suggestions.json"

    rc = main([
        "generate-candidates",
        "--in", str(input_file),
        "--srs", str(srs_file),
        "--out", str(out_file),
    ])
    assert rc == 0
    assert out_file.is_file()

    sidecar = json.loads(out_file.read_text(encoding="utf-8"))
    assert sidecar["contract"] == "c1.candidate-suggestions"
    assert sidecar["schema_version"] == "1.0.0"


# T-12: CLI generate-candidates includes blocked requirements
def test_cli_generate_candidates_blocked_requirement_in_output(tmp_path: Path, archive_test_source):
    srs_file = tmp_path / "test.srs"
    srs_file.write_text("The service shall timeout after [timeout].", encoding="utf-8")

    req = _req("REQ-EX-001", "The service shall timeout after [timeout].", tier=TIER_2)
    artifact = _minimal_artifact([req])
    _validate_contract_artifact(artifact)

    input_file = tmp_path / "validated_requirements.json"
    input_file.write_text(json.dumps(artifact), encoding="utf-8")
    archive_test_source(input_file, srs_file)
    out_file = tmp_path / "candidate_suggestions.json"

    rc = main([
        "generate-candidates",
        "--in", str(input_file),
        "--srs", str(srs_file),
        "--out", str(out_file),
    ])
    assert rc == 0
    sidecar = json.loads(out_file.read_text(encoding="utf-8"))
    assert sidecar["requirements"][0]["blocked"] is True
    assert sidecar["requirements"][0]["blocked_reason"] == "tier2_open_questions"


# T-13: CLI generate-candidates does not mutate input
def test_cli_generate_candidates_does_not_mutate_input(tmp_path: Path, archive_test_source):
    srs_file = tmp_path / "test.srs"
    srs_file.write_text("The service may respond within 2 seconds.", encoding="utf-8")

    req = _req("REQ-EX-001", "The service may respond within 2 seconds.")
    artifact = _minimal_artifact([req])
    _validate_contract_artifact(artifact)

    input_file = tmp_path / "validated_requirements.json"
    raw_before = json.dumps(artifact, indent=2) + "\n"
    input_file.write_text(raw_before, encoding="utf-8")
    archive_test_source(input_file, srs_file)
    out_file = tmp_path / "candidate_suggestions.json"

    rc = main([
        "generate-candidates",
        "--in", str(input_file),
        "--srs", str(srs_file),
        "--out", str(out_file),
    ])
    assert rc == 0
    raw_after = input_file.read_text(encoding="utf-8")
    assert raw_after == raw_before


# T-14: Generate then refine integration
def test_generate_then_refine_integration(tmp_path: Path):
    srs_text = "The service shall respond within 2 seconds. The service may respond within 2 seconds."
    srs_file = tmp_path / "test.srs"
    srs_file.write_text(srs_text, encoding="utf-8")

    req = _req("REQ-EX-001", "The service may respond within 2 seconds.", tier=TIER_1)
    artifact = _minimal_artifact([req])
    _validate_contract_artifact(artifact)

    # 1. Generate candidates
    sidecar = generate_candidate_suggestions(artifact, srs_text)
    ranked = sidecar["requirements"][0]["ranked_candidates"]
    assert len(ranked) >= 1
    selected_text = ranked[0]["text"]
    selected_id = ranked[0]["candidate_id"]

    # 2. Feed selected candidate into c1 refine actions
    actions = {
        "requirements": [{
            "requirement_id": "REQ-EX-001",
            "candidate_texts": [selected_text],
            "selected_candidate_text": selected_text,
            "human_decision": "approved",
        }]
    }

    refined, diagnostics = process_refinement_actions(artifact, actions, srs_text)
    _validate_contract_artifact(refined)
    assert refined["requirements"][0]["final_text"] == selected_text
    assert refined["requirements"][0]["human_decision"] == "approved"


# T-15: Insufficient evidence yields empty candidates with reason
def test_insufficient_evidence_yields_empty_candidates_with_reason():
    # Vague qualifier "quickly" but SRS has no measurable threshold
    srs = "The service shall respond quickly to requests."
    req = _req("REQ-EX-001", "The service shall respond quickly to requests.", defects=[{"type": "vague", "detector": "rule", "explanation": "vague"}])
    artifact = _minimal_artifact([req])
    sidecar = generate_candidate_suggestions(artifact, srs)

    req_out = sidecar["requirements"][0]
    assert len(req_out["ranked_candidates"]) == 0
    assert req_out["zero_candidates_reason"] is not None


# T-16: Mismatched clarification answer does not unblock
def test_mismatched_clarification_answer_does_not_unblock():
    srs = "The service shall wait [timeout]."
    req = _req("REQ-EX-001", "The service shall wait [timeout].", tier=TIER_2)
    artifact = _minimal_artifact([req])
    answers = [{"question": "What is the wrong question?", "answer": "2 seconds"}]
    sidecar = generate_candidate_suggestions(artifact, srs, clarification_answers=answers)

    assert sidecar["requirements"][0]["blocked"] is True
    assert sidecar["requirements"][0]["blocked_reason"] == "tier2_open_questions"


# T-17: Answer containing placeholder does not resolve question
def test_answer_containing_placeholder_does_not_resolve_question():
    srs = "The service shall wait [timeout]."
    req = _req("REQ-EX-001", "The service shall wait [timeout].", tier=TIER_2)
    artifact = _minimal_artifact([req])
    q = clarification_questions_for("The service shall wait [timeout].")[0]
    answers = [{"question": q, "answer": "within [TBD] seconds"}]
    sidecar = generate_candidate_suggestions(artifact, srs, clarification_answers=answers)

    assert sidecar["requirements"][0]["blocked"] is True
    assert sidecar["requirements"][0]["blocked_reason"] == "tier2_open_questions"


# T-18: Clarification answer provenance recorded as user-supplied
def test_clarification_answer_provenance_recorded_as_user_supplied():
    srs = "The service shall wait [timeout]."
    req = _req("REQ-EX-001", "The service shall wait [timeout].", tier=TIER_2)
    artifact = _minimal_artifact([req])
    q = clarification_questions_for("The service shall wait [timeout].")[0]
    answers = [{"question": q, "answer": "5 seconds"}]
    sidecar = generate_candidate_suggestions(artifact, srs, clarification_answers=answers)

    cands = sidecar["requirements"][0]["ranked_candidates"]
    assert len(cands) == 1
    cand = cands[0]
    assert cand["source_evidence"]["kind"] == "clarification_answer"
    assert cand["source_evidence"]["source"] == "user_supplied"
    assert cand["is_human_clarified"] is True
    assert cand["is_fabricated"] is False


# T-19: Potential conflict excluded from ranking, retained as diagnostic suggestion
def test_potential_conflict_excluded_from_ranking_retained_as_diagnostic():
    srs = "The response time shall be at least 2 seconds. The response time shall be at most 1 minutes."
    target = _req("REQ-EX-001", "The response time may be at least 2 seconds.", tier=TIER_1)
    peer = _req("REQ-EX-002", "The response time shall be at most 1 minutes.", tier=TIER_1)
    artifact = _minimal_artifact([target, peer])

    sidecar = generate_candidate_suggestions(artifact, srs)

    out_req = sidecar["requirements"][0]
    # Candidate for REQ-EX-001 ("The response time shall be at least 2 seconds.") has potential conflict with REQ-EX-002
    assert len(out_req["ranked_candidates"]) == 0
    assert len(out_req["diagnostic_suggestions"]) == 1
    diag = out_req["diagnostic_suggestions"][0]
    assert diag["diagnostic_reason"] == "potential_conflict"
    assert diag["consistency"]["status"] == "potential_conflict"
    assert diag["validation"]["bdd_readiness"]["bdd_ready"] is False


# T-20: Zero valid candidates reports reason
def test_zero_valid_candidates_reports_reason():
    srs = "The system shall perform correctly."
    req = _req("REQ-EX-001", "The system shall perform correctly.")
    artifact = _minimal_artifact([req])
    sidecar = generate_candidate_suggestions(artifact, srs)

    req_out = sidecar["requirements"][0]
    assert len(req_out["ranked_candidates"]) == 0
    assert req_out["zero_candidates_reason"] is not None


# T-21: Ranking tie broken deterministically
def test_ranking_tie_broken_deterministically():
    class TwoEqualCandidatesBackend:
        def generate(self, text, defects, evidence_chunks, clarification_answers, *, max_candidates=3):
            return [
                {
                    "text": "The service shall respond within 2 seconds.",
                    "strategy": "s1",
                    "source_evidence": {"kind": "srs_chunk", "chunk_id": "SRS-1", "text": "The service shall respond within 2 seconds.", "source": "lexical"},
                },
                {
                    "text": "The client shall authenticate within 2 seconds.",
                    "strategy": "s2",
                    "source_evidence": {"kind": "srs_chunk", "chunk_id": "SRS-2", "text": "The client shall authenticate within 2 seconds.", "source": "lexical"},
                },
            ]

    srs = "The service shall respond within 2 seconds. The client shall authenticate within 2 seconds."
    req = _req("REQ-EX-001", "The service may respond within 2 seconds.")
    artifact = _minimal_artifact([req])

    sidecar1 = generate_candidate_suggestions(artifact, srs, backend=TwoEqualCandidatesBackend())
    sidecar2 = generate_candidate_suggestions(artifact, srs, backend=TwoEqualCandidatesBackend())

    cands1 = sidecar1["requirements"][0]["ranked_candidates"]
    cands2 = sidecar2["requirements"][0]["ranked_candidates"]
    assert len(cands1) == 2
    if cands1[0]["score"] == cands1[1]["score"]:
        assert cands1[0]["rank"] == cands1[1]["rank"]
    assert [c["candidate_id"] for c in cands1] == [c["candidate_id"] for c in cands2]


# T-22: Lexical fallback recorded when RAG unavailable
def test_rag_candidate_validation_rejected_before_generation():
    srs = "The service shall respond within 2 seconds."
    req = _req("REQ-EX-001", "The service shall respond within 2 seconds.")
    artifact = _minimal_artifact([req])
    with pytest.raises(ValueError, match="only lexical"):
        generate_candidate_suggestions(artifact, srs, grounding_mode="rag")


# T-23: Human-confirmed substitution is NOT rejected due to SRS absence
def test_human_confirmed_substitution_not_rejected_due_to_srs_absence():
    srs = "The system shall timeout after [timeout]."
    req = _req("REQ-EX-001", "The system shall timeout after [timeout].", tier=TIER_2)
    artifact = _minimal_artifact([req])
    q = clarification_questions_for("The system shall timeout after [timeout].")[0]
    answers = [{"question": q, "answer": "99 milliseconds"}]

    sidecar = generate_candidate_suggestions(artifact, srs, clarification_answers=answers)

    req_out = sidecar["requirements"][0]
    assert req_out["blocked"] is False
    assert len(req_out["ranked_candidates"]) == 1
    cand = req_out["ranked_candidates"][0]
    assert cand["text"] == "The system shall timeout after 99 milliseconds."
    assert cand["is_human_clarified"] is True
    assert cand["is_fabricated"] is False
    assert cand["source_evidence"]["source"] == "user_supplied"
