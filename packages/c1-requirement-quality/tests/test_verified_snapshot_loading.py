"""Permanent reproductions of public-loader and ancestry downgrade attacks."""
import copy
import json
from pathlib import Path

import pytest

from test_candidate_validation import context
from test_grounding_policy import rag_run
from test_initial_rag_ancestry import lineage
from test_child_evidence_links import linked
from c1_requirement_quality.demo_workflow import DemoSession
from c1_requirement_quality.source_integrity import (
    VerifiedWorkflowContext, verify_source, resolve_workflow_policy,
    require_refinement_grounding,
)


@pytest.mark.parametrize("corrupt_root", [False, True])
def test_both_removed_markers_cannot_bypass_public_verification(lineage, corrupt_root):
    paths, source = lineage
    path = paths[-1].parent / "internal/source_manifest.json"
    manifest = json.loads(path.read_bytes())
    for key in ("rag_policy", "rag_ancestry_version"):
        manifest.pop(key)
    path.chmod(0o644)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    if corrupt_root:
        paths[0].chmod(0o644)
        paths[0].write_bytes(paths[0].read_bytes() + b" ")
    with pytest.raises(ValueError):
        _, accepted = verify_source(paths[-1], source)
        require_refinement_grounding(accepted)


def test_root_provenance_cannot_be_downgraded_to_optional_diagnostics(rag_run):
    policy = rag_run[0]
    path = policy.input_path.parent / "internal/source_manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest.pop("rag_policy")
    path.chmod(0o644)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="without its mandatory manifest policy"):
        _, accepted = verify_source(policy.input_path, policy.source)
        require_refinement_grounding(accepted)


def substitute_text(monkeypatch, artifact, forged):
    """Inject only the formerly unauthenticated read, leaving sealed bytes intact."""
    read = Path.read_text
    def replace(path, *args, **kwargs):
        if path == artifact:
            return json.dumps(forged)
        return read(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", replace)


def test_policy_resolver_rejects_forged_original_text_read(lineage, monkeypatch):
    paths, source = lineage
    forged = json.loads(paths[-1].read_bytes())
    forged["requirements"][0]["original_text"] = "The system shall erase audit logs."
    substitute_text(monkeypatch, paths[-1], forged)
    with pytest.raises(ValueError, match="artifact mismatch"):
        resolve_workflow_policy(VerifiedWorkflowContext(paths[-1], source), artifact=forged)


def test_policy_resolver_rejects_forged_candidate_text_read(linked, monkeypatch):
    artifact = linked["child"]
    forged = json.loads(artifact.read_bytes())
    forged["requirements"][0]["candidates"][0]["text"] = "The system shall erase audit logs."
    substitute_text(monkeypatch, artifact, forged)
    with pytest.raises(ValueError, match="artifact mismatch"):
        resolve_workflow_policy(VerifiedWorkflowContext(artifact, linked["source"]), artifact=forged)


@pytest.mark.parametrize("field", ["original_text", "candidate_text"])
def test_session_returns_only_authenticated_display_data(linked, tmp_path, monkeypatch, field):
    artifact = linked["child"]
    session = DemoSession.create(tmp_path / "display", artifact=artifact, source=linked["source"])
    authentic = json.loads(artifact.read_bytes())
    forged = copy.deepcopy(authentic)
    row = forged["requirements"][0]
    if field == "original_text":
        row[field] = "The system shall erase audit logs."
    else:
        row["candidates"][0]["text"] = "The system shall erase audit logs."
    substitute_text(monkeypatch, artifact, forged)
    # Eliminating the vulnerable read is also secure: the unconsumed injected
    # text must never appear alongside an authenticated workflow state.
    assert session.read()[0] == authentic


@pytest.mark.parametrize("loader", ["policy", "session", "create"])
def test_substituted_authenticated_byte_read_fails_closed(lineage, tmp_path, monkeypatch, loader):
    paths, source = lineage
    artifact = paths[-1]
    session = DemoSession.create(tmp_path / "bytes", artifact=artifact, source=source)
    raw = Path.read_bytes
    forged = json.loads(raw(artifact))
    forged["requirements"][0]["original_text"] = "The system shall erase audit logs."
    hits = []
    def replace(path):
        if path == artifact:
            hits.append(path)
            return json.dumps(forged).encode()
        return raw(path)
    monkeypatch.setattr(Path, "read_bytes", replace)
    with pytest.raises(ValueError):
        if loader == "policy":
            resolve_workflow_policy(VerifiedWorkflowContext(artifact, source))
        elif loader == "session":
            session.read()
        else:
            DemoSession.create(tmp_path / "new-bytes", artifact=artifact, source=source)
    assert hits


def test_legacy_and_non_rag_public_verification_remain_supported(context, verified_legacy):
    from test_refinement import _artifact
    for policy in (VerifiedWorkflowContext(context[0], context[1]),
                   verified_legacy(_artifact("The system shall allow login."),
                                   "The system shall allow login.")):
        assert verify_source(policy.input_path, policy.source)[0]
        assert not resolve_workflow_policy(policy)[0]


def test_forged_caller_object_rejected_without_any_read_substitution(lineage):
    paths, source = lineage
    forged = json.loads(paths[-1].read_bytes())
    forged["requirements"][0]["original_text"] = "The system shall erase audit logs."
    with pytest.raises(ValueError, match="artifact mismatch"):
        resolve_workflow_policy(VerifiedWorkflowContext(paths[-1], source), artifact=forged)


@pytest.mark.parametrize("part", ["artifact", "workflow", "manifest", "source"])
def test_mutation_between_local_verification_and_ancestry_is_rejected(lineage, monkeypatch, part):
    from c1_requirement_quality import source_integrity
    paths, source = lineage
    artifact = paths[-1]
    target = {"artifact": artifact, "source": source,
              "workflow": artifact.parent / "internal/workflow_snapshot.json",
              "manifest": artifact.parent / "internal/source_manifest.json"}[part]
    local = source_integrity._verify_source_local
    changed = []
    def mutate(path, supplied):
        result = local(path, supplied)
        if path == artifact and not changed:
            raw = target.read_bytes()
            target.chmod(0o644)
            if part == "manifest":
                metadata = json.loads(raw)
                metadata["source_location"] = "changed during verification"
                raw = json.dumps(metadata).encode()
            else:
                raw += b" "
            target.write_bytes(raw)
            changed.append(part)
        return result
    monkeypatch.setattr(source_integrity, "_verify_source_local", mutate)
    with pytest.raises(ValueError):
        verify_source(artifact, source)
    assert changed == [part]


def test_public_loaders_use_one_iterative_ancestry_walk(lineage, tmp_path, monkeypatch):
    from c1_requirement_quality import workflow_persistence
    paths, source = lineage
    artifact = paths[-1]
    session = DemoSession.create(tmp_path / "one-walk", artifact=artifact, source=source)
    load = workflow_persistence.load_state
    calls = []
    def counted(*args, **kwargs):
        calls.append(args[0])
        return load(*args, **kwargs)
    monkeypatch.setattr(workflow_persistence, "load_state", counted)
    monkeypatch.setattr(DemoSession, "__init__", lambda *a, **k: pytest.fail("Recursive session construction"))
    for loader in (lambda: verify_source(artifact, source),
                   lambda: resolve_workflow_policy(VerifiedWorkflowContext(artifact, source)),
                   session.read):
        calls.clear()
        loader()
        assert calls == [artifact]
