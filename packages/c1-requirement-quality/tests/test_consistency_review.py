"""Audit-only pair review: synthetic inputs, no models or providers."""
import copy
import json
import socket

import pytest

from c1_requirement_quality import cli
from c1_requirement_quality.consistency_review import DECISIONS, make_review, pair_views, validate_record
from c1_requirement_quality.demo_workflow import DemoSession, guided_demo


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("Network forbidden"))


@pytest.fixture
def inputs():
    rows = [{"requirement_id": rid, "original_text": text, "final_text": text,
             "source": {"section": "Requirements"}} for rid, text in [
                 ("REQ-EX-002", "The system shall archive messages."),
                 ("REQ-EX-001", "The system shall send email.")]]
    return ({"requirements": rows}, {"document_id": "doc", "sha256": "source", "normalized_sha256": "nir"},
            {"requirements": {r["requirement_id"]: {"questions": {}, "answers": []} for r in rows}})


def kwargs(view, decision="consistent_within_scope"):
    return dict(decision=decision, evidence_refs=list(view["evidence"]), scope="Message processing",
                conditions="No additional conditions stated", rationale="Reviewed distinct obligations in the quoted source.",
                reviewer="test-reviewer", confirmed=True)


@pytest.mark.parametrize("decision", sorted(DECISIONS))
def test_all_decisions_and_immutable_findings(inputs, decision):
    artifact, manifest, state = inputs
    before = copy.deepcopy(inputs)
    view = pair_views(*inputs, [])[0]
    record = make_review(view, **kwargs(view, decision))
    validate_record(record)
    reviewed = pair_views(artifact, manifest, state, [record])[0]
    assert reviewed["decision"] == decision
    assert reviewed["requirement_ids"] == ["REQ-EX-001", "REQ-EX-002"]
    assert reviewed["current_deterministic"] == view["current_deterministic"]
    assert record["decision_effect"] == "none" and inputs == before
    assert pair_views(artifact, manifest, state, [])[0]["decision"] == "unresolved"
    reversed_artifact = {"requirements": list(reversed(artifact["requirements"]))}
    assert pair_views(reversed_artifact, manifest, state, [record])[0]["binding"] == record["binding"]


@pytest.mark.parametrize("field,value", [("evidence_refs", []), ("evidence_refs", ["unknown"]),
    ("rationale", ""), ("scope", ""), ("conditions", ""), ("reviewer", ""), ("confirmed", False)])
def test_missing_required_evidence_and_confirmation(inputs, field, value):
    view = pair_views(*inputs, [])[0]
    values = kwargs(view)
    values[field] = value
    with pytest.raises(ValueError): make_review(view, **values)


@pytest.mark.parametrize("decision", ["not_applicable", "consistent_within_scope"])
def test_conflict_cannot_be_dismissed(inputs, decision):
    artifact, _, _ = inputs
    artifact["requirements"][0]["original_text"] = artifact["requirements"][0]["final_text"] = "The system shall not send email."
    view = pair_views(*inputs, [])[0]
    assert view["current_deterministic"]["classification"] == "conflict"
    with pytest.raises(ValueError, match="cannot be dismissed"):
        make_review(view, **kwargs(view, decision))


@pytest.mark.parametrize("change", ["text", "source", "evidence", "clarification", "policy"])
def test_conservative_invalidation_and_supersession(inputs, change):
    view = pair_views(*inputs, [])[0]
    record = make_review(view, **kwargs(view))
    artifact, manifest, state = inputs
    policy = {}
    if change == "text": artifact["requirements"][0]["final_text"] += " Again."
    if change == "source": manifest["sha256"] = "changed"
    if change == "evidence": manifest["normalized_sha256"] = "changed"
    if change == "clarification": state["requirements"]["REQ-EX-001"]["answers"].append({"answer": "new"})
    if change == "policy": policy["policy"] = "next-policy"
    stale = pair_views(*inputs, [record], **policy)[0]
    assert stale["decision"] == "unresolved" and stale["invalidation"]
    assert stale["history"] == [record]
    if change != "policy":
        replacement = make_review(stale, **kwargs(stale, "unresolved"))
        assert replacement["supersedes"] == record["review_id"]
        assert replacement["prior_invalidation"]


