"""Session-retained candidate evidence exercises real binding and verifier logic."""
import concurrent.futures
import json
import os
import subprocess
import sys
import threading

import pytest

from test_candidate_validation import context
from test_grounding_policy import rag_run
from c1_requirement_quality.demo_workflow import DemoSession
from c1_requirement_quality.rag import candidate_validation as service
from c1_requirement_quality.source_integrity import VerifiedWorkflowContext, resolve_workflow_policy
from c1_requirement_quality.workflow_persistence import candidate_evidence_path, restore_candidate_receipts

TEXT = "The system shall retain logs."


@pytest.fixture
def saved(context, tmp_path):
    artifact, source, rid, _, control, factory = context
    session = DemoSession.create(tmp_path / "s", artifact=artifact, source=source)
    digest = session.validate_candidate_evidence(rid, TEXT, analyser_factory=factory)
    event = session.events[-1]
    reference = candidate_evidence_path(session.workspace, event["reference"])
    data = json.loads(reference.read_bytes())
    evidence = candidate_evidence_path(session.workspace, data["evidence"])
    return session, digest, reference, evidence, control, factory, rid


def test_registration_and_restart_without_inference(saved):
    session, digest, reference, evidence, control, factory, rid = saved
    parent = session.current.read_bytes()
    count = control["analyses"]
    restored = DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory)
    assert restored.receipts == {service.stable_candidate_id(rid, TEXT): (evidence, digest)}
    _, text, _, state = resolve_workflow_policy(restored)
    result = restored.assess(rid, TEXT, text, TEXT, state["requirements"][rid])
    assert result["eligible_for_acceptance"]
    assert control["analyses"] == count == 1
    assert session.current.read_bytes() == parent
    record = json.loads(reference.read_bytes())
    assert reference.read_bytes() == service._canonical(record) + b"\n"
    assert session.events[-1]["reference_sha256"] == service.sha256(reference.read_bytes())
    assert record["receipt_sha256"] == digest
    assert record["binding"]["verification_policy"] == service.verification_policy()
    assert all(instance.released for instance in control["instances"])


def test_reference_modified_before_journal_cannot_promote_contradiction(context, tmp_path, monkeypatch):
    from c1_requirement_quality import demo_workflow as demo
    artifact, source, rid, _, control, factory = context
    control["passages"] = ["The system shall not retain logs."]
    session = DemoSession.create(tmp_path / "s", artifact=artifact, source=source)
    publish = demo._write
    observed = {}
    def modify_published_reference(path, value):
        publish(path, value)
        if path.name != "reference.json":
            return
        reference = json.loads(path.read_bytes())
        evidence = session.workspace / reference["evidence"]
        record = json.loads(evidence.read_bytes())
        assert record["verdict"] == "CONTRADICTED"
        observed.update(path=path, trusted_bytes=value, original_receipt=reference["receipt_sha256"])
        # Simulate a filesystem writer after exclusive publication, without
        # touching the journal, the classifier, or its independently checked result.
        record["verdict"] = "SUPPORTED"
        record["grounding"] = {"status": "supported", "errors": [], "evidence": [],
            "diagnostics": [{"fact": {"text": TEXT}, "outcome": "SUPPORTED",
                "evidence_outcomes": [{"chunk_id": "forged", "outcome": "SUPPORTED"}]}]}
        evidence.write_bytes(service._canonical(record) + b"\n")
        reference["receipt_sha256"] = service.sha256(evidence.read_bytes())
        path.write_bytes(service._canonical(reference) + b"\n")
    monkeypatch.setattr(demo, "_write", modify_published_reference)
    with pytest.raises(ValueError, match="journal binding"):
        session.validate_candidate_evidence(rid, TEXT, analyser_factory=factory)
    assert isinstance(observed["trusted_bytes"], bytes)
    journal = json.loads(next((session.workspace / "events").glob("*.json")).read_bytes())
    assert journal["reference_sha256"] == service.sha256(observed["trusted_bytes"])
    assert journal["reference_sha256"] != service.sha256(observed["path"].read_bytes())
    assert json.loads(observed["trusted_bytes"])["receipt_sha256"] == observed["original_receipt"]
    # Neither restart nor a direct restoration can accept the promoted support.
    with pytest.raises(ValueError, match="journal binding"):
        DemoSession(session.workspace)
    with pytest.raises(ValueError, match="journal binding"):
        session.candidate_grounding_context(analyser_factory=factory)


