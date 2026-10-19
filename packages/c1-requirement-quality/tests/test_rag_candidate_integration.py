"""Authoritative receipt consumption across existing candidate review interfaces."""
import copy
import json
from types import SimpleNamespace

import pytest

from test_candidate_validation import context
from c1_requirement_quality import cli, wizard
from c1_requirement_quality.demo_workflow import DemoSession
from c1_requirement_quality.refinement import _evaluate_candidate, process_refinement_actions
from c1_requirement_quality.rewrite_generator import generate_candidate_suggestions
from c1_requirement_quality.validation_lifecycle import grounded_current
from c1_requirement_quality.workflow_persistence import load_state, refine_with_history
from c1_requirement_quality.rag import candidate_validation as service

CANDIDATE = "The system shall retain logs"


def inputs(context):
    artifact, source, rid, _, _, _ = context
    text, manifest = service.verify_source(artifact, source)
    state, _ = load_state(artifact, source)
    data = json.loads(artifact.read_bytes())
    row = next(r for r in data["requirements"] if r["requirement_id"] == rid)
    return data, row, text, manifest, state


def receipt_context(context, candidate=CANDIDATE):
    artifact, source, rid, out, _, factory = context
    digest = service.validate_candidate_run(artifact, source, rid, candidate, out, analyser_factory=factory)
    return service.CandidateGroundingContext(artifact, source,
        {service.stable_candidate_id(rid, candidate): (out, digest)}, analyser_factory=factory)


def evaluate(context, grounding_context, candidate=CANDIDATE):
    _, row, text, _, state = inputs(context)
    return _evaluate_candidate(candidate, text, row["original_text"], state["requirements"][row["requirement_id"]],
        grounding_context=grounding_context, requirement_id=row["requirement_id"], require_rag=True)


@pytest.mark.parametrize("label,verdict,eligible", [
    ("entailment", "SUPPORTED", True), ("contradiction", "CONTRADICTED", False),
    ("neutral", "INCONCLUSIVE", False),
])
def test_authoritative_verdicts_are_used(context, label, verdict, eligible):
    context[4]["label"] = label
    gc = receipt_context(context)
    result = evaluate(context, gc)
    assert result["grounding"]["verdict"] == verdict
    assert result["candidate_eligible"] is eligible
    assert result["grounding"]["validation_receipt_sha256"]
    assert result["grounding"]["diagnostics"][0]["retrieved_evidence"]
    assert context[4]["analyses"] == 1
    assert all(i.released for i in context[4]["instances"])


def test_missing_context_cannot_use_lexical_self_support(context):
    result = evaluate(context, None)
    assert result["grounding_check"] == "fail" and not result["candidate_eligible"]
    gc = service.CandidateGroundingContext(context[0], context[1])
    assert not evaluate(context, gc)["candidate_eligible"]
    assert not context[4]["instances"]  # No silent inference or model loading.


@pytest.mark.parametrize("failure", ["tamper", "model", "workflow", "error"])
def test_unusable_evidence_is_ineligible(context, monkeypatch, failure):
    if failure == "error":
        context[4]["outer_error"] = True
    gc = receipt_context(context)
    if failure == "tamper":
        context[3].write_text("{}", encoding="utf-8")
    elif failure == "model":
        context[4]["models"]["nli"]["asset_sha256"]["weights"] = "changed"
    elif failure == "workflow":
        original = service._verify_snapshot
        def changed(*args):
            text, manifest, artifact, state = original(*args)
            state = copy.deepcopy(state)
            state["requirements"][context[2]]["clarification_requested"] = True
            return text, manifest, artifact, state
        monkeypatch.setattr(service, "_verify_snapshot", changed)
    result = evaluate(context, gc)
    assert not result["candidate_eligible"]
    assert result["grounding"]["verdict"] == "ERROR"


@pytest.mark.parametrize("candidate,field", [
    ("The user shall retain logs.", "actor"),
    ("The system shall delete logs.", "action"),
    ("The system shall retain reports.", "target"),
    ("The system shall not retain logs.", "is_negated"),
    ("The system may retain logs.", "modality"),
    ("The system shall retain 3 logs.", "numeric_values"),
    ("The system shall retain logs for 3 days.", "units"),
    ("The system shall retain logs when enabled.", "conditions"),
])
def test_meaning_changes_are_detected(candidate, field):
    result = service.compare_meaning("The system shall retain logs.", candidate)
    assert result["status"] == "changed_or_unproven"
    assert field in result["differences"]


def test_omitted_and_added_obligations_are_reported():
    original = "The system shall retain logs. The user shall view reports."
    result = service.compare_meaning(original, "The system shall retain logs.")
    assert result["removed_or_changed_obligations"] == ["The user shall view reports"]
    result = service.compare_meaning("The system shall retain logs.", original)
    assert result["added_or_changed_obligations"] == ["The user shall view reports"]


def test_supported_but_changed_meaning_is_not_eligible(context):
    candidate = "The system must retain logs."
    gc = receipt_context(context, candidate)
    result = evaluate(context, gc, candidate)
    assert result["grounding"]["verdict"] == "SUPPORTED"
    assert result["grounding"]["meaning_preservation"]["status"] == "changed_or_unproven"
    assert not result["candidate_eligible"]