def test_guided_record_pause_resume_and_unchanged_contract(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Requirements\n1. The system shall send email.\n2. The system shall archive messages.\n")
    cli.run(source, tmp_path / "run", "RUN-20261015-230000-cr01", registry_path=tmp_path / "registry.json")
    artifact = tmp_path / "run/c1/validated_requirements.json"
    session = DemoSession.create(tmp_path / "demo", artifact=artifact, source=source)
    session.apply({"requirement_id": "REQ-EX-001", "human_decision": "not_required"}, "test-reviewer", True)
    authoritative = session.current
    original_files = {p: p.read_bytes() for p in (tmp_path / "run").rglob("*") if p.is_file()}
    baseline = session.read()
    assert baseline[0]["requirements"][0]["human_decision"] == "not_required"
    view = session.consistency_pairs()[0]
    values = iter(["review-pair", "REQ-EX-002", "REQ-EX-001", "", "not_applicable",
        ",".join(view["evidence"]), "Message operations", "No shared exclusion specified",
        "Separate obligations in the cited source", "test-reviewer", "yes", "pairs", "pause"])
    messages = []
    guided_demo(tmp_path / "demo", resume=True, ask=lambda _: next(values), tell=messages.append)
    resumed = DemoSession(tmp_path / "demo")
    assert resumed.consistency_pairs()[0]["decision"] == "not_applicable"
    assert resumed.current == authoritative
    assert resumed.read() == baseline
    assert all(p.read_bytes() == content for p, content in original_files.items())
    cli._validate_contract_artifact(resumed.read()[0])
    assert any("Readiness, deterministic findings and approvals are unchanged" in m for m in messages)
    # An interrupted prompt never creates an event or replays a decision.
    before = len(resumed.events)
    def interrupt(_): raise KeyboardInterrupt
    guided_demo(tmp_path / "demo", resume=True, ask=interrupt, tell=messages.append)
    assert len(DemoSession(tmp_path / "demo").events) == before
    # Registering an unapproved candidate does not change authoritative text.
    resumed.apply({"requirement_id": "REQ-EX-001", "selected_candidate_text": "The system shall send encrypted email."}, "test-reviewer", True)
    assert DemoSession(tmp_path / "demo").consistency_pairs()[0]["invalidation"] is None
    resumed.apply({"requirement_id": "REQ-EX-001", "clarification_questions": ["Which messages are sent?"]}, "test-reviewer", True)
    stale = DemoSession(tmp_path / "demo").consistency_pairs()[0]
    assert stale["invalidation"] and stale["decision"] == "unresolved"
    assert len(stale["history"]) == 1
    assert stale["history"][0]["invalidations"]
    # Supersession is explicit and history remains available after another resume.
    resumed = DemoSession(tmp_path / "demo")
    resumed.record_consistency(["REQ-EX-002", "REQ-EX-001"], **kwargs(stale, "unresolved"))
    reviewed = DemoSession(tmp_path / "demo").consistency_pairs()[0]
    assert len(reviewed["history"]) == 2
    assert reviewed["history"][-1]["supersedes"] == reviewed["history"][0]["review_id"]
    assert reviewed["history"][-1]["prior_invalidation"]


def test_sticky_invalidation_does_not_reactivate_when_binding_returns(inputs):
    view = pair_views(*inputs, [])[0]
    record = make_review(view, **kwargs(view))
    record["invalidations"] = [{"snapshot_sha256": "historical-change"}]
    reverted = pair_views(*inputs, [record])[0]
    assert reverted["binding"] == record["binding"]
    assert reverted["decision"] == "unresolved" and reverted["invalidation"]


def test_one_endpoint_reference_is_insufficient(inputs):
    view = pair_views(*inputs, [])[0]
    values = kwargs(view)
    values["evidence_refs"] = [next(iter(view["evidence"]))]
    with pytest.raises(ValueError, match="both requirements"):
        make_review(view, **values)
