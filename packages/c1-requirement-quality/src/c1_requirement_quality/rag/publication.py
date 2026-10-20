"""Journal-authorized publication of M1 intents; no inference or policy fallback."""
from __future__ import annotations

import copy
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from c1_requirement_quality.source_integrity import sha256, VerifiedWorkflowContext
from c1_requirement_quality.rag.candidate_validation import _canonical

_factory = ContextVar("publication_model_provenance_adapter", default=None)
_verifying = ContextVar("publication_verification_stack", default=())


@contextmanager
def publication_models(factory):
    token = _factory.set(factory or _factory.get())
    try:
        yield
    finally:
        _factory.reset(token)


def active_intents(session):
    state = session._review_state or session.read()[3]
    basis = session._review_basis(state)
    return [copy.deepcopy(e) for e in session._approval_intents if e["basis"] == basis]


def authorize_operation(operation, source, *, analyser_factory=None):
    """Obtain policy exclusively from the independently anchored pre-operation journal."""
    from c1_requirement_quality.demo_workflow import DemoSession, _verified_journal
    from c1_requirement_quality.workflow_persistence import _candidate_snapshot_identity, _reject_ancestry_reparse
    if (not isinstance(operation, dict) or operation.get("operation_version") != 2
            or not isinstance(operation.get("approval_intent_sha256s"), list)
            or not operation["approval_intent_sha256s"]):
        raise ValueError("Journal-backed approval publication operation required")
    workspace = Path(operation["workspace"])
    _reject_ancestry_reparse(workspace)
    journal = _verified_journal(workspace, {"sequence": operation["sequence"], "sha256": operation["sha256"]})
    if journal[-1] != operation or operation["kind"] != "pending":
        raise ValueError("Publication operation is not journal-authenticated")
    anchor = {"sequence": operation["sequence"] - 1, "sha256": operation["previous"]}
    if operation["registry_anchor"] != anchor:
        raise ValueError("Publication registry cutoff mismatch")
    session = DemoSession(workspace, _registry_anchor=anchor,
                          analyser_factory=analyser_factory or _factory.get())
    data, text, manifest, state = session.read()
    if (manifest.get("rag_policy") != "c1-initial-rag-v1" or session.pending is not None
            or session.current.resolve() != Path(operation["parent"]).resolve()
            or sha256(source.read_bytes()) != manifest["sha256"]
            or operation["parent_identity"] != _candidate_snapshot_identity(manifest, state)
            or operation["parent_sha256"] != manifest["artifact_sha256"]):
        raise ValueError("Approval publication parent/source mismatch")
    available = {e["sha256"]: e for e in active_intents(session)}
    selected = operation["approval_intent_sha256s"]
    if len(set(selected)) != len(selected) or not set(selected) <= available.keys():
        raise ValueError("Missing, stale, duplicate or unapproved publication intent")
    intents = [available[digest] for digest in selected]
    if len({e["action"]["requirement_id"] for e in intents}) != len(intents):
        raise ValueError("Ambiguous publication requirement selection")
    expected = {"requirements": [{**e["action"], "actor_id": e["reviewer"]} for e in intents]}
    actions = Path(operation["actions"])
    _reject_ancestry_reparse(actions)
    raw = actions.read_bytes()
    if (sha256(raw) != operation["actions_sha256"] or json.loads(raw) != expected
            or sha256(_canonical(expected)) != operation["actions_parsed_sha256"]
            or operation["evidence_candidate_ids"] != [e["eligibility"]["candidate_id"] for e in intents]):
        raise ValueError("Publication actions or selected evidence disagree with approval")
    return session, intents