def test_reopened_snapshot_with_same_artifact_allows_fresh_evidence(context, tmp_path):
    artifact, source, rid, _, control, factory = context
    session = DemoSession.create(tmp_path / "s", artifact=artifact, source=source)
    session.apply({"requirement_id": rid, "clarification_questions": ["Who confirms?"],
        "clarification_answers": [{"question": "Who confirms?", "answer": "Administrator"}]}, "Reviewer", True)
    session.validate_candidate_evidence(rid, TEXT, analyser_factory=factory)
    old_state = session.read()[3]
    old_artifact = session.current.read_bytes()
    old_reference = candidate_evidence_path(session.workspace, session.events[-1]["reference"])
    old_reference_bytes = old_reference.read_bytes()
    old_evidence = candidate_evidence_path(session.workspace, json.loads(old_reference_bytes)["evidence"])
    old_evidence_bytes = old_evidence.read_bytes()
    qid = next(qid for qid, q in old_state["requirements"][rid]["questions"].items() if q["text"] == "Who confirms?")
    session.apply({"requirement_id": rid, "question_actions": [{"question_id": qid, "status": "REOPENED"}]}, "Reviewer", True)
    new_state = session.read()[3]
    assert session.current.read_bytes() == old_artifact
    assert new_state["snapshot_id"] != old_state["snapshot_id"]
    assert new_state != old_state
    assert not session.candidate_grounding_context(analyser_factory=factory).receipts
    digest = session.validate_candidate_evidence(rid, TEXT, analyser_factory=factory)
    fresh_reference = candidate_evidence_path(session.workspace, session.events[-1]["reference"])
    assert fresh_reference != old_reference
    restored = DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory)
    cid = service.stable_candidate_id(rid, TEXT)
    assert len(restored.receipts) == 1
    assert restored.receipts[cid][0] != old_evidence
    assert restored.receipts[cid][1] == digest
    _, text, _, state = resolve_workflow_policy(restored)
    assessment = restored.assess(rid, TEXT, text, TEXT, state["requirements"][rid])
    assert assessment["eligible_for_acceptance"]
    assert assessment["validation_binding"]["snapshot_id"] == new_state["snapshot_id"]
    assert old_reference.read_bytes() == old_reference_bytes
    assert old_evidence.read_bytes() == old_evidence_bytes
    assert control["analyses"] == 2


def test_separate_process_restores_without_inference(saved):
    session, _, _, _, control, _, rid = saved
    script = """
import json, sys
sys.addaudithook(lambda event, args: (_ for _ in ()).throw(RuntimeError('Network forbidden'))
                if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'} else None)
from pathlib import Path
from c1_requirement_quality.demo_workflow import DemoSession
from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser
from c1_requirement_quality.source_integrity import resolve_workflow_policy
class OfflineFake(RAGGroundingAnalyser):
    def model_provenance(self):
        return json.loads(sys.argv[2])
    def analyse(self, text):
        raise AssertionError('Inference must not run on restoration')
session = DemoSession(Path(sys.argv[1]))
context = session.candidate_grounding_context(analyser_factory=OfflineFake)
_, text, _, state = resolve_workflow_policy(context)
rid = sys.argv[3]
assert context.assess(rid, sys.argv[4], text, sys.argv[4], state['requirements'][rid])['eligible_for_acceptance']
print('restored without inference')
"""
    result = subprocess.run([sys.executable, "-B", "-c", script, str(session.workspace),
        json.dumps(control["models"]), rid, TEXT], capture_output=True, text=True, timeout=30, check=True)
    assert result.stdout.strip() == "restored without inference"


