"""Synthetic descendants audit history without enabling RAG publication."""
import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from test_candidate_validation import context
from test_grounding_policy import rag_run
from test_child_evidence_links import reseal_fixture
from c1_requirement_quality import cli
from c1_requirement_quality.demo_workflow import DemoSession
from c1_requirement_quality.rag import candidate_validation
from c1_requirement_quality.source_integrity import (
    VerifiedWorkflowContext, copy_source_bundle, resolve_workflow_policy, sha256,
    verify_source, require_refinement_grounding,
)
from c1_requirement_quality.workflow_persistence import (
    build_initial_rag_ancestry, load_state, verify_initial_rag_ancestry,
)


def synthetic_child(parent, source, target, *, ancestry=None):
    """Seal fixture-only unchanged obligations, without calling refinement APIs."""
    policy = VerifiedWorkflowContext(parent, source)
    _, _, manifest, state = resolve_workflow_policy(policy)
    child = copy.deepcopy(state)
    child.update(snapshot_id="SNAPSHOT-" + target.parent.name, round=state["round"] + 1,
                 parent={"snapshot_id": state["snapshot_id"],
                         "artifact_path": os.path.relpath(parent, target).replace("\\", "/"),
                         "artifact_sha256": manifest["artifact_sha256"],
                         "workflow_sha256": manifest["workflow_sha256"],
                         "legacy_diagnostics_sha256": state.get("legacy_diagnostics_sha256")})
    child.pop("parent_evidence_links", None)
    child.pop("operation_binding", None)
    child["initial_rag_ancestry"] = ancestry or build_initial_rag_ancestry(policy)
    target.mkdir(parents=True)
    (target / "validated_requirements.json").write_bytes(parent.read_bytes())
    copy_source_bundle(parent, target, manifest, child)
    return target / "validated_requirements.json"


@pytest.fixture
def lineage(rag_run, tmp_path):
    policy = rag_run[0]
    paths = [policy.input_path]
    for index in range(1, 4):
        paths.append(synthetic_child(paths[-1], policy.source, tmp_path / f"g{index}/c1"))
    return paths, policy.source


def rewrite(path, value):
    path.chmod(0o644)
    path.write_bytes(json.dumps(value).encode())


def test_three_generations_and_restart_are_historical_only(lineage, tmp_path):
    paths, source = lineage
    root = verify_initial_rag_ancestry(paths[0], source)["root"]
    for generation, artifact in enumerate(paths):
        result = verify_initial_rag_ancestry(artifact, source)
        assert result["generations"] == generation
        assert result["root"] == root
        assert not any(result[k] for k in ("child_independently_validated",
            "approval_authorized", "publication_authorized", "bdd_ready_authorized"))
        assert resolve_workflow_policy(VerifiedWorkflowContext(artifact, source))[0]
        if generation:
            assert not (artifact.parent / "rag_diagnostics.json").exists()
            assert not (artifact.parent / "internal/rag_provenance.json").exists()
            assert not (artifact.parent / "candidate_evidence").exists()
    session = DemoSession.create(tmp_path / "restart", artifact=paths[-1], source=source)
    assert DemoSession(session.workspace).read()[3]["round"] == 3


@pytest.mark.parametrize("part", ["artifact", "workflow", "source", "normalized", "rag", "provenance", "missing"])
def test_original_ancestor_tampering_fails_closed(lineage, part):
    paths, source = lineage
    root = paths[0]
    target = {"artifact": root, "workflow": root.parent / "internal/workflow_snapshot.json",
              "source": root.parent / "internal/source" / source.name,
              "normalized": root.parent / "internal/normalized_ingestion.json",
              "rag": root.parent / "rag_diagnostics.json",
              "provenance": root.parent / "internal/rag_provenance.json",
              "missing": root}[part]
    target.chmod(0o644)
    if part == "missing":
        target.unlink()
    else:
        target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises((ValueError, OSError)):
        verify_source(paths[-1], source)


@pytest.mark.parametrize("change", ["missing", "duplicate", "reordered", "parent", "root", "policy", "candidate_receipt"])
def test_resealed_ancestry_substitutions_rejected(lineage, change):
    paths, source = lineage
    def mutate(state):
        envelope = state["initial_rag_ancestry"]
        if change == "missing":
            state.pop("initial_rag_ancestry")
        elif change in {"duplicate", "reordered"}:
            envelope["links"] = [envelope["parent"], envelope["root"]][::(-1 if change == "reordered" else 1)]
        elif change == "policy":
            envelope["verification_policy"]["sha256"] = "0" * 64
        elif change == "candidate_receipt":
            envelope["root"] = {"receipt_sha256": "0" * 64}
        else:
            envelope[change]["workflow_sha256"] = "0" * 64
    reseal_fixture(paths[-1], mutate)
    with pytest.raises(ValueError, match="ancestry"):
        load_state(paths[-1], source)


