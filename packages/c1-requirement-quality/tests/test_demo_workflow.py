"""Guided workflow tests use scripted human input and saved synthetic sidecars only."""
import hashlib
import json
import socket
from pathlib import Path
from unittest.mock import patch

import pytest

from c1_requirement_quality import cli
from c1_requirement_quality.demo_workflow import DemoSession, guided_demo
from c1_requirement_quality.rewrite_generator import generate_candidates_run
from c1_requirement_quality.workflow_persistence import question_id


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("No cloud allowed"))


@pytest.fixture
def baseline(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Requirements\n1. The system shall wait for [timeout].\n", encoding="utf-8")
    cli.run(source, tmp_path / "baseline", "RUN-20261015-230000-dm01", registry_path=tmp_path / "registry.json")
    return tmp_path / "baseline/c1/validated_requirements.json", source


def scripted(values):
    iterator = iter(values)
    def ask(prompt):
        try: return next(iterator)
        except StopIteration: raise AssertionError("Unexpected prompt: " + prompt)
    return ask


def proposal_file(session, path):
    data, _, manifest, _ = session.read()
    rid = data["requirements"][0]["requirement_id"]
    ref = f"SRS:{rid}:original"
    proposal = {"schema_version": 1, "requirement_id": rid,
        "source_evidence_refs": [ref], "advisory_refs": [],
        "clarification_questions": [{"question": "What value or rule should replace [timeout]?",
            "reason": "The source leaves the timeout unresolved.", "source_evidence_refs": [ref], "advisory_refs": []}],
        "proposed_rewrite": None, "unresolved_assumptions": [], "claimed_grounding_status": "insufficient"}
    path.write_text(json.dumps({"input_sha256": hashlib.sha256(session.current.read_bytes()).hexdigest(),
        "source_sha256": manifest["sha256"], "document_id": manifest["document_id"],
        "decision_effect": "none", "diagnostic_sha256": {}, "proposals": [{"proposal": proposal}]}))
    return path


def test_new_analysis_session_and_resume(tmp_path):
    source = tmp_path / "new.md"
    source.write_text("# Requirements\n1. The system shall send email.\n")
    workspace = tmp_path / "demo"
    messages = []
    guided_demo(workspace, source=source, run_id="RUN-20261015-230000-dm02", registry=tmp_path / "registry.json",
                ask=scripted(["issues", "pause"]), tell=messages.append)
    session = DemoSession(workspace)
    assert len(session.read()[0]["requirements"]) == 1
    assert "initial" in str(session.current)
    guided_demo(workspace, resume=True, ask=scripted(["issues", "pause"]), tell=messages.append)
    assert any("unknown is not consistent" in message for message in messages)
    with pytest.raises(FileExistsError):
        DemoSession.create(workspace, source=source, run_id="RUN-20261015-230000-dm02", registry=tmp_path / "registry.json")


@pytest.mark.parametrize("choice", ["accept", "reject", "pending"])
def test_question_review_is_explicit_and_resumable(tmp_path, baseline, choice):
    artifact, source = baseline
    workspace = tmp_path / "demo"
    session = DemoSession.create(workspace, artifact=artifact, source=source)
    original = artifact.read_bytes()
    sidecar = proposal_file(session, tmp_path / "questions.json")
    answers = ["proposals", str(sidecar), "1", choice]
    if choice == "accept": answers += ["reviewer-A", "yes"]
    answers += ["pause"]
    guided_demo(workspace, resume=True, ask=scripted(answers), tell=lambda _: None)
    resumed = DemoSession(workspace)
    assert artifact.read_bytes() == original
    assert (resumed.current != artifact.resolve()) == (choice == "accept")
    assert all(r["human_decision"] == "pending" for r in resumed.read()[0]["requirements"])
    if choice == "reject": assert resumed.events[-1]["accepted"] is False
    if choice == "pending": assert resumed.events == []


def test_human_answer_binding_selection_approval_and_invalidation(tmp_path, baseline):
    artifact, source = baseline
    workspace = tmp_path / "demo"
    session = DemoSession.create(workspace, artifact=artifact, source=source)
    rid = "REQ-EX-001"
    messages = []
    guided_demo(workspace, resume=True, ask=scripted([
        "answer", rid, "1", "2 seconds", "", "reviewer-A", "yes", "pause"]), tell=messages.append)
    session = DemoSession(workspace)
    assert session.read()[3]["requirements"][rid]["answers"][0]["answer"] == "2 seconds"
    assert any("does not guarantee grounding" in message for message in messages)
    sidecar = tmp_path / "candidates.json"
    generate_candidates_run(session.current, session.source, sidecar)
    candidates = session.candidates(sidecar)
    assert len(candidates) == 1
    guided_demo(workspace, resume=True, ask=scripted([
        "candidates", str(sidecar), "all", "register", "reviewer-A", "yes", "pause"]), tell=lambda _: None)
    session = DemoSession(workspace)
    row = session.read()[0]["requirements"][0]
    assert row["human_decision"] == "pending" and row["candidates"]
    cid = candidates[0][1]["candidate_id"]
    guided_demo(workspace, resume=True, ask=scripted([
        "select", rid, cid, "reviewer-A", "yes", "decision", rid, "approved", "reviewer-A", "yes", "pause"]), tell=lambda _: None)
    session = DemoSession(workspace)
    row = session.read()[0]["requirements"][0]
    assert row["selected_candidate_id"] == cid and row["human_decision"] == "approved"
    assert row["bdd_ready"] is True
    session.apply({"requirement_id": rid, "selected_candidate_text": "The system shall wait for 9 seconds."}, "reviewer-A", True)
    row = DemoSession(workspace).read()[0]["requirements"][0]
    assert row["human_decision"] == "pending" and row["bdd_ready"] is False
    cli._validate_contract_artifact(session.read()[0])


def test_missing_stale_diagnostics_and_unbound_candidates(tmp_path, baseline):
    artifact, source = baseline
    session = DemoSession.create(tmp_path / "demo", artifact=artifact, source=source)
    with pytest.raises(FileNotFoundError): session.diagnostics(tmp_path / "missing.json")
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps({"model": {"identifier": "distilbert-requirement-defects"}, "input_sha256": "stale"}))
    with pytest.raises(ValueError): session.diagnostics(stale)
    sidecar = proposal_file(session, tmp_path / "proposal.json")
    session.apply({"requirement_id": "REQ-EX-001", "clarification_questions": ["Who owns the timeout?"]}, "reviewer", True)
    with pytest.raises(ValueError, match="Stale"): session.proposals(sidecar)
    stale.write_text('{}')
    with pytest.raises(ValueError, match="unbound"): session.candidates(stale)


