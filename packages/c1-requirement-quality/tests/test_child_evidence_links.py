"""Read-only verification of synthetic sealed children; no publication integration."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_candidate_validation import context
from test_grounding_policy import rag_run
from c1_requirement_quality import cli
from c1_requirement_quality.demo_workflow import DemoSession
from c1_requirement_quality.rag import candidate_validation as service
from c1_requirement_quality.source_integrity import (
    VerifiedWorkflowContext, copy_source_bundle, resolve_workflow_policy, sha256,
)
from c1_requirement_quality.workflow_persistence import (
    PARENT_EVIDENCE_PURPOSE, build_parent_evidence_links, candidate_evidence_path,
    refine_with_history, verify_child_evidence_links,
)

TEXT = "The system shall retain logs."
CANDIDATE = TEXT.rstrip(".")


def make_snapshot(parent, source, target, actions, links=None):
    """Create only temporary test-fixture bytes using existing in-memory services."""
    policy = VerifiedWorkflowContext(parent, source)
    _, text, manifest, state = resolve_workflow_policy(policy)
    data = json.loads(parent.read_bytes())
    refined, _, child_state = refine_with_history(data, {"requirements": actions}, text,
        state, parent, target, manifest)
    if links is not None:
        child_state["parent_evidence_links"] = copy.deepcopy(links)
    target.mkdir(parents=True)
    (target / "validated_requirements.json").write_text(json.dumps(refined), encoding="utf-8")
    copy_source_bundle(parent, target, manifest, child_state)
    return target / "validated_requirements.json"


def archive_links(child, workspace, links):
    for link in links["links"]:
        for key in ("reference_path", "evidence_path"):
            original = candidate_evidence_path(workspace, link[key])
            archived = candidate_evidence_path(child.parent, link[key])
            archived.parent.mkdir(parents=True, exist_ok=True)
            archived.write_bytes(original.read_bytes())


def reseal_fixture(child, mutate):
    """Mutate owned test metadata and reseal, to exercise semantic checks too."""
    workflow = child.parent / "internal/workflow_snapshot.json"
    state = json.loads(workflow.read_bytes())
    mutate(state)
    workflow.chmod(0o644)
    workflow.write_text(json.dumps(state), encoding="utf-8")
    manifest_path = child.parent / "internal/source_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["workflow_sha256"] = sha256(workflow.read_bytes())
    manifest_path.chmod(0o644)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def linked(context, tmp_path):
    parent, source, rid, _, control, factory = context
    session = DemoSession.create(tmp_path / "s", artifact=parent, source=source)
    session.validate_candidate_evidence(rid, CANDIDATE, analyser_factory=factory)
    cid = service.stable_candidate_id(rid, CANDIDATE)
    policy = VerifiedWorkflowContext(parent, source)
    links = build_parent_evidence_links(policy, session.workspace, [cid], analyser_factory=factory)
    child = make_snapshot(parent, source, tmp_path / "c/c1",
        [{"requirement_id": rid, "candidate_texts": [CANDIDATE]}], links)
    archive_links(child, session.workspace, links)
    return {"parent": parent, "source": source, "rid": rid, "cid": cid,
            "session": session, "links": links, "child": child, "control": control, "factory": factory}


def verify(bundle):
    return verify_child_evidence_links(bundle["child"], bundle["source"],
        registry_workspace=bundle["session"].workspace, analyser_factory=bundle["factory"])


def test_valid_parent_evidence_child_is_read_only_and_non_authoritative(linked):
    bundle = linked
    roots = [bundle["parent"].parent, bundle["child"].parent, bundle["session"].workspace]
    before = {path: path.read_bytes() for root in roots for path in root.rglob("*") if path.is_file()}
    result = verify(bundle)
    assert result["purpose"] == PARENT_EVIDENCE_PURPOSE
    assert result["links"][0]["verdict_on_parent"] == "SUPPORTED"
    assert result["links"][0]["origin_snapshot_id"] == bundle["links"]["links"][0]["binding"]["snapshot_id"]
    assert result["links"][0]["origin_snapshot_id"] != result["child_snapshot_id"]
    assert not any(result[key] for key in ("child_independently_validated", "approval_authorized",
                                          "publication_authorized", "bdd_ready_authorized"))
    assert bundle["control"]["analyses"] == 1
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert all(instance.released for instance in bundle["control"]["instances"])
    record = json.loads(candidate_evidence_path(bundle["child"].parent,
        bundle["links"]["links"][0]["evidence_path"]).read_bytes())
    assert record["binding"]["parent_artifact_sha256"] == sha256(bundle["parent"].read_bytes())
    assert record["binding"]["parent_artifact_sha256"] != sha256(bundle["child"].read_bytes())


@pytest.mark.parametrize("field", ["snapshot_id", "parent_artifact_sha256", "workflow_sha256",
    "workflow_basis_sha256", "requirement_id", "original_text_sha256", "candidate_text_sha256",
    "document_id", "source_sha256", "normalized_sha256", "verification_policy"])
def test_changed_required_binding_rejected_even_in_sealed_child(linked, field):
    reseal_fixture(linked["child"], lambda state:
        state["parent_evidence_links"]["links"][0]["binding"].__setitem__(field, "wrong"))
    with pytest.raises(ValueError):
        verify(linked)


@pytest.mark.parametrize("field", ["candidate_text", "receipt_sha256", "reference_sha256", "models"])
def test_changed_link_metadata_rejected(linked, field):
    reseal_fixture(linked["child"], lambda state:
        state["parent_evidence_links"]["links"][0].__setitem__(field, "modified"))
    with pytest.raises(ValueError):
        verify(linked)


@pytest.mark.parametrize("field", ["parent_evidence_links", "binding", "candidate_text", "models",
                                   "receipt_sha256", "reference_sha256", "reference_path", "evidence_path"])
def test_missing_metadata_rejected(linked, field):
    def remove(state):
        if field == "parent_evidence_links":
            state.pop(field)
        else:
            state["parent_evidence_links"]["links"][0].pop(field)
    reseal_fixture(linked["child"], remove)
    with pytest.raises(ValueError):
        verify(linked)


@pytest.mark.parametrize("change", ["bool_version", "unsupported_version", "empty", "malformed",
                                   "current_purpose", "approval_flag", "link_approval_flag"])
def test_malformed_or_authoritative_envelopes_rejected(linked, change):
    def mutate(state):
        envelope = state["parent_evidence_links"]
        if change == "bool_version": envelope["version"] = True
        elif change == "unsupported_version": envelope["version"] = 2
        elif change == "empty": envelope["links"] = []
        elif change == "malformed": envelope["links"] = [None]
        elif change == "current_purpose": envelope["purpose"] = "current-child-approval"
        elif change == "approval_flag": envelope["approval_authorized"] = True
        else: envelope["links"][0]["approval_authorized"] = True
    reseal_fixture(linked["child"], mutate)
    with pytest.raises(ValueError):
        verify(linked)


@pytest.mark.parametrize("part", ["reference_path", "evidence_path"])
@pytest.mark.parametrize("missing", [False, True])
def test_corrupt_or_missing_archive_files_fail_closed(linked, part, missing):
    path = candidate_evidence_path(linked["child"].parent, linked["links"]["links"][0][part])
    if missing: path.unlink()
    else: path.write_bytes(b'{"edited": true}')
    with pytest.raises((OSError, ValueError)):
        verify(linked)


def test_child_metadata_cannot_replace_independent_registry_anchor(linked):
    original_reference = candidate_evidence_path(linked["session"].workspace,
                                                linked["links"]["links"][0]["reference_path"])
    original_reference.write_bytes(b'{"edited": true}')
    with pytest.raises(ValueError, match="journal binding"):
        verify(linked)


@pytest.mark.parametrize("change", ["model", "policy", "source", "parent", "parent_identity", "cycle"])
def test_live_parent_and_provenance_changes_rejected(linked, monkeypatch, change):
    if change == "model":
        linked["control"]["models"]["nli"]["asset_sha256"]["weights"] = "different"
    elif change == "policy":
        monkeypatch.setattr(service, "verification_policy", lambda: {"version": "changed"})
    elif change == "source":
        linked["source"].write_text("changed source", encoding="utf-8")
    elif change == "parent":
        linked["parent"].unlink()
    elif change == "parent_identity":
        reseal_fixture(linked["child"], lambda state: state["parent"].__setitem__("snapshot_id", "wrong"))
    else:
        reseal_fixture(linked["child"], lambda state: state["parent"].__setitem__("artifact_path", "validated_requirements.json"))
    with pytest.raises((OSError, ValueError)):
        verify(linked)


@pytest.mark.parametrize("relative", ["../outside.json", "candidate_evidence/../outside.json",
    "candidate_evidence/a\\b", "C:/outside.json", "candidate_evidence//outside.json"])
def test_archive_path_traversal_rejected(linked, relative):
    reseal_fixture(linked["child"], lambda state:
        state["parent_evidence_links"]["links"][0].__setitem__("reference_path", relative))
    with pytest.raises(ValueError, match="Unsafe"):
        verify(linked)


def test_archive_symlink_or_junction_escape_rejected(linked, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = linked["child"].parent / "candidate_evidence/escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt": raise
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                       capture_output=True, check=True)
    reseal_fixture(linked["child"], lambda state: state["parent_evidence_links"]["links"][0].__setitem__(
        "reference_path", "candidate_evidence/escape/reference.json"))
    with pytest.raises(ValueError, match="symlink/reparse"):
        verify(linked)


@pytest.mark.parametrize("change", ["candidate", "path"])
def test_duplicate_or_ambiguous_links_rejected(linked, change):
    def duplicate(state):
        second = copy.deepcopy(state["parent_evidence_links"]["links"][0])
        if change == "path":
            second["candidate_text"] += " "
            second["binding"]["candidate_id"] = service.stable_candidate_id(linked["rid"], second["candidate_text"])
        state["parent_evidence_links"]["links"].append(second)
    reseal_fixture(linked["child"], duplicate)
    with pytest.raises(ValueError, match="Duplicate or ambiguous"):
        verify(linked)


def test_parent_receipt_cannot_be_loaded_as_child_receipt(linked):
    link = linked["links"]["links"][0]
    with pytest.raises(ValueError, match="binding mismatch"):
        service.load_candidate_validation(candidate_evidence_path(linked["child"].parent, link["evidence_path"]),
            linked["child"], linked["source"], linked["rid"], CANDIDATE,
            expected_sha256=link["receipt_sha256"], analyser_factory=linked["factory"])


def test_child_candidate_must_match_the_linked_candidate(linked, tmp_path):
    child = make_snapshot(linked["parent"], linked["source"], tmp_path / "different/c1",
        [{"requirement_id": linked["rid"], "candidate_texts": [CANDIDATE + " "]}], linked["links"])
    archive_links(child, linked["session"].workspace, linked["links"])
    with pytest.raises(ValueError, match="Child requirement or candidate identity"):
        verify_child_evidence_links(child, linked["source"], registry_workspace=linked["session"].workspace,
                                    analyser_factory=linked["factory"])


def substitute_comparison_read(monkeypatch, target, replacement):
    """Replace owned fixture bytes only at the verifier's artifact read boundary."""
    read_bytes = Path.read_bytes
    authentic = read_bytes(target)
    reads = []

    def substituted(path):
        if path == target and sys._getframe(1).f_code.co_name == "verify_child_evidence_links":
            reads.append(path)
            target.write_bytes(replacement)
            try:
                return read_bytes(path)
            finally:
                target.write_bytes(authentic)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", substituted)
    return reads, authentic


