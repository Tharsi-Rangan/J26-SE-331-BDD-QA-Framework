"""Real workflow, synthetic reviewer actions and injected models; no cloud."""
import copy
import json

import pytest

from test_grounded_review_intents import review
from test_candidate_validation import context
from test_groq_generator import transport, MODEL, KEY
from c1_requirement_quality.demo_workflow import DemoSession
from c1_requirement_quality.refined_export import export_refined_srs
from c1_requirement_quality.contract import validate_contract_artifact


@pytest.mark.parametrize("review", [("The system shall wait for [timeout].",
    ["The system shall wait for [timeout]."])], indirect=True)
def test_confirmed_exact_answer_approval_publication_resume_export(review, tmp_path):
    session, rid, _, control, factory = review
    original = session.current.read_bytes()
    candidate = "The system shall wait for 2 seconds."
    question = next(iter(session.review_read()[3]["requirements"][rid]["questions"].values()))
    session.review_action({"requirement_id": rid, "clarification_answers": [
        {"question_id": question["question_id"], "answer": "2 seconds"}]}, "synthetic-reviewer", True)
    session.review_action({"requirement_id": rid, "selected_candidate_text": candidate}, "synthetic-reviewer", True)
    session.validate_candidate_evidence(rid, candidate)
    session.review_action({"requirement_id": rid, "human_decision": "approved"}, "synthetic-reviewer", True)
    assert session.current.read_bytes() == original
    intent = session.approval_intents()[-1]
    ground = intent["eligibility"]["evaluation"]["grounding"]
    assert ground["original_srs_status"] == "unsupported"
    assert ground["human_clarification_evidence"][0]["actor_id"] == "synthetic-reviewer"
    assert ground["human_evidence_binding"]["requirement_id"] == rid
    assert ground["eligible_for_acceptance"] and intent["active"]
    session.publish_approved("synthetic-reviewer", True)
    resumed = DemoSession(session.workspace, analyser_factory=factory)
    row = resumed.read()[0]["requirements"][0]
    validate_contract_artifact(resumed.read()[0])
    assert row["bdd_ready"] and row["final_text"] == candidate
    assert row["original_text"] == "The system shall wait for [timeout]."
    exported = export_refined_srs(resumed, tmp_path / "export")
    assert exported["refined_srs.docx"].is_file()
    report = json.loads(exported["quality_report.json"].read_text())
    assert report["summary"]["bdd_ready"] == 1


@pytest.mark.parametrize("review", [("The system shall wait for [timeout].",
    ["The system shall wait for [timeout]."])], indirect=True)
def test_stale_or_unsupported_human_changes_never_approve(review):
    session, rid, _, _, factory = review
    question = next(iter(session.review_read()[3]["requirements"][rid]["questions"].values()))
    def answer(value):
        session.review_action({"requirement_id": rid, "clarification_answers": [
            {"question_id": question["question_id"], "answer": value}]}, "synthetic-reviewer", True)
    answer("2 seconds")
    for candidate in ("The system shall wait for 3 seconds.",
                      "The system shall wait for 2 seconds and delete accounts."):
        session.review_action({"requirement_id": rid, "selected_candidate_text": candidate}, "synthetic-reviewer", True)
        session.validate_candidate_evidence(rid, candidate)
        with pytest.raises(ValueError, match="not eligible"):
            session.review_action({"requirement_id": rid, "human_decision": "approved"}, "synthetic-reviewer", True)
    candidate = "The system shall wait for 2 seconds."
    session.review_action({"requirement_id": rid, "selected_candidate_text": candidate}, "synthetic-reviewer", True)
    session.validate_candidate_evidence(rid, candidate)
    session.review_action({"requirement_id": rid, "human_decision": "approved"}, "synthetic-reviewer", True)
    answer("3 seconds")
    assert not DemoSession(session.workspace, analyser_factory=factory).approval_intents()[-1]["active"]
    with pytest.raises(ValueError, match="No current approved intents"):
        session.publish_approved("synthetic-reviewer", True)
    with pytest.raises(ValueError, match="not eligible"):
        session.review_action({"requirement_id": rid, "human_decision": "approved"}, "synthetic-reviewer", True)


