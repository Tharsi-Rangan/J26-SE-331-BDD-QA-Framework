"""Candidate eligibility must consume the original from authenticated bytes."""
import copy
import inspect
import json
from pathlib import Path

import pytest

from test_candidate_validation import context
from c1_requirement_quality.rag import candidate_validation as service
from c1_requirement_quality.source_integrity import _verify_snapshot, sha256

ORIGINAL = "The system shall retain logs."
CHANGED = "The user shall view reports."


def bound(context, candidate=ORIGINAL):
    artifact, source, rid, out, _, factory = context
    digest = service.validate_candidate_run(artifact, source, rid, candidate, out, analyser_factory=factory)
    ctx = service.CandidateGroundingContext(artifact, source,
        {service.stable_candidate_id(rid, candidate): (out, digest)}, analyser_factory=factory)
    text, _, data, state = _verify_snapshot(artifact, source)
    return ctx, text, data, state


def replace_text_read(monkeypatch, artifact, forged):
    read = Path.read_text
    def substitute(path, *args, **kwargs):
        return json.dumps(forged) if path == artifact else read(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", substitute)


def test_substituted_original_cannot_make_changed_meaning_eligible(context, monkeypatch):
    context[4]["passages"] = [CHANGED]
    ctx, text, data, state = bound(context, CHANGED)
    rid = context[2]
    normal = ctx.assess(rid, CHANGED, text, ORIGINAL, state["requirements"][rid])
    assert normal["verdict"] == "SUPPORTED"
    assert normal["meaning_preservation"]["status"] == "changed_or_unproven"
    assert not normal["eligible_for_acceptance"]
    forged = copy.deepcopy(data)
    forged["requirements"][0]["original_text"] = CHANGED
    replace_text_read(monkeypatch, context[0], forged)
    result = ctx.assess(rid, CHANGED, text, CHANGED, state["requirements"][rid])
    assert not result["eligible_for_acceptance"]
    assert result["meaning_preservation"]["status"] != "preserved"


def test_check_parent_rejects_forged_text_reread(context, monkeypatch):
    ctx, _, data, _ = bound(context)
    forged = copy.deepcopy(data)
    forged["requirements"][0]["original_text"] = CHANGED
    replace_text_read(monkeypatch, context[0], forged)
    with pytest.raises(ValueError, match="different parent"):
        ctx.check_parent(forged)


def test_context_cannot_bind_unverified_first_and_last_reads(context, monkeypatch):
    artifact, source, rid, _, _, _ = context
    authentic = artifact.read_bytes()
    forged = json.loads(authentic)
    forged["requirements"][0]["original_text"] = CHANGED
    read = Path.read_bytes
    def substitute(path):
        if path == artifact and inspect.currentframe().f_back.f_code.co_name == "_context":
            return json.dumps(forged).encode()
        return read(path)
    monkeypatch.setattr(Path, "read_bytes", substitute)
    _, binding = service._context(artifact, source, rid, ORIGINAL, 5)
    assert binding["parent_artifact_sha256"] == sha256(authentic)
    assert binding["original_text_sha256"] == sha256(ORIGINAL.encode())


@pytest.mark.parametrize("change", ["original", "candidate", "requirement", "candidate_id", "receipt", "source", "workflow"])
def test_direct_assessment_fails_closed_on_mismatched_inputs(context, change):
    ctx, text, _, state = bound(context)
    rid = context[2]
    original, candidate, record = ORIGINAL, ORIGINAL, copy.deepcopy(state["requirements"][rid])
    if change == "original": original = CHANGED
    if change == "candidate": candidate = CHANGED
    if change == "requirement": rid = "REQ-EX-999"
    if change == "source": text += "forged source"
    if change == "workflow": record["clarification_requested"] = True
    if change == "candidate_id":
        ctx.receipts["wrong-candidate-id"] = ctx.receipts.pop(service.stable_candidate_id(rid, candidate))
    if change == "receipt":
        key = service.stable_candidate_id(rid, candidate)
        ctx.receipts[key] = (context[3], "0" * 64)
    result = ctx.assess(rid, candidate, text, original, record)
    assert not result["eligible_for_acceptance"]
    assert result["verdict"] == "ERROR"


@pytest.mark.parametrize("passages,label,verdict,eligible", [
    (["The system must retain logs."], "entailment", "SUPPORTED", True),
    (["The system shall not retain logs."], "entailment", "CONTRADICTED", False),
    (["The system must retain logs."], "neutral", "INCONCLUSIVE", False),
    ([], "entailment", "INCONCLUSIVE", False),
])
def test_verified_evidence_and_meaning_policies_are_preserved(context, passages, label, verdict, eligible):
    context[4].update(passages=passages, label=label)
    ctx, text, data, state = bound(context)
    ctx.check_parent(data)
    result = ctx.assess(context[2], ORIGINAL, text, ORIGINAL, state["requirements"][context[2]])
    assert result["verdict"] == verdict
    assert result["eligible_for_acceptance"] == eligible


def test_inference_error_remains_ineligible(context):
    context[4]["outer_error"] = True
    ctx, text, _, state = bound(context)
    result = ctx.assess(context[2], ORIGINAL, text, ORIGINAL, state["requirements"][context[2]])
    assert result["verdict"] == "ERROR"
    assert not result["eligible_for_acceptance"]


@pytest.mark.parametrize("part", ["artifact", "workflow", "manifest", "source"])
def test_changed_parent_inputs_are_rejected(context, part):
    ctx, text, data, state = bound(context)
    target = {"artifact": context[0], "source": context[1],
              "workflow": context[0].parent / "internal/workflow_snapshot.json",
              "manifest": context[0].parent / "internal/source_manifest.json"}[part]
    raw = target.read_bytes()
    target.chmod(0o644)
    if part == "manifest":
        payload = json.loads(raw)
        payload["document_id"] = "FORGED-DOCUMENT"
        target.write_text(json.dumps(payload), encoding="utf-8")
    else:
        target.write_bytes(raw + b" ")
    result = ctx.assess(context[2], ORIGINAL, text, ORIGINAL, state["requirements"][context[2]])
    assert not result["eligible_for_acceptance"]
    with pytest.raises(ValueError):
        ctx.check_parent(data)


@pytest.mark.parametrize("part", ["artifact", "workflow", "manifest", "source"])
def test_mutation_after_authenticated_snapshot_capture_is_rejected(context, monkeypatch, part):
    ctx, text, _, state = bound(context)
    target = {"artifact": context[0], "source": context[1],
              "workflow": context[0].parent / "internal/workflow_snapshot.json",
              "manifest": context[0].parent / "internal/source_manifest.json"}[part]
    verify = service._verify_snapshot
    changed = []
    def mutate(*args):
        snapshot = verify(*args)
        if not changed:
            target.chmod(0o644)
            if part == "manifest":
                manifest = json.loads(target.read_bytes())
                manifest["document_id"] = "CHANGED-DOCUMENT"
                target.write_text(json.dumps(manifest), encoding="utf-8")
            else:
                target.write_bytes(target.read_bytes() + b" ")
            changed.append(part)
        return snapshot
    monkeypatch.setattr(service, "_verify_snapshot", mutate)
    result = ctx.assess(context[2], ORIGINAL, text, ORIGINAL, state["requirements"][context[2]])
    assert changed == [part]
    assert not result["eligible_for_acceptance"]
    assert result["verdict"] == "ERROR"