def test_temporary_child_artifact_substitution_rejected(linked, tmp_path, monkeypatch):
    child = make_snapshot(linked["parent"], linked["source"], tmp_path / "substitution/c1",
        [{"requirement_id": linked["rid"], "candidate_texts": [CANDIDATE + " "]}], linked["links"])
    archive_links(child, linked["session"].workspace, linked["links"])
    bundle = dict(linked, child=child)
    with pytest.raises(ValueError, match="Child requirement or candidate identity"):
        verify(bundle)
    forged = json.loads(child.read_bytes())
    row = next(row for row in forged["requirements"] if row["requirement_id"] == linked["rid"])
    row["candidates"].append({"candidate_id": linked["cid"], "text": CANDIDATE})
    reads, authentic = substitute_comparison_read(monkeypatch, child, json.dumps(forged).encode())
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        verify(bundle)
    assert reads == [child]
    assert child.read_bytes() == authentic


def test_temporary_parent_artifact_substitution_rejected(linked, monkeypatch):
    child = linked["child"]
    changed = json.loads(child.read_bytes())
    row = next(row for row in changed["requirements"] if row["requirement_id"] == linked["rid"])
    row["original_text"] = "The system shall erase logs."
    child.write_bytes(json.dumps(changed).encode())
    digest = sha256(child.read_bytes())
    reseal_fixture(child, lambda state: state.__setitem__("artifact_sha256", digest))
    manifest_path = child.parent / "internal/source_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["artifact_sha256"] = digest
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    resolve_workflow_policy(VerifiedWorkflowContext(child, linked["source"]))
    with pytest.raises(ValueError, match="Child requirement or candidate identity"):
        verify(linked)
    parent = linked["parent"]
    forged = json.loads(parent.read_bytes())
    next(row for row in forged["requirements"] if row["requirement_id"] == linked["rid"])["original_text"] = "The system shall erase logs."
    reads, authentic = substitute_comparison_read(monkeypatch, parent, json.dumps(forged).encode())
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        verify(linked)
    assert reads == [parent]
    assert parent.read_bytes() == authentic