@pytest.mark.parametrize("part", ["reference", "evidence", "journal"])
def test_missing_persistence_never_restores_support(saved, part):
    session, _, reference, evidence, _, factory, _ = saved
    if part == "reference":
        reference.unlink()
    elif part == "evidence":
        evidence.unlink()
    else:
        # Orphan registry files are never discovered and promoted to authority.
        next((session.workspace / "events").glob("*.json")).unlink()
        restored = DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory)
        assert not restored.receipts
        return
    with pytest.raises((OSError, ValueError)):
        DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory)


@pytest.mark.parametrize("part", ["reference", "evidence"])
def test_partial_or_edited_files_fail_closed(saved, part):
    session, _, reference, evidence, _, factory, _ = saved
    (reference if part == "reference" else evidence).write_bytes(b'{"partial":')
    with pytest.raises(ValueError):
        DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory)


def test_digest_substitution_cannot_be_adopted(saved):
    session, _, reference, _, _, factory, _ = saved
    record = json.loads(reference.read_bytes())
    record["receipt_sha256"] = "0" * 64
    reference.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="journal binding"):
        DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory)


@pytest.mark.parametrize("change", ["snapshot_id", "candidate_id", "binding", "evidence_path"])
def test_inconsistent_even_independently_anchored_reference_rejected(saved, change):
    session, _, reference, _, _, factory, _ = saved
    record = json.loads(reference.read_bytes())
    if change == "evidence_path":
        record["evidence"] = "candidate_evidence/../external.json"
    elif change == "binding":
        record["binding"]["workflow_basis_sha256"] = "0" * 64
    else:
        record[change] = "wrong-identity"
    reference.write_text(json.dumps(record), encoding="utf-8")
    # Deliberately reseal this synthetic test journal to exercise binding checks
    # beyond the independently retained reference hash, not a production API.
    from c1_requirement_quality.demo_workflow import _hash
    event_path = next((session.workspace / "events").glob("*.json"))
    event = json.loads(event_path.read_bytes())
    event.pop("sha256")
    event["reference_sha256"] = _hash(reference.read_bytes())
    event["sha256"] = _hash(json.dumps(event, sort_keys=True).encode())
    event_path.write_text(json.dumps(event), encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch|Unsafe"):
        DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory)


@pytest.mark.parametrize("change", ["missing", "snapshot_id", "workflow_basis_sha256"])
def test_journal_snapshot_identity_must_match_verified_replay(saved, change):
    from c1_requirement_quality.demo_workflow import _hash
    session, _, _, _, _, factory, _ = saved
    event_path = next((session.workspace / "events").glob("*.json"))
    event = json.loads(event_path.read_bytes())
    event.pop("sha256")
    if change == "missing":
        event.pop("snapshot_identity")
    else:
        event["snapshot_identity"][change] = "wrong-verified-basis"
    # A synthetically resealed journal still cannot make a different or missing
    # workflow identity match the actual immutable snapshot active at this event.
    event["sha256"] = _hash(json.dumps(event, sort_keys=True).encode())
    event_path.write_text(json.dumps(event), encoding="utf-8")
    with pytest.raises(ValueError, match="verified snapshot identity mismatch"):
        DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory)


def test_candidate_text_change_has_no_receipt(saved):
    session, _, _, _, _, factory, rid = saved
    restored = session.candidate_grounding_context(analyser_factory=factory)
    _, text, _, state = resolve_workflow_policy(restored)
    result = restored.assess(rid, "The system shall delete logs.", text, TEXT, state["requirements"][rid])
    assert not result["eligible_for_acceptance"]
    assert result["verdict"] == "ERROR"