@pytest.mark.parametrize("value", [None, [], {}, {"version": True}, "unverified"])
def test_malformed_ancestry_is_not_accepted(lineage, value):
    paths, source = lineage
    reseal_fixture(paths[-1], lambda s: s.update(initial_rag_ancestry=value))
    with pytest.raises(ValueError, match="ancestry"):
        load_state(paths[-1], source)


def test_json_boolean_cannot_substitute_for_version(lineage):
    paths, source = lineage
    reseal_fixture(paths[-1], lambda s: s["initial_rag_ancestry"].update(version=True))
    with pytest.raises(ValueError, match="ancestry"):
        load_state(paths[-1], source)


def test_same_artifact_sibling_different_workflow_cannot_replace_parent(lineage, tmp_path):
    paths, source = lineage
    sibling = synthetic_child(paths[0], source, tmp_path / "sibling/c1")
    assert sibling.read_bytes() == paths[1].read_bytes()
    assert load_state(sibling, source)[0]["snapshot_id"] != load_state(paths[1], source)[0]["snapshot_id"]
    def mutate(state):
        state["parent"]["artifact_path"] = os.path.relpath(sibling, paths[2].parent).replace("\\", "/")
    reseal_fixture(paths[2], mutate)
    with pytest.raises(ValueError, match="hash mismatch|Parent snapshot reference"):
        load_state(paths[-1], source)


@pytest.mark.parametrize("location", ["/absolute/artifact.json", "C:/external/artifact.json", "../bad\\artifact.json"])
def test_unsafe_ancestor_paths_rejected(lineage, location):
    paths, source = lineage
    reseal_fixture(paths[-1], lambda s: s["parent"].update(artifact_path=location))
    with pytest.raises(ValueError, match="path"):
        load_state(paths[-1], source)


def test_ancestor_directory_link_is_rejected(lineage, tmp_path):
    paths, source = lineage
    redirect = tmp_path / "redirect"
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(redirect), str(paths[-2].parent)],
                       capture_output=True, check=True)
    else:
        redirect.symlink_to(paths[-2].parent, target_is_directory=True)
    location = os.path.relpath(redirect / paths[-2].name, paths[-1].parent).replace("\\", "/")
    reseal_fixture(paths[-1], lambda s: s["parent"].update(artifact_path=location))
    with pytest.raises(ValueError, match="symlink/reparse"):
        load_state(paths[-1], source)


@pytest.mark.parametrize("change", ["rag_policy", "rag_ancestry_version", "root_digest"])
def test_descendant_cannot_downgrade_manifest(lineage, change):
    paths, source = lineage
    path = paths[-1].parent / "internal/source_manifest.json"
    manifest = json.loads(path.read_bytes())
    if change == "root_digest":
        manifest["rag_diagnostics_sha256"] = "0" * 64
    else:
        manifest.pop(change)
    rewrite(path, manifest)
    with pytest.raises((ValueError, OSError)):
        resolve_workflow_policy(VerifiedWorkflowContext(paths[-1], source))


def test_current_verifier_policy_change_invalidates_lineage(lineage, monkeypatch):
    paths, source = lineage
    monkeypatch.setattr(candidate_validation, "verification_policy", lambda: {"version": 99})
    with pytest.raises(ValueError, match="ancestry transition"):
        load_state(paths[-1], source)


def test_ancestor_candidate_receipt_cannot_validate_identical_descendant_artifact(lineage, rag_run, tmp_path):
    paths, source = lineage
    policy, data, row, text, _, _, _, factory = rag_run
    candidate = row["original_text"].rstrip(".")
    rid = row["requirement_id"]
    receipt_path = tmp_path / "parent-receipt.json"
    digest = candidate_validation.validate_candidate_run(policy.input_path, source, rid,
        candidate, receipt_path, analyser_factory=factory)
    assert paths[-1].read_bytes() == paths[0].read_bytes()
    with pytest.raises(ValueError, match="binding"):
        candidate_validation.load_candidate_validation(receipt_path, paths[-1], source, rid,
            candidate, expected_sha256=digest, analyser_factory=factory)
    assert not verify_initial_rag_ancestry(paths[-1], source)["candidate_evidence_verified"]


@pytest.mark.parametrize("change", ["clarification_requested", "snapshot_id"])
def test_resealed_parent_workflow_change_invalidates_descendant(lineage, change):
    paths, source = lineage
    def mutate(state):
        if change == "snapshot_id":
            state[change] = "SNAPSHOT-replaced"
        else:
            next(iter(state["requirements"].values()))[change] = True
    reseal_fixture(paths[0], mutate)
    with pytest.raises(ValueError, match="Parent snapshot reference"):
        load_state(paths[-1], source)


def test_no_session_replay_or_inference_needed_for_ancestry(lineage, monkeypatch):
    paths, source = lineage
    def forbidden(*args, **kwargs):
        raise AssertionError("No session replay or model inference allowed")
    monkeypatch.setattr(DemoSession, "__init__", forbidden)
    monkeypatch.setattr(candidate_validation.RAGGroundingAnalyser, "__init__", forbidden)
    assert verify_initial_rag_ancestry(paths[-1], source)["generations"] == 3


