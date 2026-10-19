"""Direct APIs must derive policy from real sealed provenance, never defaults."""
import json
import copy

import pytest

from test_candidate_validation import context
from test_clarification_proposals import proposal
from c1_requirement_quality import cli, wizard
from c1_requirement_quality.demo_workflow import DemoSession
from c1_requirement_quality.clarification_proposals import _context, validate_proposal
from c1_requirement_quality.refinement import _evaluate_candidate, process_refinement_actions
from c1_requirement_quality.refinement import _process_refinement_actions
from c1_requirement_quality.rewrite_generator import generate_candidate_suggestions
from c1_requirement_quality.source_integrity import VerifiedWorkflowContext, resolve_workflow_policy
from c1_requirement_quality.workflow_persistence import load_state
from c1_requirement_quality.rag.candidate_validation import (
    CandidateGroundingContext, validate_candidate_run, stable_candidate_id,
)


@pytest.fixture
def rag_run(context, tmp_path, monkeypatch):
    _, source, _, _, control, factory = context
    monkeypatch.setattr(cli, "RAGGroundingAnalyser", factory)
    cli.run(source, tmp_path / "rag", "RUN-20261019-120000-abcd",
            registry_path=tmp_path / "rag-registry.json", grounding_mode="rag", mandatory_rag=True)
    artifact = tmp_path / "rag/c1/validated_requirements.json"
    policy = VerifiedWorkflowContext(artifact, source)
    _, text, manifest, state = resolve_workflow_policy(policy)
    data = json.loads(artifact.read_bytes())
    row = data["requirements"][0]
    session = DemoSession.create(tmp_path / "session", artifact=artifact, source=source)
    return policy, data, row, text, manifest, state, session, factory


@pytest.mark.parametrize("false_flag", [False, True])
def test_no_receipt_or_flag_can_downgrade_actual_rag(rag_run, false_flag):
    policy, data, row, text, _, state, _, _ = rag_run
    rid = row["requirement_id"]
    for provenance in (None, policy):
        result = _evaluate_candidate(row["original_text"], text, row["original_text"],
            state["requirements"][rid], workflow_context=provenance, require_rag=false_flag)
        assert not result["candidate_eligible"]
        assert result["grounding"]["verdict"] == "ERROR"
        with pytest.raises(ValueError):
            process_refinement_actions(data, {"requirements": [{"requirement_id": rid,
                "selected_candidate_text": row["original_text"].rstrip("."), "human_decision": "approved"}]},
                text, workflow_context=provenance, require_rag=false_flag)
        with pytest.raises(ValueError):
            generate_candidate_suggestions(data, text, workflow_context=provenance)


def test_direct_clarification_cannot_default_to_lexical(rag_run):
    policy, data, row, text, _, state, _, _ = rag_run
    rid = row["requirement_id"]
    supplied = proposal(rid, rewrite=row["original_text"])
    ctx = _context(row, text, state, {}, 20000)
    with pytest.raises(ValueError, match="Verified workflow context"):
        validate_proposal(supplied, ctx, text, data["requirements"], state["requirements"][rid], None)
    result = validate_proposal(supplied, ctx, text, data["requirements"], state["requirements"][rid],
        None, workflow_context=policy, require_rag=False)
    assert result["proposed_rewrite"] is None
    assert result["validation"]["rewrite_status"] == "rejected"


def test_verified_receipt_keeps_eligibility_but_not_approval(rag_run, tmp_path):
    policy, data, row, text, _, state, session, factory = rag_run
    rid = row["requirement_id"]
    candidate = row["original_text"].rstrip(".")
    out = tmp_path / "evidence.json"
    receipt = validate_candidate_run(policy.input_path, policy.source, rid, candidate, out, analyser_factory=factory)
    evidence = CandidateGroundingContext(policy.input_path, policy.source,
        {stable_candidate_id(rid, candidate): (out, receipt)}, analyser_factory=factory)
    assessment = wizard.Wizard(tmp_path / "ui").candidate_assessment(session, rid,
        {"text": candidate}, grounding_context=evidence)
    assert assessment["evaluation"]["candidate_eligible"]
    assert not assessment["validation"]["bdd_readiness"]["bdd_ready"]
    assert not wizard.Wizard(tmp_path / "ui").candidate_assessment(session, rid,
        {"text": candidate})["evaluation"]["candidate_eligible"]
    with pytest.raises(ValueError, match="RAG refinement integration is pending"):
        session.apply({"requirement_id": rid, "human_decision": "approved"}, "Reviewer", True)
    with pytest.raises(ValueError):
        process_refinement_actions(data, {"requirements": []}, text, workflow_context=policy,
                                   grounding_context=evidence, require_rag=False)
    assert not list((session.workspace / "snapshots").glob("*"))


def test_unknown_and_tampered_provenance_fail_closed(rag_run, tmp_path):
    policy, data, row, text, _, _, _, _ = rag_run
    for untrusted in ("legacy", {}, VerifiedWorkflowContext(tmp_path / "missing.json", policy.source)):
        result = _evaluate_candidate(row["original_text"], text, workflow_context=untrusted)
        assert not result["candidate_eligible"]
    manifest = policy.input_path.parent / "internal/source_manifest.json"
    manifest.chmod(0o644)
    payload = json.loads(manifest.read_bytes())
    payload.pop("rag_policy")
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="without its mandatory manifest policy"):
        generate_candidate_suggestions(data, text, workflow_context=policy)