def materialize(operation, source, *, analyser_factory=None):
    """Recompute the complete final set using existing independent readiness checks."""
    session, intents = authorize_operation(operation, source, analyser_factory=analyser_factory or _factory.get())
    from c1_requirement_quality.refinement import _consistency_with_candidate, can_mark_bdd_ready
    from c1_requirement_quality.effective_consistency import context_from_state
    from c1_requirement_quality.validation_lifecycle import validation_signature
    from c1_requirement_quality.workflow_persistence import (
        build_initial_rag_ancestry, refinement_operation_binding, _sync_candidates, _workflow_status,
    )
    data, text, manifest, parent = session.read()
    state = copy.deepcopy(session._review_state or parent)
    state.pop("parent_evidence_links", None)
    state.pop("rag_publication", None)
    state.update(snapshot_id=operation["child_snapshot_id"], round=parent["round"] + 1,
        parent={"snapshot_id": parent["snapshot_id"],
                "artifact_path": os.path.relpath(session.current, Path(operation["out"]) / "c1").replace("\\", "/"),
                "artifact_sha256": manifest["artifact_sha256"], "workflow_sha256": manifest["workflow_sha256"],
                "legacy_diagnostics_sha256": parent.get("legacy_diagnostics_sha256")},
        initial_rag_ancestry=build_initial_rag_ancestry(VerifiedWorkflowContext(session.current, session.source)),
        operation_binding=refinement_operation_binding(operation),
        rag_publication={"version": 1, "workspace": str(session.workspace),
            "pending_sequence": operation["sequence"], "pending_sha256": operation["sha256"],
            "approval_intent_sha256s": operation["approval_intent_sha256s"]})
    output = copy.deepcopy(data)
    by_id = {e["action"]["requirement_id"]: e for e in intents}
    for row in output["requirements"]:
        rid = row["requirement_id"]
        record = state["requirements"][rid]
        baseline = record["original_assessment"]
        for key in ("defects", "tier", "grounding", "consistency", "validation"):
            row[key] = copy.deepcopy(baseline[key])
        row.update(final_text=row["original_text"], bdd_ready=False, human_decision="pending",
            selected_candidate_id=record["selected_candidate_id"],
            candidates=[{"candidate_id": cid, "text": item["text"]} for cid, item in record["candidates"].items()])
        if any(e["review_version"] == 2 for e in intents) and record["questions"]:
            row["clarification_questions"] = [q["text"] for q in record["questions"].values()]
        row["validation"] = copy.deepcopy(row["validation"] or {"status": "needs_review", "checks": {}})
        row["validation"]["status"] = "needs_review"
        selected = record["candidates"].get(record["selected_candidate_id"])
        if selected and selected["status"] == "REJECTED":
            row["human_decision"] = "rejected"
        if rid in by_id:
            intent = by_id[rid]
            row["final_text"] = selected["text"]
            checked = session._review_evaluation(rid, session._review_state or parent,
                                                review_version=intent["review_version"])
            if checked != intent["eligibility"]:
                raise ValueError("Approval eligibility changed before publication")
            row.update(human_decision="approved", defects=checked["evaluation"]["quality_findings"],
                grounding=checked["evaluation"]["grounding"], consistency=checked["consistency"], tier=checked["tier"]["tier"],
                validation={"status": "passed", "checks": copy.deepcopy(checked["validation"]["checks"])})
            # Contract grounding has a frozen shape; retain rich evidence in diagnostics.
            row["grounding"] = {k: row["grounding"][k] for k in ("status", "evidence")}
            row["consistency"] = {k: row["consistency"][k] for k in ("status", "related_requirement_ids", "conflicts")}
    diagnostics = []
    peers = [{"requirement_id": r["requirement_id"], "text": r["final_text"]} for r in output["requirements"]]
    for row in output["requirements"]:
        rid = row["requirement_id"]
        record = state["requirements"][rid]
        checked = by_id[rid]["eligibility"] if rid in by_id else None
        if checked:
            consistency = _consistency_with_candidate(rid, row["final_text"], output["requirements"],
                state["requirements"], context_from_state(state))
            if consistency != checked["consistency"]:
                raise ValueError("Final peer set differs from independently approved consistency basis")
            row["bdd_ready"] = can_mark_bdd_ready("passed", row["validation"]["checks"], "approved", consistency_result=consistency)
            if not row["bdd_ready"]:
                raise ValueError("Mandatory readiness conditions are not satisfied")
        record.pop("current_validation", None)
        _sync_candidates(state, row)
        _workflow_status(state, row)
        diagnostics.append({"requirement_id": rid, "approval_intent_sha256": by_id[rid]["sha256"] if checked else None,
            "original_text": row["original_text"], "final_text": row["final_text"],
            "evaluation": checked, "clarification_resolution": copy.deepcopy(record["questions"]),
            "answer_history": copy.deepcopy(record["answers"]), "workflow_status": record["workflow_status"],
            "validation_signature": validation_signature(row["final_text"], row, text, peers, record),
            "bdd_ready": row["bdd_ready"]})
    return output, diagnostics, state, session


