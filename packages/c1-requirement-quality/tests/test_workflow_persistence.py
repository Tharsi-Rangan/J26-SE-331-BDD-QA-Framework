"""Human workflow continuity and integrity across successive CLI snapshots."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from c1_requirement_quality import cli
from c1_requirement_quality.refinement import stable_candidate_id
from c1_requirement_quality.source_integrity import verify_source
from c1_requirement_quality.workflow_persistence import load_state, question_id

RUN = "RUN-20261013-150000-ab12"
PLACEHOLDER = "The system shall wait for [timeout]."
QUESTION = "What value or rule should replace [timeout]?"
CUSTOM = "Who confirms the timeout?"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def initial(tmp_path, text=PLACEHOLDER):
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n" + text + "\n" + f"1. {text}\n", encoding="utf-8")
    out = tmp_path / "initial"
    cli.run(source, out, RUN, registry_path=tmp_path / "isolated-registry.json", document_id="TEST-SRS")
    artifact = out / "c1/validated_requirements.json"
    return artifact, source, read(artifact)["requirements"][0]["requirement_id"]


def refine(tmp_path, artifact, source, actions, name):
    action_file = tmp_path / f"{name}-actions.json"
    action_file.write_text(json.dumps({"requirements": actions}), encoding="utf-8")
    out = tmp_path / name
    cli.refine_run(artifact, source, action_file, out)
    path = out / "c1/validated_requirements.json"
    state, _ = load_state(path, source)
    cli._validate_contract_artifact(read(path))
    return path, state


def test_initial_run_persists_automatic_questions_and_awaiting_state(tmp_path):
    artifact, source, rid = initial(tmp_path)
    state, manifest = load_state(artifact, source)
    q = state["requirements"][rid]["questions"][question_id(rid, QUESTION)]
    assert q["text"] == QUESTION and q["status"] == "OPEN"
    assert state["requirements"][rid]["workflow_status"] == "AWAITING_CLARIFICATION"
    assert manifest["workflow_sha256"]
    assert state["parent"] is None and state["round"] == 0
    assert all(e["actor_id"] == "system" for e in state["events"])


def test_three_rounds_preserve_custom_questions_answers_and_history(tmp_path):
    artifact, source, rid = initial(tmp_path)
    first, state1 = refine(tmp_path, artifact, source, [{"requirement_id": rid, "actor_id": "reviewer-A",
        "clarification_questions": [CUSTOM], "clarification_answers": [{"question": QUESTION, "answer": "2 seconds", "provenance": "review meeting"}],
        "workflow_action": "request_clarification"}], "round1")
    second, state2 = refine(tmp_path, first, source, [{"requirement_id": rid}], "round2")
    third, state3 = refine(tmp_path, second, source, [{"requirement_id": rid, "actor_id": "reviewer-B",
        "clarification_answers": [{"question_id": question_id(rid, QUESTION), "answer": "3 seconds"}, {"question": CUSTOM, "answer": "The requirement owner"}]}], "round3")
    records = state3["requirements"][rid]
    assert list(records["questions"]) == [question_id(rid, QUESTION), question_id(rid, CUSTOM)]
    assert [a["answer"] for a in records["answers"]] == ["2 seconds", "3 seconds", "The requirement owner"]
    assert records["unanswered_question_ids"] == []
    assert state2["events"][:len(state1["events"])] == state1["events"]
    assert state3["events"][:len(state2["events"])] == state2["events"]
    assert state3["round"] == 3 and state3["parent"]["snapshot_id"] == state2["snapshot_id"]
    assert read(third)["requirements"][0]["clarification_questions"] == [QUESTION, CUSTOM]
    assert records["answers"][0]["actor_id"] == "reviewer-A"
    assert records["answers"][0]["provenance"]["kind"] == "human_provided"
    assert records["answers"][0]["provenance"]["supplied"] == "review meeting"
    assert read(first)["requirements"][0]["bdd_ready"] is False
    assert read(third)["requirements"][0]["bdd_ready"] is False


def test_repeated_questions_are_deduplicated_and_historical_text_is_retained(tmp_path):
    artifact, source, rid = initial(tmp_path)
    first, _ = refine(tmp_path, artifact, source, [{"requirement_id": rid, "clarification_questions": [CUSTOM, CUSTOM]}], "one")
    second, state = refine(tmp_path, first, source, [{"requirement_id": rid, "clarification_questions": ["Who   confirms the timeout?", CUSTOM]}], "two")
    record = state["requirements"][rid]
    assert len(record["questions"]) == 2
    assert record["questions"][question_id(rid, CUSTOM)]["historical_texts"] == [CUSTOM, "Who   confirms the timeout?"]
    assert read(second)["requirements"][0]["clarification_questions"].count(CUSTOM) == 1


def test_answer_update_retains_actor_event_snapshot_and_human_timestamp(tmp_path):
    artifact, source, rid = initial(tmp_path)
    first, state1 = refine(tmp_path, artifact, source, [{"requirement_id": rid,
        "clarification_answers": [{"question": QUESTION, "answer": "2 seconds", "actor_id": "alice", "human_timestamp": "2026-10-13T09:00:00+05:30"}]}], "one")
    _, state2 = refine(tmp_path, first, source, [{"requirement_id": rid, "clarification_answers": [{"question": QUESTION, "answer": "4 seconds"}]}], "two")
    answers = state2["requirements"][rid]["answers"]
    assert answers[0] == state1["requirements"][rid]["answers"][0]
    assert answers[0]["human_timestamp"] == "2026-10-13T09:00:00+05:30"
    assert answers[1]["actor_id"] == "unknown" and "human_timestamp" not in answers[1]
    assert answers[0]["snapshot_id"] == state1["snapshot_id"]
    assert all(a["event_id"] in {e["event_id"] for e in state2["events"]} for a in answers)
    assert all(a["resolution_state"] == "ANSWERED" for a in answers)


def test_answer_does_not_become_original_srs_evidence_or_auto_approval(tmp_path):
    artifact, source, rid = initial(tmp_path)
    candidate = "The system shall wait for 2 seconds."
    path, state = refine(tmp_path, artifact, source, [{"requirement_id": rid, "clarification_answers": [{"question": QUESTION, "answer": "2 seconds"}],
        "selected_candidate_text": candidate}], "answered")
    row = read(path)["requirements"][0]
    assert row["human_decision"] == "pending" and row["final_text"] == PLACEHOLDER
    diagnostic = read(path.parent / "refinement_diagnostics.json")[0]
    assert diagnostic["candidates"][0]["grounding"]["status"] == "supported"
    assert diagnostic["candidates"][0]["grounding"]["original_srs_status"] == "unsupported"
    assert diagnostic["candidates"][0]["grounding"]["human_clarification_evidence"]
    assert state["requirements"][rid]["unanswered_question_ids"] == []
    assert "clarification_answers" not in row and row["bdd_ready"] is False


def test_answered_question_can_be_explicitly_closed_and_reopened(tmp_path):
    artifact, source, rid = initial(tmp_path); qid = question_id(rid, QUESTION)
    first, _ = refine(tmp_path, artifact, source, [{"requirement_id": rid, "clarification_answers": [{"question_id": qid, "answer": "2 seconds"}]}], "answered")
    second, state2 = refine(tmp_path, first, source, [{"requirement_id": rid, "question_actions": [{"question_id": qid, "status": "CLOSED", "reason": "Recorded by owner"}]}], "closed")
    assert state2["requirements"][rid]["questions"][qid]["status"] == "CLOSED"
    third, state3 = refine(tmp_path, second, source, [{"requirement_id": rid, "question_actions": [{"question_id": qid, "status": "REOPENED", "reason": "Need review"}]}], "reopened")
    record = state3["requirements"][rid]
    assert record["unanswered_question_ids"] == [qid]
    assert record["questions"][qid]["current_answer_id"] is None
    assert len(record["answers"]) == 1
    assert read(third)["requirements"][0]["human_decision"] == "pending"
    assert read(third.parent / "refinement_diagnostics.json")[0]["clarification_answers"] == []


def test_explicit_requirement_reopen_revokes_approval_and_preserves_events(tmp_path):
    artifact, source, rid = initial(tmp_path, "The system shall send email.")
    first, _ = refine(tmp_path, artifact, source, [{"requirement_id": rid, "human_decision": "not_required", "actor_id": "reviewer"}], "approved")
    assert read(first)["requirements"][0]["bdd_ready"] is True
    second, state = refine(tmp_path, first, source, [{"requirement_id": rid, "workflow_action": "reopen"}], "reopened")
    assert read(second)["requirements"][0]["human_decision"] == "pending"
    assert read(second)["requirements"][0]["bdd_ready"] is False
    assert {e["kind"] for e in state["events"]} >= {"human_decision", "reopen"}


def test_rejected_candidate_persists_and_requires_explicit_reconsideration(tmp_path):
    artifact, source, rid = initial(tmp_path)
    candidate = "The system shall wait for 2 seconds."; cid = stable_candidate_id(rid, candidate)
    first, state1 = refine(tmp_path, artifact, source, [{"requirement_id": rid, "selected_candidate_text": candidate, "human_decision": "rejected"}], "rejected")
    second, state2 = refine(tmp_path, first, source, [], "unchanged")
    assert state2["requirements"][rid]["candidates"][cid]["status"] == "REJECTED"
    assert read(second)["requirements"][0]["human_decision"] == "rejected"
    with pytest.raises(ValueError, match="reconsider"):
        refine(tmp_path, second, source, [{"requirement_id": rid, "selected_candidate_id": cid}], "bad-selection")
    with pytest.raises(ValueError, match="reconsider"):
        refine(tmp_path, second, source, [{"requirement_id": rid, "human_decision": "approved"}], "bad-approval")
    third, state3 = refine(tmp_path, second, source, [{"requirement_id": rid, "reconsider_candidate_ids": [cid], "selected_candidate_id": cid, "human_decision": "pending"}], "reconsidered")
    assert state3["requirements"][rid]["candidates"][cid]["status"] == "PROPOSED"
    assert read(third)["requirements"][0]["human_decision"] == "pending"
    assert state3["events"][:len(state1["events"])] == state1["events"]


def test_inherited_edited_and_not_required_decisions_survive_empty_rounds(tmp_path):
    artifact, source, rid = initial(tmp_path, "The system shall send email.")
    candidate = "The system  shall send email."
    first, _ = refine(tmp_path, artifact, source, [{"requirement_id": rid, "human_decision": "edited", "edited_text": candidate}], "edited")
    second, state = refine(tmp_path, first, source, [], "continued")
    assert read(second)["requirements"][0]["human_decision"] == "edited"
    assert read(second)["requirements"][0]["final_text"] == candidate
    third, _ = refine(tmp_path, second, source, [{"requirement_id": rid, "human_decision": "not_required"}], "original")
    fourth, _ = refine(tmp_path, third, source, [], "original-again")
    assert read(fourth)["requirements"][0]["human_decision"] == "not_required"


def test_selection_of_new_candidate_does_not_inherit_edited_approval(tmp_path):
    artifact, source, rid = initial(tmp_path, "The system shall send email.")
    first, _ = refine(tmp_path, artifact, source, [{"requirement_id": rid, "human_decision": "edited", "edited_text": "The system  shall send email."}], "edited")
    second, _ = refine(tmp_path, first, source, [{"requirement_id": rid, "selected_candidate_text": "The system shall record events."}], "selected")
    assert read(second)["requirements"][0]["human_decision"] == "pending"
    assert read(second)["requirements"][0]["final_text"] == "The system shall send email."


def test_tier3_escalation_remains_blocked_even_after_explicit_resolution(tmp_path):
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall allow deletion.\n2. The system shall not allow deletion.\n")
    out = tmp_path / "initial"
    cli.run(source, out, RUN, registry_path=tmp_path / "registry.json")
    artifact = out / "c1/validated_requirements.json"; rid = read(artifact)["requirements"][0]["requirement_id"]
    first, state1 = refine(tmp_path, artifact, source, [], "continued")
    assert state1["requirements"][rid]["workflow_status"] == "AWAITING_ESCALATION"
    with pytest.raises(ValueError, match="resolution"):
        refine(tmp_path, first, source, [{"requirement_id": rid, "human_decision": "not_required"}], "invalid")
    second, state2 = refine(tmp_path, first, source, [{"requirement_id": rid, "workflow_action": "resolve_escalation", "resolution": "Owner reviewed both statements", "human_decision": "not_required"}], "resolved-attempt")
    assert state2["requirements"][rid]["escalation_active"] is True
    assert read(second)["requirements"][0]["tier"] == "TIER_3_ESCALATE"
    assert read(second)["requirements"][0]["bdd_ready"] is False
    assert any(e["kind"] == "resolve_escalation" for e in state2["events"])


def test_manual_escalation_requires_resolution_and_checks_before_continuing(tmp_path):
    artifact, source, rid = initial(tmp_path, "The system shall send email.")
    first, state1 = refine(tmp_path, artifact, source, [{"requirement_id": rid, "workflow_action": "escalate", "reason": "Owner review"}], "escalated")
    assert state1["requirements"][rid]["workflow_status"] == "AWAITING_ESCALATION"
    with pytest.raises(ValueError, match="resolution"):
        refine(tmp_path, first, source, [{"requirement_id": rid, "human_decision": "not_required"}], "bad")
    second, state2 = refine(tmp_path, first, source, [{"requirement_id": rid, "workflow_action": "resolve_escalation", "resolution": "Owner confirms original obligation", "human_decision": "not_required"}], "resolved")
    assert state2["requirements"][rid]["workflow_status"] == "VALIDATED"
    assert read(second)["requirements"][0]["bdd_ready"] is True


def test_snapshot_lineage_is_relative_and_source_bundle_unchanged(tmp_path):
    artifact, source, rid = initial(tmp_path)
    first, state = refine(tmp_path, artifact, source, [], "one")
    assert (first.parent / state["parent"]["artifact_path"]).resolve() == artifact.resolve()
    assert not Path(state["parent"]["artifact_path"]).is_absolute()
    original = read(artifact.parent / "internal/source_manifest.json")
    manifest = read(first.parent / "internal/source_manifest.json")
    assert {k: manifest[k] for k in ("document_id", "sha256", "normalized_sha256")} == {k: original[k] for k in ("document_id", "sha256", "normalized_sha256")}
    assert (first.parent / "internal/source/srs.md").read_bytes() == source.read_bytes()


def rewrite_state(path, mutate):
    statefile = path.parent / "internal/workflow_snapshot.json"
    data = read(statefile); mutate(data)
    statefile.chmod(0o644); statefile.write_text(json.dumps(data), encoding="utf-8")
    manifestfile = path.parent / "internal/source_manifest.json"
    manifest = read(manifestfile); manifest["workflow_sha256"] = hashlib.sha256(statefile.read_bytes()).hexdigest()
    manifestfile.chmod(0o644); manifestfile.write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize("corruption", ["parent_id", "parent_path", "parent_hash", "source_identity", "round", "event_prefix"])
def test_inconsistent_lineage_rejected_even_with_resealed_current_hash(tmp_path, corruption):
    artifact, source, rid = initial(tmp_path)
    first, _ = refine(tmp_path, artifact, source, [], "one")
    def mutate(state):
        if corruption == "parent_id": state["parent"]["snapshot_id"] = "wrong"
        elif corruption == "parent_path": state["parent"]["artifact_path"] = "missing.json"
        elif corruption == "parent_hash": state["parent"]["artifact_sha256"] = "0" * 64
        elif corruption == "source_identity": state["source_identity"]["document_id"] = "wrong"
        elif corruption == "round": state["round"] = 5
        else: state["events"][0]["actor_id"] = "corrupted"
    rewrite_state(first, mutate)
    with pytest.raises(ValueError): load_state(first, source)


def test_unsealed_workflow_change_rejected_and_previous_snapshot_unchanged(tmp_path):
    artifact, source, rid = initial(tmp_path)
    before = artifact.read_bytes()
    first, _ = refine(tmp_path, artifact, source, [], "one")
    ledger = first.parent / "internal/workflow_snapshot.json"
    ledger.chmod(0o644); ledger.write_bytes(ledger.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash mismatch"): load_state(first, source)
    assert artifact.read_bytes() == before


@pytest.mark.parametrize("part", ["source", "normalized", "parent_source"])
def test_corrupted_source_bundle_blocks_continuation(tmp_path, part):
    artifact, source, rid = initial(tmp_path)
    first, _ = refine(tmp_path, artifact, source, [], "one")
    target = {"source": first.parent / "internal/source/srs.md", "normalized": first.parent / "internal/normalized_ingestion.json", "parent_source": artifact.parent / "internal/source/srs.md"}[part]
    target.chmod(0o644); target.write_bytes(target.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        refine(tmp_path, first, source, [], "blocked")
    assert not (tmp_path / "blocked").exists()


def test_previous_snapshot_cannot_be_overwritten(tmp_path):
    artifact, source, rid = initial(tmp_path)
    first, _ = refine(tmp_path, artifact, source, [], "one"); before = first.read_bytes()
    with pytest.raises(FileExistsError): refine(tmp_path, first, source, [], "one")
    assert first.read_bytes() == before


@pytest.mark.parametrize("action", [
    {"clarification_answers": [{"question_id": "wrong", "answer": "2 seconds"}]},
    {"clarification_answers": [{"question": QUESTION, "answer": ""}]},
    {"question_actions": [{"question_id": "wrong", "status": "REOPENED"}]},
    {"actor_id": ""}, {"human_timestamp": ""}, {"workflow_action": "unknown"},
])
def test_invalid_actions_never_publish_history(tmp_path, action):
    artifact, source, rid = initial(tmp_path)
    before = (artifact.parent / "internal/workflow_snapshot.json").read_bytes()
    with pytest.raises(ValueError): refine(tmp_path, artifact, source, [{"requirement_id": rid, **action}], "invalid")
    assert not (tmp_path / "invalid").exists()
    assert (artifact.parent / "internal/workflow_snapshot.json").read_bytes() == before


def test_generation_reuses_saved_answers_without_mutating_snapshot(tmp_path):
    artifact, source, rid = initial(tmp_path)
    first, _ = refine(tmp_path, artifact, source, [{"requirement_id": rid,
        "clarification_answers": [{"question": QUESTION, "answer": "2 seconds"}]}], "answered")
    before = (first.parent / "internal/workflow_snapshot.json").read_bytes()
    output = tmp_path / "candidates.json"
    assert cli.main(["generate-candidates", "--in", str(first), "--srs", str(source), "--out", str(output)]) == 0
    candidates = read(output)["requirements"][0]
    assert any(c["text"] == "The system shall wait for 2 seconds." for c in candidates["ranked_candidates"])
    assert (first.parent / "internal/workflow_snapshot.json").read_bytes() == before


def test_generation_does_not_reuse_answers_after_reopening(tmp_path):
    artifact, source, rid = initial(tmp_path)
    first, _ = refine(tmp_path, artifact, source, [{"requirement_id": rid,
        "clarification_answers": [{"question": QUESTION, "answer": "2 seconds"}]}], "answered")
    second, _ = refine(tmp_path, first, source, [{"requirement_id": rid, "workflow_action": "reopen"}], "reopened")
    output = tmp_path / "candidates.json"
    assert cli.main(["generate-candidates", "--in", str(second), "--srs", str(source), "--out", str(output)]) == 0
    assert read(output)["requirements"][0]["blocked"] is True


def test_generation_respects_existing_human_rejection_and_escalation(tmp_path):
    artifact, source, rid = initial(tmp_path)
    candidate = "The system shall wait for 2 seconds."
    first, _ = refine(tmp_path, artifact, source, [{"requirement_id": rid,
        "clarification_answers": [{"question": QUESTION, "answer": "2 seconds"}],
        "selected_candidate_text": candidate, "human_decision": "rejected"}], "rejected")
    output = tmp_path / "candidates.json"
    assert cli.main(["generate-candidates", "--in", str(first), "--srs", str(source), "--out", str(output)]) == 0
    row = read(output)["requirements"][0]
    assert row["ranked_candidates"] == []
    assert row["rejected_candidates"][0]["rejected_reason"] == "persisted_human_rejection"
    second, _ = refine(tmp_path, first, source, [{"requirement_id": rid, "workflow_action": "escalate"}], "escalated")
    output2 = tmp_path / "escalated-candidates.json"
    assert cli.main(["generate-candidates", "--in", str(second), "--srs", str(source), "--out", str(output2)]) == 0
    assert read(output2)["requirements"][0]["blocked_reason"] == "workflow_escalation"


def test_missing_parent_blocks_generation_and_refinement(tmp_path):
    artifact, source, rid = initial(tmp_path)
    first, _ = refine(tmp_path, artifact, source, [], "one")
    # Corrupt the reference without deleting or changing the parent artifact.
    rewrite_state(first, lambda s: s["parent"].update(artifact_path="missing-parent.json"))
    with pytest.raises(ValueError, match="missing"): load_state(first, source)
    output = tmp_path / "candidates.json"
    assert cli.main(["generate-candidates", "--in", str(first), "--srs", str(source), "--out", str(output)]) == 1
    assert not output.exists()


def test_questions_and_answers_are_requirement_scoped(tmp_path):
    source = tmp_path / "srs.md"
    source.write_text("# One\n1. The system shall wait for [timeout].\n# Two\n1. The client shall wait for [timeout].\n")
    out = tmp_path / "initial"; cli.run(source, out, RUN, registry_path=tmp_path / "registry.json")
    artifact = out / "c1/validated_requirements.json"
    rid1, rid2 = [r["requirement_id"] for r in read(artifact)["requirements"]]
    assert question_id(rid1, QUESTION) != question_id(rid2, QUESTION)
    with pytest.raises(ValueError, match="recorded question"):
        refine(tmp_path, artifact, source, [{"requirement_id": rid2,
            "clarification_answers": [{"question_id": question_id(rid1, QUESTION), "answer": "2 seconds"}]}], "wrong")
    first, state = refine(tmp_path, artifact, source, [{"requirement_id": rid1,
        "clarification_answers": [{"question": QUESTION, "answer": "2 seconds"}]}], "correct")
    assert state["requirements"][rid1]["unanswered_question_ids"] == []
    assert state["requirements"][rid2]["unanswered_question_ids"] == [question_id(rid2, QUESTION)]


def test_legacy_phase1b1_answers_are_adopted_prospectively_without_changing_parent(tmp_path):
    from c1_requirement_quality.source_integrity import snapshot_source, seal_source
    source = tmp_path / "srs.md"; source.write_text(f"1. {PLACEHOLDER}\n")
    # Build an isolated Phase 1B.1-style fixture, without a workflow ledger.
    # Use a fresh current artifact's contract data, archived separately as legacy.
    current, _, rid = initial(tmp_path, PLACEHOLDER)
    directory = tmp_path / "legacy/c1"; directory.mkdir(parents=True)
    path = directory / "validated_requirements.json"
    payload = read(current); payload["requirements"][0]["clarification_questions"] = [QUESTION, CUSTOM]
    path.write_text(json.dumps(payload), encoding="utf-8")
    _, manifest = snapshot_source(directory, source, "LEGACY-SRS")
    seal_source(directory, manifest)
    diag = directory / "refinement_diagnostics.json"
    diag.write_text(json.dumps([{"requirement_id": rid, "clarification_answers": [{"question": CUSTOM, "answer": "Owner"}]}]))
    before = {p: p.read_bytes() for p in (path, diag, directory / "internal/source_manifest.json")}
    first, state = refine(tmp_path, path, source, [], "adopted")
    assert state["requirements"][rid]["answers"][0]["answer"] == "Owner"
    assert state["requirements"][rid]["answers"][0]["provenance"]["source"] == "legacy_diagnostics_unsealed"
    assert state["parent"]["workflow_sha256"] is None
    assert all(p.read_bytes() == raw for p, raw in before.items())


def test_parent_question_history_cannot_be_dropped(tmp_path):
    artifact, source, rid = initial(tmp_path)
    first, _ = refine(tmp_path, artifact, source, [], "one")
    def drop(state):
        state["requirements"][rid]["questions"] = {}
        state["requirements"][rid]["unanswered_question_ids"] = []
    rewrite_state(first, drop)
    with pytest.raises(ValueError, match="question history|validation signature"): load_state(first, source)


def test_explicit_approve_reject_aliases_are_audited_without_fabricated_actor(tmp_path):
    artifact, source, rid = initial(tmp_path, "The system shall send email.")
    candidate = "The system  shall send email."
    first, _ = refine(tmp_path, artifact, source, [{"requirement_id": rid,
        "selected_candidate_text": candidate, "workflow_action": "approve", "actor_id": "owner"}], "approved")
    second, state = refine(tmp_path, first, source, [{"requirement_id": rid, "workflow_action": "reject"}], "rejected")
    assert read(second)["requirements"][0]["human_decision"] == "rejected"
    decisions = [e for e in state["events"] if e["kind"] == "human_decision"]
    assert [e["payload"]["human_decision"] for e in decisions] == ["approved", "rejected"]
    assert [e["actor_id"] for e in decisions] == ["owner", "unknown"]
    assert all(e["timestamp_basis"] == "system_recorded_at" for e in decisions)
    assert all("human_timestamp" not in e for e in decisions)


def test_closing_without_an_answer_does_not_invent_one_or_promote_readiness(tmp_path):
    artifact, source, rid = initial(tmp_path)
    first, state = refine(tmp_path, artifact, source, [{"requirement_id": rid,
        "question_actions": [{"question_id": question_id(rid, QUESTION), "status": "CLOSED", "reason": "Deferred explicitly"}]}], "closed")
    assert state["requirements"][rid]["answers"] == []
    assert state["requirements"][rid]["unanswered_question_ids"] == []
    assert read(first)["requirements"][0]["bdd_ready"] is False


def test_conflicting_approval_and_reopening_is_rejected(tmp_path):
    artifact, source, rid = initial(tmp_path)
    with pytest.raises(ValueError, match="Cannot approve"):
        refine(tmp_path, artifact, source, [{"requirement_id": rid,
            "workflow_action": "reopen", "human_decision": "not_required"}], "conflicting")


def test_reconsideration_alone_clears_rejection_without_approving(tmp_path):
    artifact, source, rid = initial(tmp_path)
    candidate = "The system shall wait for 2 seconds."; cid = stable_candidate_id(rid, candidate)
    first, _ = refine(tmp_path, artifact, source, [{"requirement_id": rid,
        "selected_candidate_text": candidate, "human_decision": "rejected"}], "rejected")
    second, state = refine(tmp_path, first, source, [{"requirement_id": rid,
        "reconsider_candidate_ids": [cid]}], "reconsidered")
    assert state["requirements"][rid]["candidates"][cid]["status"] == "PROPOSED"
    assert read(second)["requirements"][0]["human_decision"] == "pending"
    assert read(second)["requirements"][0]["bdd_ready"] is False


def test_request_clarification_without_placeholder_is_an_explicit_wait_state(tmp_path):
    artifact, source, rid = initial(tmp_path, "The system shall send email.")
    first, state = refine(tmp_path, artifact, source, [{"requirement_id": rid,
        "workflow_action": "request_clarification", "reason": "Ask owner to review scope"}], "requested")
    assert state["requirements"][rid]["workflow_status"] == "AWAITING_CLARIFICATION"
    assert read(first)["requirements"][0]["human_decision"] == "pending"
    second, state2 = refine(tmp_path, first, source, [], "continued")
    assert state2["requirements"][rid]["workflow_status"] == "AWAITING_CLARIFICATION"
    third, state3 = refine(tmp_path, second, source, [{"requirement_id": rid,
        "human_decision": "not_required", "actor_id": "owner"}], "reviewed")
    assert state3["requirements"][rid]["workflow_status"] == "VALIDATED"
    assert read(third)["requirements"][0]["bdd_ready"] is True