@pytest.mark.parametrize("artifact", ["child", "parent"])
@pytest.mark.parametrize("replacement", [b'{"requirements": []}', b'not JSON'])
def test_comparison_artifact_bytes_require_verified_digest(linked, monkeypatch, artifact, replacement):
    target = linked[artifact]
    reads, authentic = substitute_comparison_read(monkeypatch, target, replacement)
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        verify(linked)
    assert reads == [target]
    assert target.read_bytes() == authentic


@pytest.mark.parametrize("verdict", ["CONTRADICTED", "INCONCLUSIVE", "ERROR"])
def test_negative_or_incomplete_parent_evidence_never_authorizes_child(linked, tmp_path, verdict):
    control = linked["control"]
    if verdict == "CONTRADICTED": control["passages"] = ["The system shall not retain logs."]
    elif verdict == "INCONCLUSIVE": control["passages"] = []
    else: control["outer_error"] = True
    candidate = CANDIDATE + " "
    session = linked["session"]
    session.validate_candidate_evidence(linked["rid"], candidate, analyser_factory=linked["factory"])
    links = build_parent_evidence_links(VerifiedWorkflowContext(linked["parent"], linked["source"]),
        session.workspace, [service.stable_candidate_id(linked["rid"], candidate)], analyser_factory=linked["factory"])
    child = make_snapshot(linked["parent"], linked["source"], tmp_path / "negative/c1",
        [{"requirement_id": linked["rid"], "candidate_texts": [candidate]}], links)
    archive_links(child, session.workspace, links)
    result = verify_child_evidence_links(child, linked["source"], registry_workspace=session.workspace,
                                         analyser_factory=linked["factory"])
    assert result["links"][0]["verdict_on_parent"] == verdict
    assert not result["child_independently_validated"]
    assert not result["approval_authorized"] and not result["bdd_ready_authorized"]
    assert result["links"][0]["completion_status"] == ("incomplete" if verdict == "ERROR" else "completed")


