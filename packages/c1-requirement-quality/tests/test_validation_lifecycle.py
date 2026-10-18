"""Synthetic Phase 1B.3 validation transitions; not research evaluation data."""
from pathlib import Path
import json

import pytest

from c1_requirement_quality import cli
from c1_requirement_quality.workflow_persistence import load_state, question_id

RUN = "RUN-20261013-160000-ab12"
ORIGINAL = "The system shall respond within [timeout]."
QUESTION = "What value or rule should replace [timeout]?"
CANDIDATE = "The system shall respond within 2 seconds."


def read(path): return json.loads(path.read_text(encoding="utf-8"))


def start(tmp_path, original=ORIGINAL, supporting=""):
    source = tmp_path / "source.md"
    source.write_text(f"# Requirements\n{supporting}\n1. {original}\n", encoding="utf-8")
    out = tmp_path / "initial"
    cli.run(source, out, RUN, registry_path=tmp_path / "isolated.json")
    artifact = out / "c1/validated_requirements.json"
    return artifact, source, read(artifact)["requirements"][0]["requirement_id"]


def step(tmp_path, artifact, source, actions, label):
    action_file = tmp_path / f"{label}-actions.json"
    action_file.write_text(json.dumps({"requirements": actions}), encoding="utf-8")
    out = tmp_path / label
    cli.refine_run(artifact, source, action_file, out)
    path = out / "c1/validated_requirements.json"
    state, _ = load_state(path, source)
    cli._validate_contract_artifact(read(path))
    return path, read(path)["requirements"][0], state


def approved(tmp_path):
    artifact, source, rid = start(tmp_path)
    path, row, state = step(tmp_path, artifact, source, [{"requirement_id": rid,
        "clarification_answers": [{"question": QUESTION, "answer": "2 seconds"}],
        "selected_candidate_text": CANDIDATE, "human_decision": "approved"}], "approved")
    return path, source, rid, row, state


@pytest.mark.parametrize("answers,candidate,decision,ready", [
    ([], None, "pending", False),
    ([{"question": QUESTION, "answer": "2 seconds"}], None, "pending", False),
    ([{"question": QUESTION, "answer": "2 seconds"}], "The system shall respond within 9 seconds.", "approved", False),
    ([{"question": QUESTION, "answer": "2 seconds"}], CANDIDATE, "pending", False),
    ([{"question": QUESTION, "answer": "2 seconds"}], CANDIDATE, "approved", True),
])
def test_tier2_clarification_rewrite_approval_matrix(tmp_path, answers, candidate, decision, ready):
    artifact, source, rid = start(tmp_path)
    action = {"requirement_id": rid, "clarification_answers": answers, "human_decision": decision}
    if candidate is not None: action["selected_candidate_text"] = candidate
    path, row, state = step(tmp_path, artifact, source, [action], "refined")
    assert row["bdd_ready"] is ready
    assert state["requirements"][rid]["original_assessment"]["tier"] == "TIER_2_CLARIFY"
    if ready:
        assert row["tier"] == "TIER_1_AUTO_REFINE" and row["validation"]["status"] == "passed"
        assert row["final_text"] == CANDIDATE
        assert row["validation"]["checks"]["grounding"] == "pass"
        assert any(e["chunk_id"].startswith("HUMAN-") for e in row["grounding"]["evidence"])
    else: assert row["validation"]["status"] != "passed" or row["human_decision"] == "pending"


def test_answered_history_retained_without_blocking_ready_snapshot(tmp_path):
    path, source, rid, row, original_state = approved(tmp_path)
    assert row["clarification_questions"] == [QUESTION]
    assert row["bdd_ready"] is True
    next_path, next_row, next_state = step(tmp_path, path, source, [], "continued")
    assert next_row["bdd_ready"] is True
    record = next_state["requirements"][rid]
    assert record["current_validation"]["clarification_resolution"]["unresolved_questions"] == []
    assert record["current_validation"]["signature"] == original_state["requirements"][rid]["current_validation"]["signature"]
    assert next_state["events"][:len(original_state["events"])] == original_state["events"]


def test_reopening_invalidates_readiness_and_signature(tmp_path):
    path, source, rid, row, state = approved(tmp_path)
    old_signature = state["requirements"][rid]["current_validation"]["signature"]
    next_path, current, new_state = step(tmp_path, path, source, [{"requirement_id": rid,
        "question_actions": [{"question_id": question_id(rid, QUESTION), "status": "REOPENED"}]}], "reopened")
    assert current["bdd_ready"] is False and current["human_decision"] == "pending"
    assert new_state["requirements"][rid]["current_validation"]["signature"] != old_signature
    assert len(new_state["requirements"][rid]["answers"]) == 1