def test_artifact_comparisons_use_single_authenticated_read(lineage, monkeypatch):
    paths, source = lineage
    read = Path.read_bytes
    counts = dict.fromkeys(paths, 0)
    def once(path):
        if path in counts:
            counts[path] += 1
            assert counts[path] == 1, "Unverified later artifact reread"
        return read(path)
    monkeypatch.setattr(Path, "read_bytes", once)
    assert load_state(paths[-1], source)[0]["round"] == 3
    assert set(counts.values()) == {1}


def test_ancestry_work_is_explicitly_bounded(lineage, monkeypatch):
    from c1_requirement_quality import workflow_persistence
    paths, source = lineage
    monkeypatch.setattr(workflow_persistence, "MAX_SNAPSHOT_ANCESTORS", 2)
    with pytest.raises(ValueError, match="verification limit"):
        load_state(paths[-1], source)


def test_legacy_does_not_acquire_initial_rag_authority(context):
    policy = VerifiedWorkflowContext(context[0], context[1])
    assert build_initial_rag_ancestry(policy) is None
    assert not resolve_workflow_policy(policy)[0]
    with pytest.raises(ValueError, match="Initial RAG ancestry required"):
        verify_initial_rag_ancestry(policy.input_path, policy.source)


def test_initial_rag_descendants_cannot_refine_approve_or_recover(lineage, tmp_path):
    paths, source = lineage
    session = DemoSession.create(tmp_path / "blocked", artifact=paths[-1], source=source)
    data, _, manifest, _ = session.read()
    rid = data["requirements"][0]["requirement_id"]
    with pytest.raises(ValueError, match="integration is pending"):
        require_refinement_grounding(manifest)
    with pytest.raises(ValueError, match="integration is pending"):
        session.apply({"requirement_id": rid, "human_decision": "approved"}, "Reviewer", True)
    actions = tmp_path / "actions.json"
    actions.write_text('{"requirements": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="integration is pending"):
        cli.refine_run(paths[-1], source, actions, tmp_path / "forbidden")
    assert session.pending is None
    assert not (tmp_path / "forbidden").exists()


def test_unverified_staged_ancestry_is_refused(rag_run, tmp_path):
    policy, _, _, _, manifest, state, _, _ = rag_run
    target = tmp_path / "unverified/c1"
    target.mkdir(parents=True)
    (target / "validated_requirements.json").write_bytes(policy.input_path.read_bytes())
    with pytest.raises(ValueError, match="ancestry required"):
        copy_source_bundle(policy.input_path, target, manifest, state)
    assert not (target / "internal/source_manifest.json").exists()


def test_interrupted_initial_rag_descendant_adoption_stays_blocked(lineage, tmp_path):
    paths, source = lineage
    session = DemoSession.create(tmp_path / "interrupted", artifact=paths[-2], source=source)
    actions = session.workspace / "action.json"
    actions.write_bytes(b'{"requirements": []}')
    # Synthetic historical operation: actual initial-RAG apply cannot get this
    # far. Even a durable pending event cannot turn ancestry into authorization.
    session._append("pending", operation_id="interrupted", parent=str(paths[-2]),
                    parent_sha256=sha256(paths[-2].read_bytes()), actions=str(actions),
                    actions_sha256=sha256(actions.read_bytes()), out=str(paths[-1].parent.parent))
    restarted = DemoSession(session.workspace)
    assert restarted.pending is not None
    with pytest.raises(ValueError, match="integration is pending"):
        restarted.recover(True)
    assert not any(event["kind"] == "completed" for event in restarted.events)
    assert restarted.current == paths[-2]
    restarted.recover(False)
    assert DemoSession(session.workspace).pending is None


@pytest.mark.parametrize("field", ["bdd_ready", "human_decision"])
def test_resealed_descendant_cannot_claim_authorization(lineage, field):
    paths, source = lineage
    data = json.loads(paths[-1].read_bytes())
    data["requirements"][0][field] = True if field == "bdd_ready" else "approved"
    rewrite(paths[-1], data)
    workflow = paths[-1].parent / "internal/workflow_snapshot.json"
    state = json.loads(workflow.read_bytes())
    state["artifact_sha256"] = sha256(paths[-1].read_bytes())
    if field == "human_decision":
        state["requirements"][data["requirements"][0]["requirement_id"]][field] = "approved"
    rewrite(workflow, state)
    manifest_path = paths[-1].parent / "internal/source_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest.update(artifact_sha256=sha256(paths[-1].read_bytes()), workflow_sha256=sha256(workflow.read_bytes()))
    rewrite(manifest_path, manifest)
    with pytest.raises(ValueError, match="authorization remains blocked"):
        verify_source(paths[-1], source)