def test_copied_cross_run_evidence_rejected_even_with_correct_digest(saved, context, tmp_path):
    from c1_requirement_quality import cli
    from c1_requirement_quality.demo_workflow import _hash
    session, _, reference, evidence, _, factory, rid = saved
    cli.run(context[1], tmp_path / "other", "RUN-20261019-120000-abcd",
            registry_path=tmp_path / "other-registry.json")
    other = tmp_path / "other/c1/validated_requirements.json"
    other_evidence = tmp_path / "other-evidence.json"
    digest = service.validate_candidate_run(other, context[1], rid, TEXT, other_evidence,
                                            analyser_factory=factory)
    evidence.write_bytes(other_evidence.read_bytes())
    record = json.loads(reference.read_bytes())
    record["receipt_sha256"] = digest
    reference.write_text(json.dumps(record), encoding="utf-8")
    event_path = next((session.workspace / "events").glob("*.json"))
    event = json.loads(event_path.read_bytes())
    event.pop("sha256")
    event["reference_sha256"] = _hash(reference.read_bytes())
    event["sha256"] = _hash(json.dumps(event, sort_keys=True).encode())
    event_path.write_text(json.dumps(event), encoding="utf-8")
    with pytest.raises(ValueError, match="binding mismatch"):
        DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory)


def test_wrong_context_and_omitted_provenance_rejected(saved, context, tmp_path):
    session, _, _, _, _, factory, _ = saved
    with pytest.raises(ValueError, match="Verified workflow context"):
        restore_candidate_receipts(session.workspace, None, analyser_factory=factory)
    other = DemoSession.create(tmp_path / "other", artifact=context[0], source=context[1])
    other.apply({"requirement_id": context[2], "clarification_questions": ["Who approves?"]}, "Reviewer", True)
    with pytest.raises(ValueError, match="workflow context mismatch"):
        restore_candidate_receipts(session.workspace,
            VerifiedWorkflowContext(other.current, other.source), analyser_factory=factory)


def test_source_change_fails_before_inference(saved):
    session, _, _, _, control, factory, _ = saved
    session.source.write_text("changed SRS", encoding="utf-8")
    count = control["analyses"]
    with pytest.raises(ValueError, match="SRS changed"):
        DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory)
    assert control["analyses"] == count


def test_clarification_and_child_basis_invalidate_parent_receipts(saved):
    session, _, _, _, control, factory, rid = saved
    session.apply({"requirement_id": rid, "clarification_questions": ["Who approves?"]}, "Reviewer", True)
    restored = DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory)
    assert not restored.receipts
    assert control["analyses"] == 1


@pytest.mark.parametrize("change", ["model", "policy"])
def test_changed_provenance_fails_closed(saved, monkeypatch, change):
    session, _, _, _, control, factory, _ = saved
    if change == "model":
        control["models"]["nli"]["asset_sha256"]["weights"] = "changed"
    else:
        original = service.verification_policy
        def changed():
            value = original()
            value["version"] += 1
            return value
        monkeypatch.setattr(service, "verification_policy", changed)
    with pytest.raises(ValueError, match="provenance|binding"):
        session.candidate_grounding_context(analyser_factory=factory)
    assert control["analyses"] == 1


@pytest.mark.parametrize("relative", ["../secret", "candidate_evidence/../../secret",
    "candidate_evidence/../secret", "candidate_evidence/C:/secret", "C:/secret",
    "candidate_evidence/a\\b", "candidate_evidence//secret"])
def test_path_traversal_rejected(tmp_path, relative):
    with pytest.raises(ValueError, match="Unsafe"):
        candidate_evidence_path(tmp_path, relative)


def test_symlink_escape_rejected(tmp_path):
    root = tmp_path / "s"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "candidate_evidence").symlink_to(outside, target_is_directory=True)
    except OSError:
        # Windows can disallow symlink creation; junctions exercise the same check.
        if os.name != "nt":
            raise
        import subprocess
        subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "candidate_evidence"), str(outside)],
                       check=True, capture_output=True)
    with pytest.raises(ValueError, match="symlink/reparse"):
        candidate_evidence_path(root, "candidate_evidence/reference.json")