def test_mandatory_rag_consistency_is_explicit_bound_and_replayed(review):
    session, _, _, _, factory = review
    # This fixture has one requirement: a fabricated peer is never accepted.
    before = len(session.events)
    with pytest.raises(ValueError, match="Unknown consistency pair"):
        session.adopt_consistency(["REQ-EX-001", "REQ-EX-999"],
            decision="not_applicable", evidence_refs=[], scope="synthetic", conditions="none",
            rationale="synthetic", reviewer="synthetic-reviewer", confirmed=True, coverage="complete")
    assert len(DemoSession(session.workspace, analyser_factory=factory).events) == before


@pytest.mark.parametrize("reject_peer", [False, True])
def test_two_requirement_consistency_review_reaches_publication(context, tmp_path, monkeypatch, reject_peer):
    from c1_requirement_quality import cli
    _, _, _, _, control, factory = context
    source = tmp_path / "two.md"
    obligations = ["The system shall retain logs.", "The user shall view reports."]
    source.write_text("# Requirements\n" + "\n".join(f"{i}. {text}" for i, text in enumerate(obligations, 1)))
    monkeypatch.setattr(cli, "RAGGroundingAnalyser", factory)
    cli.run(source, tmp_path / "two", "RUN-20261020-120000-pair", registry_path=tmp_path / "pair-registry.json",
            grounding_mode="rag", mandatory_rag=True)
    session = DemoSession.create(tmp_path / "pair-review", artifact=tmp_path / "two/c1/validated_requirements.json", source=source)
    session = DemoSession(session.workspace, analyser_factory=factory)
    rows = session.read()[0]["requirements"]
    ids = [r["requirement_id"] for r in rows]
    for row in rows:
        rid, text = row["requirement_id"], row["original_text"]
        session.review_action({"requirement_id": rid, "selected_candidate_text": text}, "synthetic-reviewer", True)
        control["passages"] = [text]
        session.validate_candidate_evidence(rid, text)
    if reject_peer:
        session.review_action({"requirement_id": ids[1], "selected_candidate_text": "The user shall delete accounts.",
            "human_decision": "rejected"}, "synthetic-reviewer", True)
    session.adopt_consistency(ids, decision="not_applicable", evidence_refs=[f"SRS:{rid}:original" for rid in ids],
        scope="Complete synthetic pair", conditions="No shared obligation or conditions in this fixture",
        rationale="Distinct subjects and objects were reviewed explicitly", reviewer="synthetic-reviewer",
        coverage="complete", confirmed=True)
    reopened = DemoSession(session.workspace, analyser_factory=factory)
    assert reopened.consistency_pairs(gate_policy=True)[0]["decision"] == "not_applicable"
    for rid in ids:
        if reject_peer and rid == ids[1]:
            continue
        session.review_action({"requirement_id": rid, "human_decision": "approved"}, "synthetic-reviewer", True)
    session.publish_approved("synthetic-reviewer", True)
    final = DemoSession(session.workspace, analyser_factory=factory)
    final_rows = final.read()[0]["requirements"]
    assert final_rows[0]["bdd_ready"]
    assert final_rows[1]["bdd_ready"] is (not reject_peer)
    if reject_peer:
        assert final_rows[1]["final_text"] == obligations[1]
        assert final_rows[1]["human_decision"] == "rejected"