def test_interrupt_after_publication_requires_explicit_adoption_no_replay(tmp_path, baseline):
    artifact, source = baseline
    workspace = tmp_path / "demo"
    session = DemoSession.create(workspace, artifact=artifact, source=source)
    with patch.object(session, "recover", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            session.apply({"requirement_id": "REQ-EX-001", "clarification_questions": ["Who owns the timeout?"]}, "reviewer", True)
    resumed = DemoSession(workspace)
    assert resumed.pending is not None and resumed.current == artifact.resolve()
    child = Path(resumed.pending["out"]) / "c1/validated_requirements.json"
    original = child.read_bytes()
    with patch.object(cli, "refine_run", side_effect=AssertionError("No replay")):
        resumed.recover(True)
    assert resumed.current == child and child.read_bytes() == original
    assert DemoSession(workspace).current == child


def test_failed_operation_cancellation_preserves_actions_and_base(tmp_path, baseline):
    artifact, source = baseline
    workspace = tmp_path / "demo"
    session = DemoSession.create(workspace, artifact=artifact, source=source)
    with pytest.raises(ValueError):
        session.apply({"requirement_id": "REQ-EX-001", "human_decision": "approved"}, "reviewer", True)
    resumed = DemoSession(workspace)
    assert resumed.pending is not None
    actions = Path(resumed.pending["actions"])
    raw = actions.read_bytes()
    resumed.recover(False)
    assert resumed.current == artifact.resolve() and actions.read_bytes() == raw
    assert DemoSession(workspace).pending is None


def test_no_confirmation_no_action_and_safe_terminal_interrupt(tmp_path, baseline):
    artifact, source = baseline
    workspace = tmp_path / "demo"
    session = DemoSession.create(workspace, artifact=artifact, source=source)
    with pytest.raises(ValueError): session.apply({"requirement_id": "REQ-EX-001"}, "reviewer", False)
    def interrupt(_): raise KeyboardInterrupt
    guided_demo(workspace, resume=True, ask=interrupt, tell=lambda _: None)
    guided_demo(workspace, resume=True, ask=scripted(["pause"]), tell=lambda _: None)
    assert DemoSession(workspace).current == artifact.resolve()


def test_session_os_lock_refuses_concurrent_review_and_releases(tmp_path):
    from c1_requirement_quality.demo_workflow import _session_lock
    with _session_lock(tmp_path):
        with pytest.raises(RuntimeError, match="Another terminal"):
            with _session_lock(tmp_path):
                pass
    with _session_lock(tmp_path):
        pass


def test_candidate_sidecar_tampering_is_not_imported(tmp_path, baseline):
    artifact, source = baseline
    session = DemoSession.create(tmp_path / "demo", artifact=artifact, source=source)
    session.apply({"requirement_id": "REQ-EX-001", "clarification_answers": [{
        "question": "What value or rule should replace [timeout]?", "answer": "2 seconds"}]}, "reviewer", True)
    path = tmp_path / "candidates.json"
    generate_candidates_run(session.current, source, path)
    report = json.loads(path.read_text())
    candidate = report["requirements"][0]["ranked_candidates"][0]
    candidate["source_evidence"]["answer"] = "99 seconds"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="inactive or unknown"):
        session.candidates(path)


