"""Owned staging fixtures exercise exact-byte archives without model inference."""
import json
import os
from pathlib import Path

import pytest

from test_candidate_validation import context
from test_child_evidence_links import CANDIDATE, linked, reseal_fixture
from test_grounding_policy import rag_run
from c1_requirement_quality import cli
from c1_requirement_quality.source_integrity import VerifiedWorkflowContext, resolve_workflow_policy, sha256
from c1_requirement_quality.workflow_persistence import (
    archive_parent_evidence_links, candidate_evidence_path, verify_child_evidence_links,
)


def inputs(bundle, tmp_path):
    actions = tmp_path / "actions.json"
    actions.write_text(json.dumps({"requirements": [{"requirement_id": bundle["rid"],
        "candidate_texts": [CANDIDATE]}]}), encoding="utf-8")
    return actions, tmp_path / "published"


def publish(bundle, actions, out):
    cli.refine_run(bundle["parent"], bundle["source"], actions, out,
        evidence_registry=bundle["session"].workspace, evidence_candidate_ids=[bundle["cid"]],
        analyser_factory=bundle["factory"])


def test_archive_and_permitted_legacy_publication_preserve_parent_bytes(linked, tmp_path):
    actions, out = inputs(linked, tmp_path)
    publish(linked, actions, out)
    child = out / "c1/validated_requirements.json"
    result = verify_child_evidence_links(child, linked["source"],
        registry_workspace=linked["session"].workspace, analyser_factory=linked["factory"])
    for key in ("reference_path", "evidence_path"):
        relative = linked["links"]["links"][0][key]
        assert candidate_evidence_path(child.parent, relative).read_bytes() == candidate_evidence_path(
            linked["session"].workspace, relative).read_bytes()
    record = json.loads(candidate_evidence_path(child.parent, linked["links"]["links"][0]["evidence_path"]).read_bytes())
    assert record["binding"]["parent_artifact_sha256"] == sha256(linked["parent"].read_bytes())
    assert record["binding"]["parent_artifact_sha256"] != sha256(child.read_bytes())
    assert not any(result[key] for key in ("child_independently_validated", "approval_authorized",
                                          "publication_authorized", "bdd_ready_authorized"))
    assert linked["control"]["analyses"] == 1


@pytest.mark.parametrize("selection", [[], ["wrong"], ["duplicate", "duplicate"]])
def test_archive_rejects_unregistered_or_ambiguous_selection(linked, tmp_path, selection):
    target = tmp_path / "stage"
    target.mkdir()
    with pytest.raises(ValueError):
        archive_parent_evidence_links(VerifiedWorkflowContext(linked["parent"], linked["source"]),
            linked["session"].workspace, target, selection, analyser_factory=linked["factory"])
    assert not list(target.iterdir())


@pytest.mark.parametrize("key", ["reference_path", "evidence_path"])
def test_archive_rejects_changed_bytes_at_copy_boundary(linked, tmp_path, monkeypatch, key):
    target = tmp_path / "stage"
    target.mkdir()
    origin = candidate_evidence_path(linked["session"].workspace, linked["links"]["links"][0][key])
    read_bytes = Path.read_bytes
    import sys
    def changed(path):
        if path == origin and sys._getframe(1).f_code.co_name == "archive_parent_evidence_links":
            return b'{"substituted": true}'
        return read_bytes(path)
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError, match="changed before archiving"):
        archive_parent_evidence_links(VerifiedWorkflowContext(linked["parent"], linked["source"]),
            linked["session"].workspace, target, [linked["cid"]], analyser_factory=linked["factory"])
    assert not list(target.iterdir())


def test_archive_never_overwrites_existing_files(linked, tmp_path):
    target = tmp_path / "stage"
    target.mkdir()
    relative = linked["links"]["links"][0]["reference_path"]
    existing = candidate_evidence_path(target, relative)
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"retained")
    with pytest.raises(FileExistsError):
        archive_parent_evidence_links(VerifiedWorkflowContext(linked["parent"], linked["source"]),
            linked["session"].workspace, target, [linked["cid"]], analyser_factory=linked["factory"])
    assert existing.read_bytes() == b"retained"