def verify_publication(path, source, manifest, artifact, state, *, staging=False):
    """Check exact child bytes against independent prepared journal commitments."""
    from c1_requirement_quality.demo_workflow import _verified_journal
    from c1_requirement_quality.workflow_persistence import candidate_evidence_path, _reject_ancestry_reparse
    proof = state.get("rag_publication")
    for local in (path, path.parent / "internal/workflow_snapshot.json", path.parent / "internal/source_manifest.json",
                  path.parent / "refinement_diagnostics.json", path.parent / "internal/normalized_ingestion.json",
                  path.parent / "internal" / manifest["archived_source"]):
        _reject_ancestry_reparse(local)
    if not isinstance(proof, dict) or type(proof.get("version")) is not int or proof["version"] != 1:
        raise ValueError("Initial RAG descendant authorization remains blocked: publication proof required")
    stack = _verifying.get()
    key = (str(path.resolve()), manifest["artifact_sha256"], state["snapshot_id"])
    if key in stack or len(stack) >= 32:
        raise ValueError("Cyclic or excessive publication verification depth")
    token = _verifying.set(stack + (key,))
    try:
        workspace = Path(proof["workspace"])
        _reject_ancestry_reparse(workspace)
        journal = _verified_journal(workspace)
        sequence = proof["pending_sequence"]
        if type(sequence) is not int or sequence < 1 or sequence >= len(journal):
            raise ValueError("Publication pending/prepared journal missing")
        operation = journal[sequence - 1]
        if operation["sha256"] != proof["pending_sha256"] or operation["approval_intent_sha256s"] != proof["approval_intent_sha256s"]:
            raise ValueError("Publication journal proof mismatch")
        prepared = journal[sequence]
        if (prepared["kind"] != "prepared" or prepared["operation_id"] != operation["operation_id"]
                or prepared["pending_sha256"] != operation["sha256"]):
            raise ValueError("Publication prepared event mismatch")
        if not staging and path.resolve() != (Path(operation["out"]) / "c1/validated_requirements.json").resolve():
            raise ValueError("Inspection or copied artifacts cannot authorize publication")
        for event in journal[sequence + 1:]:
            if event.get("operation_id") == operation["operation_id"] and event["kind"] == "cancelled":
                raise ValueError("Cancelled publication is not authorized")
        expected, diagnostics, workflow, session = materialize(operation, source, analyser_factory=_factory.get())
        # Archive identities are independently recovered from the retained prefix.
        from c1_requirement_quality.workflow_persistence import build_parent_evidence_links
        links = build_parent_evidence_links(VerifiedWorkflowContext(session.current, source), workspace,
            operation["evidence_candidate_ids"], analyser_factory=_factory.get(), registry_anchor=operation["registry_anchor"])
        workflow.update(parent_evidence_links=links, artifact_sha256=manifest["artifact_sha256"])
        if artifact != expected or state != workflow or sha256(_canonical(links)) != operation["evidence_links_sha256"]:
            raise ValueError("Published child differs from approved obligations/workflow")
        for link in links["links"]:
            for relative, digest in ((link["reference_path"], link["reference_sha256"]), (link["evidence_path"], link["receipt_sha256"])):
                if sha256(candidate_evidence_path(path.parent, relative).read_bytes()) != digest:
                    raise ValueError("Published evidence archive digest mismatch")
        diagnostic_raw = (path.parent / "refinement_diagnostics.json").read_bytes()
        if json.loads(diagnostic_raw) != diagnostics:
            raise ValueError("Published diagnostics differ from approved checks")
        commitment = {"version": 1, "snapshot_id": state["snapshot_id"], "artifact_sha256": manifest["artifact_sha256"],
            "workflow_sha256": manifest["workflow_sha256"], "manifest_sha256": sha256(_canonical(manifest)),
            "diagnostics_sha256": sha256(diagnostic_raw)}
        if prepared["commitment"] != commitment:
            raise ValueError("Published child prepared commitment mismatch")
    finally:
        _verifying.reset(token)
