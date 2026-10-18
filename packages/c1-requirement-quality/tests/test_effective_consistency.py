"""Reviewed consistency tests: synthetic human records, no model/provider calls."""
import copy
import json
import socket

import pytest

from c1_requirement_quality import cli
from c1_requirement_quality.consistency_review import make_review
from c1_requirement_quality.demo_workflow import DemoSession
from c1_requirement_quality.effective_consistency import assess, views, create_review, context_from_state, NOTICE
from c1_requirement_quality.refinement import _consistency_with_candidate
from c1_requirement_quality.workflow_persistence import load_state


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("Network prohibited"))


@pytest.fixture
def case():
    rows = [{"requirement_id": f"REQ-EX-{i:03}", "original_text": text, "final_text": text,
             "source": {"section": "Requirements"}} for i, text in enumerate([
                 "The system shall send email.", "The system shall archive messages."], 1)]
    records = {r["requirement_id"]: {"questions": {}, "answers": []} for r in rows}
    context = {"source_identity": {"document_id": "synthetic", "sha256": "source", "normalized_sha256": "nir"}, "history": []}
    return rows, records, context


def request(pair, decision="not_applicable", coverage="complete"):
    return {"decision": decision, "coverage": coverage, "evidence_refs": list(pair["evidence"]),
        "scope": "Complete pair obligation", "conditions": "No shared restricting conditions in these synthetic texts",
        "rationale": "Test reviewer examined both source obligations", "reviewer": "synthetic-test-reviewer", "confirmed": True}


@pytest.mark.parametrize("decision,coverage,status,check", [
    ("not_applicable", "complete", "consistent", "pass"),
    ("consistent_within_scope", "complete", "consistent", "pass"),
    ("not_applicable", "partial", "potential_conflict", "skipped"),
    ("consistent_within_scope", "partial", "potential_conflict", "skipped"),
    ("unresolved", "complete", "potential_conflict", "skipped"),
    ("conflict_confirmed", "complete", "conflict", "fail")])
def test_review_outcomes_preserve_raw_findings(case, decision, coverage, status, check):
    rows, records, context = case
    raw = assess(rows[0]["requirement_id"], *case)
    pair = views(*case)[0]
    context["history"].append(create_review(pair, request(pair, decision, coverage)))
    result = assess(rows[0]["requirement_id"], *case)
    assert (result["status"], result["check"]) == (status, check)
    assert result["pairs"] == raw["pairs"]
    assert result["pairs"][0]["classification"] == "unassessed"
    if decision == "not_applicable" and coverage == "complete":
        assert result["effective_review"]["explanation"] == NOTICE


def test_batch_reuses_views_and_rebuilds_after_review_and_text_changes(case, monkeypatch):
    from unittest.mock import Mock
    from c1_requirement_quality import effective_consistency as module
    rows, records, context = case
    expected = {r["requirement_id"]: assess(r["requirement_id"], *case) for r in rows}
    assert module.assess_all(*case) == expected
    pair = views(*case)[0]
    context["history"].append(create_review(pair, request(pair)))
    expected = {r["requirement_id"]: assess(r["requirement_id"], *case) for r in rows}
    spy = Mock(wraps=module.views)
    monkeypatch.setattr(module, "views", spy)
    assert module.assess_all(*case) == expected
    assert spy.call_count == 1
    assert all(r["check"] == "pass" for r in expected.values())
    rows[0]["final_text"] += " Again."
    assert all(r["check"] == "skipped" for r in module.assess_all(*case).values())
    assert spy.call_count == 2


def test_deterministic_consistent_needs_no_review(case):
    rows, _, _ = case
    rows[1]["original_text"] = rows[1]["final_text"] = rows[0]["original_text"]
    result = assess(rows[0]["requirement_id"], *case)
    assert result["status"] == "consistent" and result["check"] == "pass"


def test_stale_and_legacy_do_not_clear(case):
    rows, records, context = case
    pair = views(*case)[0]
    legacy = make_review(pair, **{k: v for k, v in request(pair).items() if k != "coverage"})
    # Merely copying an audit record into a context must not grant gate effect.
    context["history"] = [legacy]
    assert assess(rows[0]["requirement_id"], *case)["check"] == "skipped"
    context["history"] = [create_review(views(rows, records, {**context, "history": []})[0], request(pair))]
    rows[0]["final_text"] += " Again."
    assert assess(rows[0]["requirement_id"], *case)["check"] == "skipped"