def test_cli_entry_point_and_resume_use_scripted_input(tmp_path, baseline, monkeypatch):
    artifact, source = baseline
    workspace = tmp_path / "demo"
    monkeypatch.setattr("builtins.input", scripted(["issues", "pause"]))
    assert cli.main(["demo", "--workspace", str(workspace), "--in", str(artifact)]) == 0
    monkeypatch.setattr("builtins.input", scripted(["pause"]))
    assert cli.main(["demo", "--resume", str(workspace)]) == 0
    assert cli.main(["demo", "--resume", str(workspace), "--srs", str(source)]) == 1


def test_journal_tampering_and_recovery_parent_hash_fail_closed(tmp_path, baseline):
    artifact, source = baseline
    workspace = tmp_path / "demo"
    session = DemoSession.create(workspace, artifact=artifact, source=source)
    with patch.object(session, "recover", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            session.apply({"requirement_id": "REQ-EX-001"}, "reviewer", True)
    resumed = DemoSession(workspace)
    actions = Path(resumed.pending["actions"])
    with actions.open("a") as stream: stream.write(" ")
    with pytest.raises(ValueError, match="changed"):
        resumed.recover(True)
    receipt = workspace / "events/000001.json"
    event = json.loads(receipt.read_text())
    event["parent_sha256"] = "wrong"
    receipt.write_text(json.dumps(event))
    with pytest.raises(ValueError, match="journal chain"):
        DemoSession(workspace)


def test_kinmail_guided_mock_demonstration_with_saved_diagnostics(tmp_path):
    base = Path(__file__).resolve().parents[1]
    portable = base / "local-inference/kinmail-portable-001"
    if not (portable / "run/c1/validated_requirements.json").is_file():
        pytest.skip("Local Kinmail portable bundle not available")
    original = {p: p.read_bytes() for p in portable.rglob("*") if p.is_file()}
    replica = tmp_path / "portable"
    for p, raw in original.items():
        out = replica / p.relative_to(portable)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("xb") as stream: stream.write(raw)
    artifact = replica / "run/c1/validated_requirements.json"
    session = DemoSession.create(tmp_path / "demo", artifact=artifact)
    report = {"input_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "source_sha256": session.read()[2]["sha256"], "document_id": session.read()[2]["document_id"],
        "decision_effect": "none", "diagnostic_sha256": {}, "proposals": []}
    for rid, question in [("REQ-EX-017", "Which observable criteria define easy navigation?"),
                          ("REQ-EX-020", "Which hosting security controls are required?")]:
        ref = f"SRS:{rid}:original"
        report["proposals"].append({"proposal": {"schema_version": 1, "requirement_id": rid,
            "source_evidence_refs": [ref], "advisory_refs": [],
            "clarification_questions": [{"question": question, "reason": "Acceptance criteria need human clarification.",
                "source_evidence_refs": [ref], "advisory_refs": []}],
            "proposed_rewrite": None, "unresolved_assumptions": [], "claimed_grounding_status": "insufficient"}})
    sidecar = tmp_path / "MOCKED-questions.json"
    sidecar.write_text(json.dumps(report))
    messages = []
    guided_demo(session.workspace, resume=True, ask=scripted([
        "issues", "diagnostics", str(base / "local-inference/kinmail-distilbert-diagnostics-001.json"),
        "diagnostics", str(base / "local-inference/kinmail-minilm-similarity-001.json"),
        "proposals", str(sidecar), "all", "accept", "accept", "mock-reviewer", "yes", "issues", "pause"
    ]), tell=messages.append)
    resumed = DemoSession(session.workspace)
    data, _, _, state = resumed.read()
    assert len(data["requirements"]) == 21
    assert all(r["human_decision"] == "pending" and r["bdd_ready"] is False and r["tier"] == "TIER_2_CLARIFY" for r in data["requirements"])
    assert all(state["requirements"][rid]["unanswered_question_ids"] for rid in ["REQ-EX-017", "REQ-EX-020"])
    assert any("210 pairs" in message for message in messages)
    assert all(p.read_bytes() == raw for p, raw in original.items())