@pytest.mark.skipif(os.name != "nt", reason="Windows extended path spelling")
def test_extended_windows_prefix_during_concurrent_creation(tmp_path, monkeypatch):
    from pathlib import Path
    target = tmp_path / "candidate_evidence" / "new"
    original = Path.resolve
    def extended(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        return Path("\\\\?\\" + str(result)) if self == target else result
    monkeypatch.setattr(Path, "resolve", extended)
    assert candidate_evidence_path(tmp_path, "candidate_evidence/new") == target


def test_repeated_registration_is_exclusive(saved):
    session, _, _, _, control, factory, rid = saved
    with pytest.raises(FileExistsError):
        session.validate_candidate_evidence(rid, TEXT, analyser_factory=factory)
    assert control["analyses"] == 1
    assert len(DemoSession(session.workspace).events) == 1


def test_concurrent_registration_cannot_overwrite(context, tmp_path):
    artifact, source, rid, _, control, factory = context
    session = DemoSession.create(tmp_path / "s", artifact=artifact, source=source)
    def register():
        try:
            DemoSession(session.workspace).validate_candidate_evidence(rid, TEXT, analyser_factory=factory)
            return "registered"
        except FileExistsError:
            return "exclusive conflict"
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: register(), range(2)))
    assert sorted(results) == ["exclusive conflict", "registered"]
    assert control["analyses"] == 1
    assert len(DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory).receipts) == 1


def test_distinct_candidates_contending_for_journal_fail_closed(context, tmp_path, monkeypatch):
    artifact, source, rid, _, control, factory = context
    session = DemoSession.create(tmp_path / "s", artifact=artifact, source=source)
    barrier = threading.Barrier(2)
    append = DemoSession._append
    def contended(self, kind, **values):
        barrier.wait(timeout=10)
        return append(self, kind, **values)
    monkeypatch.setattr(DemoSession, "_append", contended)
    def register(text):
        try:
            DemoSession(session.workspace).validate_candidate_evidence(rid, text, analyser_factory=factory)
            return "registered"
        except FileExistsError:
            return "exclusive conflict"
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register, [TEXT, TEXT.rstrip(".")]))
    assert sorted(results) == ["exclusive conflict", "registered"]
    assert control["analyses"] == 2
    assert len(DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory).receipts) == 1


def test_interrupted_registration_is_not_authoritative(context, tmp_path, monkeypatch):
    artifact, source, rid, _, _, factory = context
    session = DemoSession.create(tmp_path / "s", artifact=artifact, source=source)
    def interrupted(*args, **kwargs):
        raise RuntimeError("simulated interruption before journal publication")
    monkeypatch.setattr(DemoSession, "_append", interrupted)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        session.validate_candidate_evidence(rid, TEXT, analyser_factory=factory)
    assert list(session.workspace.rglob("reference.json"))
    assert not DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory).receipts
    with pytest.raises(FileExistsError):
        session.validate_candidate_evidence(rid, TEXT, analyser_factory=factory)


def test_rag_receipt_never_enables_approval(rag_run):
    policy, data, row, text, _, _, session, factory = rag_run
    from c1_requirement_quality.refinement import process_refinement_actions, _process_refinement_actions
    rid = row["requirement_id"]
    session.validate_candidate_evidence(rid, row["original_text"], analyser_factory=factory)
    restored = DemoSession(session.workspace).candidate_grounding_context(analyser_factory=factory)
    assert restored.receipts
    for process in (process_refinement_actions, _process_refinement_actions):
        with pytest.raises(ValueError, match="integration is pending"):
            process(data, {"requirements": []}, text, workflow_context=policy, grounding_context=restored)
    with pytest.raises(ValueError, match="integration is pending"):
        session.apply({"requirement_id": rid, "human_decision": "approved"}, "Reviewer", True)
    assert not list((session.workspace / "snapshots").glob("*"))


def test_policy_fingerprint_is_stable_and_explicit():
    assert service.verification_policy() == service.verification_policy()
    policy = service.verification_policy()
    assert policy["sha256"] == service.sha256(service._canonical(policy["configuration"]))
    assert policy["configuration"]["nli"]["confidence_threshold"] is None