def test_conflicts_are_sticky_and_cannot_be_dismissed(case):
    rows, records, context = case
    pair = views(*case)[0]
    context["history"].append(create_review(pair, request(pair, "conflict_confirmed")))
    pair = views(*case)[0]
    context["history"].append(create_review(pair, request(pair, "not_applicable")))
    rows[0]["final_text"] += " Again."
    assert assess(rows[0]["requirement_id"], *case)["check"] == "fail"
    rows[1]["original_text"] = rows[1]["final_text"] = "The system shall not send email."
    rows[0]["final_text"] = rows[0]["original_text"]
    pair = views(*case)[0]
    with pytest.raises(ValueError, match="cannot be dismissed"):
        create_review(pair, request(pair))


def test_candidate_text_does_not_inherit_review(case):
    rows, records, context = case
    pair = views(*case)[0]
    context["history"].append(create_review(pair, request(pair)))
    assert _consistency_with_candidate(rows[0]["requirement_id"], rows[0]["final_text"], rows, records, context)["check"] == "pass"
    assert _consistency_with_candidate(rows[0]["requirement_id"], "The system shall send encrypted email.", rows, records, context)["check"] == "skipped"


def test_partial_review_for_21_requirements_does_not_clear_document(case):
    rows, records, context = case
    for i in range(3, 22):
        text = f"The system shall display synthetic item {i}."
        rid = f"REQ-EX-{i:03}"
        rows.append({"requirement_id": rid, "original_text": text, "final_text": text, "source": {"section": "Synthetic"}})
        records[rid] = {"questions": {}, "answers": []}
    pairs = views(*case)
    assert len(pairs) == 210
    context["history"].append(create_review(pairs[0], request(pairs[0])))
    assert "review_basis" not in assess("REQ-EX-021", *case)
    result = assess(rows[0]["requirement_id"], *case)
    assert result["status"] == "potential_conflict" and result["effective_review"]["unresolved_count"] >= 19