def test_tier3_requires_actual_corrected_obligations_and_explicit_resolution(context, tmp_path, monkeypatch):
    from c1_requirement_quality import cli
    _, _, _, _, control, factory = context
    source = tmp_path / "conflicts.md"
    source.write_text("# Requirements\n1. The system shall allow deletion.\n2. The system shall not allow deletion.\n")
    control.update(passages=["The system shall allow deletion.", "The system shall not allow deletion."], label="neutral")
    monkeypatch.setattr(cli, "RAGGroundingAnalyser", factory)
    cli.run(source, tmp_path / "conflict", "RUN-20261020-120000-tr03", registry_path=tmp_path / "tr3-registry.json",
            grounding_mode="rag", mandatory_rag=True)
    session = DemoSession.create(tmp_path / "tr3-review", artifact=tmp_path / "conflict/c1/validated_requirements.json", source=source)
    session = DemoSession(session.workspace, analyser_factory=factory)
    rows = session.read()[0]["requirements"]
    assert all(r["tier"] == "TIER_3_ESCALATE" for r in rows)
    rid = rows[0]["requirement_id"]
    session.review_action({"requirement_id": rid, "selected_candidate_text": rows[0]["original_text"]}, "synthetic-reviewer", True)
    session.validate_candidate_evidence(rid, rows[0]["original_text"])
    with pytest.raises(ValueError, match="remains unresolved"):
        session.review_action({"requirement_id": rid, "workflow_action": "resolve_escalation", "resolution": "Reviewed"}, "synthetic-reviewer", True)
    replacement = "The system shall allow deletion when the administrator confirms ownership."
    question = "What requirement should replace the original obligation?"
    for row in rows:
        rid = row["requirement_id"]
        session.review_action({"requirement_id": rid, "selected_candidate_text": replacement,
            "clarification_questions": [question], "clarification_answers": [{"question": question, "answer": replacement}]}, "synthetic-reviewer", True)
        session.validate_candidate_evidence(rid, replacement)
    for row in rows:
        rid = row["requirement_id"]
        session.review_action({"requirement_id": rid, "workflow_action": "resolve_escalation",
            "resolution": "Both corrected obligations explicitly use the same confirmed ownership condition"}, "synthetic-reviewer", True)
    for row in rows:
        session.review_action({"requirement_id": row["requirement_id"], "human_decision": "approved"}, "synthetic-reviewer", True)
    session.publish_approved("synthetic-reviewer", True)
    final = DemoSession(session.workspace, analyser_factory=factory)
    assert all(r["bdd_ready"] and r["final_text"] == replacement for r in final.read()[0]["requirements"])
    assert all(r["original_assessment"]["tier"] == "TIER_3_ESCALATE" for r in final.read()[3]["requirements"].values())


@pytest.mark.parametrize("review", [("The system shall retain logs", ["The system shall retain logs."])], indirect=True)
def test_two_cloud_proposals_independently_validate_and_preserve_history(review, transport):
    from c1_requirement_quality.groq_generator import GroqGeneratorBackend
    session, rid, _, _, _ = review
    texts = ["The system shall retain logs.", "The user shall delete accounts."]
    transport["body"] = {"model": MODEL, "choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"candidates": [{"ambiguity": "Review wording", "clarification_question": "What wording is intended?",
            "measurable_rewrite": text} for text in texts]})}}]}
    backend = GroqGeneratorBackend(KEY, MODEL)
    result = session.generate_review_candidates([rid], backend=backend)
    row = result["requirements"][0]
    assert len(transport["calls"]) == 1
    assert [c["text"] for c in row["ranked_candidates"]] == texts[:1]
    assert [c["text"] for c in row["rejected_candidates"]] == texts[1:]
    before = {p: p.read_bytes() for p in (session.workspace / "sidecars").glob("review-generation-*.json")}
    session.generate_review_candidates([rid], backend=backend)
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert len(list((session.workspace / "sidecars").glob("review-generation-*.json"))) == 2
    assert session.read()[0]["requirements"][0]["human_decision"] == "pending"


@pytest.mark.parametrize("format_name,filename", [("docx", "refined_srs.docx"), ("json", "c1/validated_requirements.json"),
    ("quality", "quality_report.json"), ("decisions", "decision_report.json"), ("traceability", "traceability_report.json")])
def test_selectable_export_formats_never_promote_unapproved_content(review, tmp_path, format_name, filename):
    session = review[0]
    out = tmp_path / "selected-export"
    paths = export_refined_srs(session, out, formats={format_name})
    assert filename in paths and paths[filename].is_file()
    assert not session.read()[0]["requirements"][0]["bdd_ready"]
    with pytest.raises(FileExistsError):
        export_refined_srs(session, out, formats={format_name})