def test_direct_archive_api_refuses_sealed_child(linked):
    before = {p: p.read_bytes() for p in linked["child"].parent.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="precede workflow sealing"):
        archive_parent_evidence_links(VerifiedWorkflowContext(linked["parent"], linked["source"]),
            linked["session"].workspace, linked["child"].parent, [linked["cid"]],
            analyser_factory=linked["factory"])
    assert all(p.read_bytes() == raw for p, raw in before.items())


def test_archive_rejects_symlink_or_junction_destination(linked, tmp_path):
    import os
    import subprocess
    target = tmp_path / "stage"
    outside = tmp_path / "outside"
    target.mkdir()
    outside.mkdir()
    escape = target / "candidate_evidence"
    try:
        escape.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        subprocess.run(["cmd", "/c", "mklink", "/J", str(escape), str(outside)],
                       capture_output=True, check=True)
    with pytest.raises(ValueError, match="symlink/reparse"):
        archive_parent_evidence_links(VerifiedWorkflowContext(linked["parent"], linked["source"]),
            linked["session"].workspace, target, [linked["cid"]], analyser_factory=linked["factory"])
    assert not list(outside.iterdir())


def test_junction_inserted_at_archive_creation_cannot_redirect_write(linked, tmp_path, monkeypatch):
    import os
    import subprocess
    from c1_requirement_quality import workflow_persistence as persistence
    stage, outside = tmp_path / "stage", tmp_path / "outside"
    stage.mkdir()
    outside.mkdir()
    sentinel = outside / "existing.txt"
    sentinel.write_bytes(b"unchanged")
    relative = linked["links"]["links"][0]["reference_path"]
    slot = stage / Path(relative).parent
    slot.mkdir(parents=True)
    write = persistence._write_evidence_archive
    injected = []
    def redirect(root, relative, raw):
        if not injected:
            retained = slot.with_name(slot.name + ".retained")
            assert slot.resolve().is_relative_to(tmp_path.resolve())
            assert retained.resolve().is_relative_to(tmp_path.resolve())
            slot.rename(retained)
            if os.name == "nt":
                subprocess.run(["cmd", "/c", "mklink", "/J", str(slot), str(outside)],
                               capture_output=True, check=True)
                assert slot.is_junction()
            else:
                slot.symlink_to(outside, target_is_directory=True)
            injected.append(slot)
        write(root, relative, raw)
    monkeypatch.setattr(persistence, "_write_evidence_archive", redirect)
    with pytest.raises((ValueError, OSError)):
        archive_parent_evidence_links(VerifiedWorkflowContext(linked["parent"], linked["source"]),
            linked["session"].workspace, stage, [linked["cid"]], analyser_factory=linked["factory"])
    assert injected
    assert {p.name for p in outside.iterdir()} == {sentinel.name}
    assert sentinel.read_bytes() == b"unchanged"