@pytest.mark.parametrize("closure", [None, "DEFERRED", "WAIVED", "ANSWERED"])
def test_closed_without_current_answer_is_not_successful_resolution(tmp_path, closure):
    artifact, source, rid = start(tmp_path, "The system shall send email.")
    custom = "What rule should this requirement enforce?"
    first, _, _ = step(tmp_path, artifact, source, [{"requirement_id": rid, "clarification_questions": [custom]}], "asked")
    operation = {"question_id": question_id(rid, custom), "status": "CLOSED"}
    if closure is not None: operation["closure_kind"] = closure
    path, row, state = step(tmp_path, first, source, [{"requirement_id": rid,
        "question_actions": [operation], "human_decision": "not_required"}], "closed")
    assert row["bdd_ready"] is False
    assert state["requirements"][rid]["current_validation"]["clarification_resolution"]["unresolved_questions"] == [custom]


def test_explicit_answered_closure_requires_valid_answer(tmp_path):
    path, source, rid, _, _ = approved(tmp_path)
    next_path, row, state = step(tmp_path, path, source, [{"requirement_id": rid,
        "question_actions": [{"question_id": question_id(rid, QUESTION), "status": "CLOSED", "closure_kind": "ANSWERED"}]}], "closed-answered")
    assert row["bdd_ready"] is True


def test_rejection_recomputes_original_defects_and_evidence(tmp_path):
    path, source, rid, ready, state = approved(tmp_path)
    before = path.read_bytes()
    rejected_path, row, rejected_state = step(tmp_path, path, source, [{"requirement_id": rid, "human_decision": "rejected"}], "rejected")
    assert row["bdd_ready"] is False and row["final_text"] == ORIGINAL
    assert row["validation"]["checks"]["quality"] == "fail"
    assert any(d["type"] == "incomplete" for d in row["defects"])
    assert not any(e["chunk_id"].startswith("HUMAN-") for e in row["grounding"]["evidence"])
    assert path.read_bytes() == before
    assert rejected_state["requirements"][rid]["original_assessment"] == state["requirements"][rid]["original_assessment"]


@pytest.mark.parametrize("field", ["selected_candidate_text", "edited_text"])
def test_candidate_replacement_does_not_inherit_approval(tmp_path, field):
    path, source, rid, row, state = approved(tmp_path)
    changed = "The system shall respond within 99 seconds."
    next_path, new_row, new_state = step(tmp_path, path, source, [{"requirement_id": rid, field: changed}], "replaced")
    assert new_row["bdd_ready"] is False and new_row["human_decision"] == "pending"
    assessments = new_state["requirements"][rid]["current_validation"]["candidate_assessments"]
    assert next(a for a in assessments if a["text"] == changed)["grounding_check"] == "fail"
    assert new_state["requirements"][rid]["current_validation"]["signature"] != state["requirements"][rid]["current_validation"]["signature"]


def test_answer_revision_revokes_inherited_approval_and_changes_grounding(tmp_path):
    path, source, rid, _, state = approved(tmp_path)
    next_path, row, revised_state = step(tmp_path, path, source, [{"requirement_id": rid,
        "clarification_answers": [{"question": QUESTION, "answer": "3 seconds"}]}], "answer-revised")
    assert row["bdd_ready"] is False and row["human_decision"] == "pending"
    record = revised_state["requirements"][rid]
    assert len(record["answers"]) == 2
    old = next(a for a in record["current_validation"]["candidate_assessments"] if a["text"] == CANDIDATE)
    assert old["grounding_check"] == "fail"
    new_text = "The system shall respond within 3 seconds."
    final_path, final_row, final_state = step(tmp_path, next_path, source, [{"requirement_id": rid,
        "selected_candidate_text": new_text, "human_decision": "approved"}], "approved-new-answer")
    assert final_row["bdd_ready"] is True
    assert final_state["requirements"][rid]["original_assessment"] == state["requirements"][rid]["original_assessment"]


@pytest.mark.parametrize("new_text", [
    "The administrator shall respond within 2 seconds.",
    "The system shall respond within 2 seconds when the account is paid.",
    "The system shall delete accounts within 2 seconds.",
    "The system shall respond within 4 seconds.",
    "The system must respond within 2 seconds.",
])
def test_extra_unprovided_facts_fail_grounding(tmp_path, new_text):
    artifact, source, rid = start(tmp_path)
    _, row, state = step(tmp_path, artifact, source, [{"requirement_id": rid,
        "clarification_answers": [{"question": QUESTION, "answer": "2 seconds"}],
        "selected_candidate_text": new_text, "human_decision": "approved"}], "unsupported")
    assert row["bdd_ready"] is False and row["grounding"]["status"] == "unsupported"