def test_verified_legacy_still_supports_explicit_actions(verified_legacy):
    from test_refinement import _artifact
    original = "The system shall allow login."
    data = _artifact(original)
    row = data["requirements"][0]
    row["tier"] = "TIER_1_AUTO_REFINE"
    rid = row["requirement_id"]
    policy = verified_legacy(data, original)
    rag, text, _, _ = resolve_workflow_policy(policy)
    assert not rag
    result = _evaluate_candidate(original.rstrip("."), text, original, workflow_context=policy)
    assert result["candidate_eligible"]
    refined, _ = process_refinement_actions(data, {"requirements": [{"requirement_id": rid,
        "selected_candidate_text": original.rstrip("."), "human_decision": "approved"}]},
        text, workflow_context=policy)
    assert refined["requirements"][0]["human_decision"] == "approved"
    assert refined["requirements"][0]["bdd_ready"]


def test_internal_sealed_rag_cannot_borrow_same_source_legacy_context(rag_run, context):
    policy, data, row, text, _, _, _, _ = rag_run
    legacy = VerifiedWorkflowContext(context[0], context[1])
    assert legacy.source == policy.source
    assert not resolve_workflow_policy(legacy)[0]
    actions = {"requirements": [{"requirement_id": row["requirement_id"],
        "selected_candidate_text": row["original_text"].rstrip("."), "human_decision": "approved"}]}
    for process in (_process_refinement_actions, process_refinement_actions):
        with pytest.raises(ValueError, match="parent artifact mismatch"):
            process(data, actions, text, workflow_context=legacy)
    with pytest.raises(ValueError, match="RAG refinement integration is pending"):
        _process_refinement_actions(data, actions, text, workflow_context=policy)


@pytest.mark.parametrize("change", ["wrong_run", "tampered", "omitted"])
def test_internal_artifact_binding_rejects_unverified_inputs(verified_legacy, change):
    from test_refinement import _artifact
    text = "The system shall allow login."
    data = _artifact(text)
    policy = verified_legacy(data, text)
    supplied = copy.deepcopy(data)
    if change == "wrong_run":
        supplied["run_id"] = "RUN-20261019-120000-abcd"
    elif change == "tampered":
        supplied["requirements"][0]["original_text"] = "The system shall delete accounts."
    else:
        policy = None
    with pytest.raises(ValueError, match="parent artifact mismatch|Verified workflow context"):
        _process_refinement_actions(supplied, {"requirements": []}, text, workflow_context=policy)


def test_internal_rounds_accept_only_unchanged_issued_results(verified_legacy):
    from test_refinement import _artifact
    text = "The system shall allow login."
    data = _artifact(text)
    data["requirements"][0]["tier"] = "TIER_1_AUTO_REFINE"
    rid = data["requirements"][0]["requirement_id"]
    policy = verified_legacy(data, text)
    actions = {"requirements": [{"requirement_id": rid,
        "selected_candidate_text": text.rstrip("."), "human_decision": "approved"}]}
    first, _ = _process_refinement_actions(data, actions, text, workflow_context=policy)
    assert first["requirements"][0]["human_decision"] == "approved"
    second, _ = _process_refinement_actions(first, {"requirements": []}, text, workflow_context=policy)
    assert second["requirements"][0]["bdd_ready"]
    # Another verified run with identical source and original content is not its parent.
    other = verified_legacy(data, text)
    with pytest.raises(ValueError, match="parent artifact mismatch"):
        _process_refinement_actions(first, {"requirements": []}, text, workflow_context=other)
    # JSON copies, manually constructed subclasses and mutated outputs carry no valid receipt.
    for unissued in (dict(first), type(first)(first)):
        with pytest.raises(ValueError, match="parent artifact mismatch"):
            _process_refinement_actions(unissued, {"requirements": []}, text, workflow_context=policy)
    second["requirements"][0]["original_text"] = "The system shall delete accounts."
    with pytest.raises(ValueError, match="parent artifact mismatch"):
        _process_refinement_actions(second, {"requirements": []}, text, workflow_context=policy)


@pytest.mark.parametrize("change", ["reopen", "supersede", "edit"])
def test_persisted_clarification_changes_invalidate_receipts(context, tmp_path, change):
    artifact, source, rid, _, _, factory = context
    data = json.loads(artifact.read_bytes())
    row = data["requirements"][0]
    question = "Who confirms the rule?"
    def refine(parent, actions, name):
        action_file = tmp_path / (name + ".json")
        action_file.write_text(json.dumps({"requirements": actions}), encoding="utf-8")
        cli.refine_run(parent, source, action_file, tmp_path / name)
        return tmp_path / name / "c1/validated_requirements.json"
    first = refine(artifact, [{"requirement_id": rid, "clarification_questions": [question],
        "clarification_answers": [{"question": question, "answer": "Administrator"}]}], "answered")
    candidate = row["original_text"].rstrip(".")
    path = tmp_path / "candidate.json"
    digest = validate_candidate_run(first, source, rid, candidate, path, analyser_factory=factory)
    state, _ = load_state(first, source)
    if change == "reopen":
        qid = next(qid for qid, q in state["requirements"][rid]["questions"].items() if q["text"] == question)
        action = {"question_actions": [{"question_id": qid, "status": "REOPENED"}]}
    else:
        action = {"clarification_answers": [{"question": question,
                  "answer": "Supervisor" if change == "edit" else "Administrator"}]}
    second = refine(first, [{"requirement_id": rid, **action}], "changed")
    evidence = CandidateGroundingContext(second, source,
        {stable_candidate_id(rid, candidate): (path, digest)}, analyser_factory=factory)
    policy = VerifiedWorkflowContext(second, source)
    _, text, _, state = resolve_workflow_policy(policy)
    result = _evaluate_candidate(candidate, text, row["original_text"], state["requirements"][rid],
        workflow_context=policy, grounding_context=evidence, requirement_id=rid)
    assert not result["candidate_eligible"]
    assert result["grounding"]["verdict"] == "ERROR"