def test_registered_parent_remains_verifiable_after_session_advanced(linked):
    from c1_requirement_quality.demo_workflow import _write
    session = linked["session"]
    actions = session.workspace / "actions/fixture.json"
    _write(actions, {"requirements": []})
    # Construct only a synthetic journal fixture using its existing event format.
    # No apply(), recover(), or production publication behavior is integrated.
    session._append("pending", operation_id="fixture", parent=str(linked["parent"]),
        parent_sha256=sha256(linked["parent"].read_bytes()), actions=str(actions),
        actions_sha256=sha256(actions.read_bytes()), out=str(linked["child"].parent.parent))
    session._append("completed", operation_id="fixture", artifact_sha256=sha256(linked["child"].read_bytes()))
    assert DemoSession(session.workspace).current == linked["child"]
    assert verify(linked)["links"][0]["verdict_on_parent"] == "SUPPORTED"
    assert linked["control"]["analyses"] == 1


def test_archive_cannot_authenticate_without_origin_registry(linked, tmp_path):
    with pytest.raises(OSError):
        verify_child_evidence_links(linked["child"], linked["source"],
            registry_workspace=tmp_path / "missing", analyser_factory=linked["factory"])


def test_same_artifact_different_clarification_parent_cannot_reuse_receipt(context, tmp_path):
    original, source, rid, _, _, factory = context
    parent = make_snapshot(original, source, tmp_path / "p/c1", [{"requirement_id": rid,
        "candidate_texts": [CANDIDATE], "clarification_questions": ["Who confirms?"],
        "clarification_answers": [{"question": "Who confirms?", "answer": "Administrator"}]}])
    session = DemoSession.create(tmp_path / "s", artifact=parent, source=source)
    session.validate_candidate_evidence(rid, CANDIDATE, analyser_factory=factory)
    links = build_parent_evidence_links(VerifiedWorkflowContext(parent, source), session.workspace,
        [service.stable_candidate_id(rid, CANDIDATE)], analyser_factory=factory)
    state = session.read()[3]
    qid = next(qid for qid, q in state["requirements"][rid]["questions"].items() if q["text"] == "Who confirms?")
    reopened = make_snapshot(parent, source, tmp_path / "r/c1",
        [{"requirement_id": rid, "question_actions": [{"question_id": qid, "status": "REOPENED"}]}])
    assert reopened.read_bytes() == parent.read_bytes()
    assert resolve_workflow_policy(VerifiedWorkflowContext(reopened, source))[3]["snapshot_id"] != state["snapshot_id"]
    child = make_snapshot(reopened, source, tmp_path / "c/c1", [], links)
    archive_links(child, session.workspace, links)
    with pytest.raises(ValueError, match="trusted registration"):
        verify_child_evidence_links(child, source, registry_workspace=session.workspace, analyser_factory=factory)