@pytest.mark.parametrize("answer", ["blue", "unknown", "TBD", "[another timeout]", "2 seconds and the system shall delete accounts"])
def test_invalid_or_irrelevant_answers_remain_validation_unresolved(tmp_path, answer):
    artifact, source, rid = start(tmp_path)
    _, row, state = step(tmp_path, artifact, source, [{"requirement_id": rid,
        "clarification_answers": [{"question": QUESTION, "answer": answer}],
        "selected_candidate_text": CANDIDATE, "human_decision": "approved"}], "invalid-answer")
    assert row["bdd_ready"] is False
    assert state["requirements"][rid]["current_validation"]["clarification_resolution"]["unresolved_questions"] == [QUESTION]


def test_semantic_source_supported_rewrite_can_pass_after_explicit_approval(tmp_path):
    original = "The system shall respond quickly."
    artifact, source, rid = start(tmp_path, original, CANDIDATE)
    _, row, state = step(tmp_path, artifact, source, [{"requirement_id": rid,
        "selected_candidate_text": CANDIDATE, "human_decision": "approved"}], "source-supported")
    assert row["bdd_ready"] is True and row["tier"] == "TIER_1_AUTO_REFINE"
    assert all(not e["chunk_id"].startswith("HUMAN-") for e in row["grounding"]["evidence"])
    assert state["requirements"][rid]["original_assessment"]["tier"] == "TIER_2_CLARIFY"


def test_explicit_human_span_binding_preserves_rest_of_obligation(tmp_path):
    original = "The system shall respond quickly."
    artifact, source, rid = start(tmp_path, original)
    custom = "What duration should replace quickly?"
    _, row, state = step(tmp_path, artifact, source, [{"requirement_id": rid, "clarification_questions": [custom],
        "clarification_answers": [{"question": custom, "answer": "within 2 seconds", "replaces_span": "quickly"}],
        "selected_candidate_text": CANDIDATE, "human_decision": "approved"}], "span-bound")
    assert row["bdd_ready"] is True
    assert state["requirements"][rid]["answers"][0]["replaces_span"] == "quickly"