def test_review_and_lifecycle_interfaces_agree(context, tmp_path):
    gc = receipt_context(context)
    data, row, text, manifest, state = inputs(context)
    rid = row["requirement_id"]
    session = SimpleNamespace(current=context[0], source=context[1],
                              read=lambda: (data, text, manifest, state))
    candidate = {"candidate_id": service.stable_candidate_id(rid, CANDIDATE), "text": CANDIDATE}
    expected = evaluate(context, gc)
    assessment = wizard.Wizard(context[0].parent).candidate_assessment(session, rid, candidate, grounding_context=gc)
    assert assessment["evaluation"] == expected
    assert not assessment["validation"]["bdd_readiness"]["bdd_ready"]
    assert grounded_current(CANDIDATE, text, row["original_text"], state["requirements"][rid],
        grounding_context=gc, requirement_id=rid) == expected["grounding"]
    candidate["source_evidence"] = {"kind": "srs_chunk", "text": row["original_text"]}
    report = {"input_sha256": service.sha256(context[0].read_bytes()),
              "source_sha256": manifest["sha256"], "workflow_sha256": manifest.get("workflow_sha256"),
              "source_document": data["source_document"], "requirements": [{"requirement_id": rid,
              "original_text": row["original_text"], "ranked_candidates": [candidate], "diagnostic_suggestions": []}]}
    path = tmp_path / "suggestions.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    checked = DemoSession.candidates(session, path, grounding_context=gc)
    assert checked[0][1]["review_validation"]["evaluation"] == expected


def test_rag_wizard_default_cannot_use_missing_receipts(context):
    data, row, text, manifest, state = inputs(context)
    session = SimpleNamespace(current=context[0], source=context[1],
        read=lambda: (data, text, dict(manifest, rag_policy="c1-initial-rag-v1"), state))
    result = wizard.Wizard(context[0].parent).candidate_assessment(session, row["requirement_id"],
        {"text": CANDIDATE})
    assert not result["evaluation"]["candidate_eligible"]


def test_generation_ranks_only_eligible_candidates(context, tmp_path):
    source = tmp_path / "clean.md"
    source.write_text("# Requirements\n1. The system shall retain logs.\n\n# Evidence\nThe system must retain logs.\n", encoding="utf-8")
    cli.run(source, tmp_path / "clean", "RUN-20261018-120002-abcd", registry_path=tmp_path / "clean-registry.json")
    artifact = tmp_path / "clean/c1/validated_requirements.json"
    rid = json.loads(artifact.read_bytes())["requirements"][0]["requirement_id"]
    clean = (artifact, source, rid, tmp_path / "clean-validation.json", context[4], context[5])
    gc = receipt_context(clean)
    data, row, text, _, state = inputs(clean)
    class Backend:
        def generate(self, *args, **kwargs):
            return [{"text": CANDIDATE, "strategy": "supplied", "source_evidence": {}},
                    {"text": "The system must retain logs.", "strategy": "supplied", "source_evidence": {}}]
    report = generate_candidate_suggestions(data, text, grounding_mode="rag", backend=Backend(),
        grounding_context=gc, workflow_records=state["requirements"], requirement_ids=[rid])
    r = report["requirements"][0]
    assert r["ranked_candidates"] or r["diagnostic_suggestions"]
    assert all(c["text"] == CANDIDATE for c in r["ranked_candidates"] + r["diagnostic_suggestions"])
    assert any(c["rejected_reason"] == "rag_or_meaning_ineligible" for c in r["rejected_candidates"])


def test_rag_refinement_and_history_remain_blocked(context):
    gc = receipt_context(context)
    data, _, text, manifest, state = inputs(context)
    with pytest.raises(ValueError, match="remain blocked"):
        process_refinement_actions(data, {"requirements": []}, text, grounding_context=gc)
    with pytest.raises(ValueError, match="Unverified workflow parent or manifest"):
        refine_with_history(data, {"requirements": []}, text, state, context[0], context[0].parent,
                            dict(manifest, rag_policy="c1-initial-rag-v1"))


@pytest.mark.parametrize("changed", ["original", "source", "workflow"])
def test_caller_basis_cannot_override_bound_evidence(context, changed):
    gc = receipt_context(context)
    _, row, text, _, state = inputs(context)
    record = copy.deepcopy(state["requirements"][context[2]])
    original = row["original_text"]
    if changed == "original":
        original = "The system shall delete logs."
    elif changed == "source":
        text += "\nInjected source"
    else:
        record["clarification_requested"] = True
    result = _evaluate_candidate(CANDIDATE, text, original, record,
        grounding_context=gc, requirement_id=context[2])
    assert not result["candidate_eligible"]
    assert result["grounding"]["verdict"] == "ERROR"


def test_different_parent_cannot_supply_generation_context(context):
    gc = receipt_context(context)
    data, _, text, _, _ = inputs(context)
    data = copy.deepcopy(data)
    data["run_id"] = "RUN-20261018-120003-abcd"
    with pytest.raises(ValueError, match="parent artifact mismatch"):
        generate_candidate_suggestions(data, text, grounding_context=gc)