@pytest.mark.skipif(os.name != "nt", reason="Windows native directory sharing semantics")
def test_windows_directory_handles_block_replacement_at_native_create(linked, tmp_path, monkeypatch):
    import ctypes
    from c1_requirement_quality import workflow_persistence as persistence
    stage, outside = tmp_path / "stage", tmp_path / "outside"
    stage.mkdir()
    outside.mkdir()
    slot = stage / Path(linked["links"]["links"][0]["reference_path"]).parent
    retained = slot.with_name(slot.name + ".retained")
    load = ctypes.WinDLL
    attempted = []
    class NativeProxy:
        def __init__(self, library):
            self.library = library
            actual = library.NtCreateFile
            def create(*args):
                actual.argtypes, actual.restype = create.argtypes, create.restype
                if not args[8] & 1:
                    attempted.append(True)
                    assert slot.resolve().is_relative_to(tmp_path.resolve())
                    assert retained.resolve().is_relative_to(tmp_path.resolve())
                    # A junction swap needs this rename/delete first. The real
                    # open directory handles must prevent it at the syscall boundary.
                    with pytest.raises(OSError):
                        slot.rename(retained)
                    raise ValueError("Native create interruption after blocked directory replacement")
                return actual(*args)
            self.NtCreateFile = create
        def __getattr__(self, name):
            return getattr(self.library, name)
    def library(name, *args, **kwargs):
        result = load(name, *args, **kwargs)
        return NativeProxy(result) if name == "ntdll" else result
    with monkeypatch.context() as patch:
        patch.setattr(ctypes, "WinDLL", library)
        with pytest.raises(ValueError, match="blocked directory replacement"):
            archive_parent_evidence_links(VerifiedWorkflowContext(linked["parent"], linked["source"]),
                linked["session"].workspace, stage, [linked["cid"]], analyser_factory=linked["factory"])
    assert attempted and not retained.exists() and not list(outside.iterdir())
    # All pinned handles were released on the exception path; retry can create
    # the still-absent files and retains the same verified parent bindings.
    assert archive_parent_evidence_links(VerifiedWorkflowContext(linked["parent"], linked["source"]),
        linked["session"].workspace, stage, [linked["cid"]], analyser_factory=linked["factory"]) == linked["links"]


def test_interrupted_archive_retains_untrusted_staging_and_does_not_publish(linked, tmp_path, monkeypatch):
    from c1_requirement_quality import workflow_persistence as persistence
    actions, out = inputs(linked, tmp_path)
    write = persistence._write_evidence_archive
    calls = []
    def interrupted(root, relative, raw):
        calls.append(root / relative)
        if len(calls) == 2:
            raise OSError("archive interrupted")
        write(root, relative, raw)
    monkeypatch.setattr(persistence, "_write_evidence_archive", interrupted)
    with pytest.raises(OSError, match="archive interrupted"):
        publish(linked, actions, out)
    assert not out.exists()
    assert calls[0].is_file() and not calls[1].exists()
    assert not list(calls[0].parents[1].glob("internal/source_manifest.json"))


@pytest.mark.parametrize("tamper", ["workflow", "sibling", "manifest", "receipt", "reference", "actions", "artifact"])
def test_staging_tampering_never_publishes(linked, tmp_path, monkeypatch, tamper):
    actions, out = inputs(linked, tmp_path)
    copy_bundle = cli.copy_source_bundle
    def corrupt(parent, target, manifest, state):
        copy_bundle(parent, target, manifest, state)
        if tamper == "workflow":
            reseal_fixture(target / "validated_requirements.json", lambda s: s.__setitem__("unexpected", True))
        elif tamper == "sibling":
            def sibling(state):
                previous = state["snapshot_id"]
                state["snapshot_id"] = "SNAPSHOT-other-child"
                for event in state["events"]:
                    if event["snapshot_id"] == previous:
                        event["snapshot_id"] = state["snapshot_id"]
            reseal_fixture(target / "validated_requirements.json", sibling)
        elif tamper in {"reference", "receipt"}:
            key = "reference_path" if tamper == "reference" else "evidence_path"
            candidate_evidence_path(target, state["parent_evidence_links"]["links"][0][key]).write_bytes(b"changed")
        elif tamper == "actions":
            actions.write_text('{"requirements": []}', encoding="utf-8")
        else:
            path = target / ("internal/source_manifest.json" if tamper == "manifest" else "validated_requirements.json")
            path.chmod(0o644)
            path.write_bytes(b"{}")
    monkeypatch.setattr(cli, "copy_source_bundle", corrupt)
    with pytest.raises((ValueError, KeyError)):
        publish(linked, actions, out)
    assert not out.exists()
    assert list(tmp_path.glob(".c1-refine-pending-*"))