@pytest.mark.parametrize("different_source", [False, True])
def test_cross_run_or_source_links_rejected(linked, tmp_path, different_source):
    source = linked["source"]
    if different_source:
        source = tmp_path / "other.md"
        source.write_text("# Requirements\n1. The system shall retain logs.\nDifferent source facts.", encoding="utf-8")
    cli.run(source, tmp_path / "other", "RUN-20261019-120000-abcd", registry_path=tmp_path / "other-registry.json")
    parent = tmp_path / "other/c1/validated_requirements.json"
    child = make_snapshot(parent, source, tmp_path / "other-child/c1",
        [{"requirement_id": linked["rid"], "candidate_texts": [CANDIDATE]}], linked["links"])
    archive_links(child, linked["session"].workspace, linked["links"])
    with pytest.raises(ValueError, match="trusted registration"):
        verify_child_evidence_links(child, source, registry_workspace=linked["session"].workspace,
                                    analyser_factory=linked["factory"])


def test_missing_provenance_and_root_as_child_rejected(linked):
    with pytest.raises(ValueError, match="Verified workflow context"):
        build_parent_evidence_links(None, linked["session"].workspace, [linked["cid"]])
    with pytest.raises(ValueError, match="immediate parent"):
        verify_child_evidence_links(linked["parent"], linked["source"],
            registry_workspace=linked["session"].workspace, analyser_factory=linked["factory"])
    with pytest.raises(TypeError):
        verify_child_evidence_links(linked["child"], linked["source"])


def test_restart_verification_without_inference(linked):
    script = """
import json, sys
from pathlib import Path
sys.addaudithook(lambda event,args: (_ for _ in ()).throw(RuntimeError('Network forbidden'))
    if event in {'socket.connect','socket.getaddrinfo','socket.sendto'} else None)
from c1_requirement_quality.workflow_persistence import verify_child_evidence_links
from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser
class Offline(RAGGroundingAnalyser):
    def model_provenance(self): return json.loads(sys.argv[4])
    def analyse(self, text): raise AssertionError('No inference on verification')
result = verify_child_evidence_links(Path(sys.argv[1]), Path(sys.argv[2]),
    registry_workspace=Path(sys.argv[3]), analyser_factory=Offline)
assert not result['child_independently_validated'] and not result['approval_authorized']
print(result['links'][0]['verdict_on_parent'])
"""
    result = subprocess.run([sys.executable, "-B", "-c", script, str(linked["child"]), str(linked["source"]),
        str(linked["session"].workspace), json.dumps(linked["control"]["models"])],
        capture_output=True, text=True, check=True, timeout=30)
    assert result.stdout.strip() == "SUPPORTED"
    assert linked["control"]["analyses"] == 1


def test_initial_rag_publication_and_approval_remain_blocked(rag_run, tmp_path):
    policy, data, row, _, _, _, session, factory = rag_run
    candidate = row["original_text"].rstrip(".")
    session.validate_candidate_evidence(row["requirement_id"], candidate, analyser_factory=factory)
    links = build_parent_evidence_links(policy, session.workspace,
        [service.stable_candidate_id(row["requirement_id"], candidate)], analyser_factory=factory)
    assert links["purpose"] == PARENT_EVIDENCE_PURPOSE
    actions = tmp_path / "actions.json"
    actions.write_text(json.dumps({"requirements": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="integration is pending"):
        cli.refine_run(policy.input_path, policy.source, actions, tmp_path / "blocked")
    with pytest.raises(ValueError, match="integration is pending"):
        session.apply({"requirement_id": row["requirement_id"], "human_decision": "approved"}, "Reviewer", True)
    assert not (tmp_path / "blocked").exists()
    assert not list((session.workspace / "snapshots").glob("*"))