@pytest.fixture
def session(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Requirements\n1. The system shall send email.\n2. The system shall archive messages.\n")
    cli.run(source, tmp_path / "run", "RUN-20261015-230000-ec01", registry_path=tmp_path / "registry.json")
    return DemoSession.create(tmp_path / "demo", artifact=tmp_path / "run/c1/validated_requirements.json", source=source)


def test_adoption_reaffirmation_standalone_and_approval_invalidation(session, tmp_path):
    before = session.current.read_bytes()
    pair = session.consistency_pairs()[0]
    session.record_consistency(pair["requirement_ids"], **{k: v for k, v in request(pair).items() if k != "coverage"})
    assert session.current.read_bytes() == before
    session.apply({"requirement_id": "REQ-EX-001", "human_decision": "not_required"}, "synthetic-test-reviewer", True)
    pair = session.consistency_pairs(gate_policy=True)[0]
    session.adopt_consistency(pair["requirement_ids"], **request(pair))
    data, _, _, state = session.read()
    assert all(r["consistency"]["status"] == "consistent" for r in data["requirements"])
    assert all(r["human_decision"] == "pending" and not r["bdd_ready"] for r in data["requirements"])
    assert any(e["kind"] == "approval_invalidated" for e in state["events"])
    assert any(e["kind"] == "consistency_review_adopted" for e in state["events"])
    cli._validate_contract_artifact(data)
    # Standalone refinement inherits the very same verified review events.
    actions = tmp_path / "empty.json"
    actions.write_text(json.dumps({"requirements": []}))
    cli.refine_run(session.current, session.source, actions, tmp_path / "standalone")
    standalone = json.loads((tmp_path / "standalone/c1/validated_requirements.json").read_text())
    assert standalone == data
    load_state(tmp_path / "standalone/c1/validated_requirements.json", session.source)
    # Fresh human approval remains a separate operation.
    session.apply({"requirement_id": "REQ-EX-001", "human_decision": "not_required"}, "synthetic-test-reviewer", True)
    assert session.read()[0]["requirements"][0]["bdd_ready"] is True
    pair = session.consistency_pairs(gate_policy=True)[0]
    session.adopt_consistency(pair["requirement_ids"], **request(pair, "unresolved"))
    row = session.read()[0]["requirements"][0]
    assert row["human_decision"] == "pending" and not row["bdd_ready"]
    assert row["consistency"]["status"] == "potential_conflict"


def test_standalone_adoption_and_existing_output_refusal(session, tmp_path):
    pair = session.consistency_pairs(gate_policy=True)[0]
    actions = tmp_path / "review.json"
    actions.write_text(json.dumps({"requirements": [], "consistency_reviews": [
        {"requirement_ids": pair["requirement_ids"], **request(pair)}]}))
    cli.refine_run(session.current, session.source, actions, tmp_path / "reviewed")
    with pytest.raises(FileExistsError):
        cli.refine_run(session.current, session.source, actions, tmp_path / "reviewed")
    data = json.loads((tmp_path / "reviewed/c1/validated_requirements.json").read_text())
    assert all(r["consistency"]["status"] == "consistent" and not r["bdd_ready"] for r in data["requirements"])


def test_guided_resolve_pair_has_simple_output_and_resume(session):
    from c1_requirement_quality.demo_workflow import guided_demo
    pair = session.consistency_pairs(gate_policy=True)[0]
    replies = iter(["resolve-pair", *pair["requirement_ids"], "", "not_applicable",
        ",".join(pair["evidence"]), "Complete obligations", "No shared restrictions in this synthetic example",
        "Examined both obligations independently", "synthetic-test-reviewer", "complete", "yes", "pairs", "pause"])
    messages = []
    guided_demo(session.workspace, resume=True, ask=lambda _: next(replies), tell=messages.append)
    resumed = DemoSession(session.workspace)
    assert resumed.current != session.current
    assert resumed.read()[0]["requirements"][0]["consistency"]["status"] == "consistent"
    assert any("blocker cleared" in m for m in messages)
    assert any(NOTICE in m for m in messages)
    assert any("0 requirement comparisons remain blocking" in m for m in messages)
    assert not any("binding_inputs" in m or "sha256" in m for m in messages)
    assert all(not r["bdd_ready"] for r in resumed.read()[0]["requirements"])


def test_clarification_invalidates_persisted_review_and_acceptance(session):
    pair = session.consistency_pairs(gate_policy=True)[0]
    session.adopt_consistency(pair["requirement_ids"], **request(pair))
    session.apply({"requirement_id": "REQ-EX-002", "human_decision": "not_required"}, "synthetic-test-reviewer", True)
    session.apply({"requirement_id": "REQ-EX-001", "clarification_questions": ["Which email recipients are intended?"]}, "synthetic-test-reviewer", True)
    data, _, _, state = DemoSession(session.workspace).read()
    assert any(e["kind"] == "consistency_review_invalidated" for e in state["events"])
    assert all(r["consistency"]["status"] == "potential_conflict" for r in data["requirements"])
    assert all(r["human_decision"] == "pending" and not r["bdd_ready"] for r in data["requirements"])


def test_all_pairs_need_complete_coverage(case):
    rows, records, context = case
    text = "The system shall list contacts."
    rows.append({"requirement_id": "REQ-EX-003", "original_text": text, "final_text": text, "source": {"section": "Contacts"}})
    records["REQ-EX-003"] = {"questions": {}, "answers": []}
    for pair in views(*case):
        context["history"].append(create_review(pair, request(pair)))
    assert len(context["history"]) == 3
    for row in rows:
        result = assess(row["requirement_id"], *case)
        assert result["effective_review"]["all_not_applicable"]
        assert result["effective_review"]["explanation"] == NOTICE


def test_review_adoption_interrupted_after_publish_is_not_replayed(session):
    from unittest.mock import patch
    pair = session.consistency_pairs(gate_policy=True)[0]
    with patch.object(session, "recover", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            session.adopt_consistency(pair["requirement_ids"], **request(pair))
    resumed = DemoSession(session.workspace)
    assert resumed.pending is not None
    with patch.object(cli, "refine_run", side_effect=AssertionError("Must not replay")):
        resumed.recover(True)
    assert DemoSession(session.workspace).read()[0]["requirements"][0]["consistency"]["status"] == "consistent"