def test_tier3_resolution_statement_does_not_clear_actual_contradiction(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Requirements\n1. The system shall allow deletion.\n2. The system shall not allow deletion.\n")
    out = tmp_path / "initial"; cli.run(source, out, RUN, registry_path=tmp_path / "registry.json")
    artifact = out / "c1/validated_requirements.json"; rid = read(artifact)["requirements"][0]["requirement_id"]
    path, row, state = step(tmp_path, artifact, source, [{"requirement_id": rid,
        "workflow_action": "resolve_escalation", "resolution": "Owner reviewed conflict", "human_decision": "not_required"}], "attempted-resolution")
    assert row["tier"] == "TIER_3_ESCALATE" and row["bdd_ready"] is False
    assert row["consistency"]["status"] == "conflict" and row["validation"]["checks"]["consistency"] == "fail"
    assert state["requirements"][rid]["escalation_active"] is True
    assert state["requirements"][rid]["original_assessment"]["tier"] == "TIER_3_ESCALATE"
    next_path, next_row, next_state = step(tmp_path, path, source, [], "still-escalated")
    assert next_row["bdd_ready"] is False


def test_actual_tier3_rewrites_rerun_entire_final_set_and_preserve_history(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Requirements\n1. The system shall allow deletion.\n2. The system shall not allow deletion.\n")
    out = tmp_path / "initial"; cli.run(source, out, RUN, registry_path=tmp_path / "registry.json")
    artifact = out / "c1/validated_requirements.json"
    new_text = "The system shall allow deletion when the administrator confirms ownership."
    question = "What rule should this requirement state after resolving the contradiction?"
    actions = [{"requirement_id": row["requirement_id"], "clarification_questions": [question],
        "clarification_answers": [{"question": question, "answer": new_text}],
        "selected_candidate_text": new_text, "human_decision": "approved",
        "workflow_action": "resolve_escalation", "resolution": "Owner supplies the explicit replacement conditional rule"}
        for row in read(artifact)["requirements"]]
    path, _, state = step(tmp_path, artifact, source, actions, "actual-resolution")
    assert all(row["bdd_ready"] is True and row["consistency"]["status"] == "consistent" for row in read(path)["requirements"])
    assert all(record["original_assessment"]["tier"] == "TIER_3_ESCALATE" for record in state["requirements"].values())
    assert len([e for e in state["events"] if e["kind"] == "resolve_escalation"]) == 2
    for record in state["requirements"].values():
        current = record["current_validation"]["candidate_assessments"][0]
        assert current["consistency"]["status"] == "consistent"
        assert current["comparison_basis"] == "current_final_peer_set"


def test_active_manual_escalation_blocks_current_clean_text(tmp_path):
    artifact, source, rid = start(tmp_path, "The system shall send email.")
    first, row, state = step(tmp_path, artifact, source, [{"requirement_id": rid, "human_decision": "not_required"}], "ready")
    second, current, state2 = step(tmp_path, first, source, [{"requirement_id": rid, "workflow_action": "escalate"}], "escalated")
    assert current["bdd_ready"] is False
    assert any(r["criterion"] == "active_escalation" for r in read(second.parent / "refinement_diagnostics.json")[0]["bdd_readiness"]["reasons"])


@pytest.mark.parametrize("field", ["original_assessment", "original_snapshot_id", "signature"])
def test_original_assessment_and_validation_signature_cannot_be_forged_in_child(tmp_path, field):
    import hashlib
    path, source, rid, _, _ = approved(tmp_path)
    ledger = path.parent / "internal/workflow_snapshot.json"
    state = read(ledger)
    if field == "original_assessment": state["requirements"][rid]["original_assessment"]["tier"] = "TIER_1_AUTO_REFINE"
    elif field == "original_snapshot_id": state["requirements"][rid]["original_snapshot_id"] = state["snapshot_id"]
    else: state["requirements"][rid]["current_validation"]["signature"] = "0" * 64
    ledger.chmod(0o644); ledger.write_text(json.dumps(state), encoding="utf-8")
    manifest_path = path.parent / "internal/source_manifest.json"
    manifest = read(manifest_path); manifest["workflow_sha256"] = hashlib.sha256(ledger.read_bytes()).hexdigest()
    manifest_path.chmod(0o644); manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError): load_state(path, source)


def test_peer_change_invalidates_other_requirements_current_validation(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Requirements\n1. The user age must be at least 18 years.\n2. The user age must be at most 65 years.\n")
    out = tmp_path / "initial"; cli.run(source, out, RUN, registry_path=tmp_path / "registry.json")
    artifact = out / "c1/validated_requirements.json"
    ids = [r["requirement_id"] for r in read(artifact)["requirements"]]
    first, _, before = step(tmp_path, artifact, source, [{"requirement_id": rid, "human_decision": "not_required"} for rid in ids], "ready-pair")
    second, _, after = step(tmp_path, first, source, [{"requirement_id": ids[1],
        "selected_candidate_text": "The user age must be at most 10 years.", "human_decision": "approved"}], "changed-peer")
    row = read(second)["requirements"][0]
    assert row["bdd_ready"] is False and row["consistency"]["status"] == "conflict"
    assert after["requirements"][ids[0]]["current_validation"]["signature"] != before["requirements"][ids[0]]["current_validation"]["signature"]


def test_generation_grounding_matches_refinement_and_keeps_human_source_label(tmp_path):
    artifact, source, rid = start(tmp_path)
    first, _, _ = step(tmp_path, artifact, source, [{"requirement_id": rid,
        "clarification_answers": [{"question": QUESTION, "answer": "2 seconds"}]}], "answered")
    generated = tmp_path / "suggestions.json"
    assert cli.main(["generate-candidates", "--in", str(first), "--srs", str(source), "--out", str(generated)]) == 0
    candidate = read(generated)["requirements"][0]["ranked_candidates"][0]
    assert candidate["grounding"]["status"] == "supported"
    assert candidate["grounding"]["original_srs_status"] == "unsupported"
    assert candidate["grounding"]["human_clarification_evidence"]
    assert candidate["tier"]["tier"] == "TIER_2_CLARIFY"
    second, row, _ = step(tmp_path, first, source, [{"requirement_id": rid,
        "selected_candidate_text": candidate["text"], "human_decision": "approved"}], "approved-suggestion")
    assert row["bdd_ready"] is True


@pytest.mark.parametrize("question,answer", [
    ("What rule should this requirement enforce?", "2 seconds"),
    ("Who confirms this requirement?", "The system shall delete accounts."),
])
def test_answer_to_different_fact_type_does_not_resolve_question(tmp_path, question, answer):
    artifact, source, rid = start(tmp_path, "The system shall send email.")
    _, row, state = step(tmp_path, artifact, source, [{"requirement_id": rid,
        "clarification_questions": [question], "clarification_answers": [{"question": question, "answer": answer}],
        "human_decision": "not_required"}], "irrelevant-fact-type")
    assert row["bdd_ready"] is False
    assert state["requirements"][rid]["current_validation"]["clarification_resolution"]["unresolved_questions"] == [question]