def test_linked_child_recovery_is_explicitly_blocked_until_operation_binding(linked, tmp_path):
    actions, out = inputs(linked, tmp_path)
    publish(linked, actions, out)
    operation = {"parent": str(linked["parent"]), "parent_sha256": sha256(linked["parent"].read_bytes()),
        "actions": str(actions), "actions_sha256": sha256(actions.read_bytes()), "out": str(out)}
    session = linked["session"]
    session._append("pending", operation_id="unbound", **operation)
    resumed = type(session)(session.workspace)
    with pytest.raises(ValueError, match="operation-bound staging"):
        resumed.recover(True)
    assert resumed.current == linked["parent"] and resumed.pending is not None
    # The original published child stays auditable without inference or adoption.
    assert verify_child_evidence_links(out / "c1/validated_requirements.json", linked["source"],
        registry_workspace=linked["session"].workspace, analyser_factory=linked["factory"])["links"]


def test_grandchild_does_not_inherit_immediate_parent_links(linked, tmp_path):
    actions, out = inputs(linked, tmp_path)
    publish(linked, actions, out)
    grandchild = tmp_path / "grandchild"
    cli.refine_run(out / "c1/validated_requirements.json", linked["source"], actions, grandchild)
    state = resolve_workflow_policy(VerifiedWorkflowContext(
        grandchild / "c1/validated_requirements.json", linked["source"]))[3]
    assert "parent_evidence_links" not in state
    assert resolve_workflow_policy(VerifiedWorkflowContext(out / "c1/validated_requirements.json",
        linked["source"]))[3]["parent_evidence_links"]


@pytest.mark.parametrize("after_rename", [False, True])
def test_interrupted_rename_does_not_promote_recovery_trust(linked, tmp_path, monkeypatch, after_rename):
    actions, out = inputs(linked, tmp_path)
    rename = Path.rename
    def interrupted(path, destination):
        if destination == out:
            if after_rename:
                rename(path, destination)
            raise OSError("rename interrupted")
        return rename(path, destination)
    monkeypatch.setattr(Path, "rename", interrupted)
    with pytest.raises(OSError, match="rename interrupted"):
        publish(linked, actions, out)
    assert out.exists() == after_rename
    assert bool(list(tmp_path.glob(".c1-refine-pending-*"))) != after_rename
    if after_rename:
        session = linked["session"]
        session._append("pending", operation_id="interrupted", parent=str(linked["parent"]),
            parent_sha256=sha256(linked["parent"].read_bytes()), actions=str(actions),
            actions_sha256=sha256(actions.read_bytes()), out=str(out))
        resumed = type(session)(session.workspace)
        with pytest.raises(ValueError, match="operation-bound staging"):
            resumed.recover(True)
        assert resumed.current == linked["parent"] and resumed.pending is not None
        resumed.recover(False)
        assert type(session)(session.workspace).pending is None
        assert out.exists()


def test_selected_receipt_must_identify_candidate_in_staged_child(linked, tmp_path):
    actions, out = inputs(linked, tmp_path)
    actions.write_text('{"requirements": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="Child requirement or candidate identity"):
        publish(linked, actions, out)
    assert not out.exists()


def test_selected_candidate_cannot_use_another_candidates_receipt(linked, tmp_path):
    actions, out = inputs(linked, tmp_path)
    actions.write_text(json.dumps({"requirements": [{"requirement_id": linked["rid"],
        "candidate_texts": [CANDIDATE, CANDIDATE + " "],
        "selected_candidate_text": CANDIDATE + " "}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Selected candidate lacks selected parent evidence"):
        publish(linked, actions, out)
    assert not out.exists()


def test_initial_rag_guard_precedes_archiving(rag_run, tmp_path):
    policy, _, row, _, _, _, session, factory = rag_run
    actions = tmp_path / "actions.json"
    actions.write_text('{"requirements": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="integration is pending"):
        cli.refine_run(policy.input_path, policy.source, actions, tmp_path / "blocked",
            evidence_registry=session.workspace, evidence_candidate_ids=["any"], analyser_factory=factory)
    assert not list(tmp_path.glob(".c1-refine-pending-*"))


def test_evidence_arguments_cannot_be_partially_supplied(linked, tmp_path):
    actions, out = inputs(linked, tmp_path)
    with pytest.raises(ValueError, match="both registry and candidate"):
        cli.refine_run(linked["parent"], linked["source"], actions, out,
                       evidence_candidate_ids=[linked["cid"]])
    assert not out.exists()
