"""Operation commitments and bounded replay use owned fixtures and no inference."""
import copy
import json
from pathlib import Path

import pytest

from test_candidate_validation import context
from test_child_evidence_links import CANDIDATE, linked, reseal_fixture
from c1_requirement_quality import cli
from c1_requirement_quality.demo_workflow import DemoSession
from c1_requirement_quality.source_integrity import VerifiedWorkflowContext, resolve_workflow_policy, sha256
from c1_requirement_quality.workflow_persistence import build_parent_evidence_links, candidate_evidence_path


@pytest.fixture
def interrupted(linked, monkeypatch):
    session = linked["session"]
    def stop(_):
        raise KeyboardInterrupt
    with monkeypatch.context() as patch:
        patch.setattr(session, "recover", stop)
        with pytest.raises(KeyboardInterrupt):
            session.apply({"requirement_id": linked["rid"], "candidate_texts": [CANDIDATE]},
                "reviewer", True, evidence_candidate_ids=[linked["cid"]], analyser_factory=linked["factory"])
    return dict(linked, operation=copy.deepcopy(session.pending), prepared=copy.deepcopy(session.prepared),
                published=Path(session.pending["out"]) / "c1/validated_requirements.json")


def restart(bundle):
    return DemoSession(bundle["session"].workspace, analyser_factory=bundle["factory"])


def test_restart_adopts_exact_prepared_child_without_replaying_inference(interrupted, monkeypatch):
    bundle = interrupted
    resumed = restart(bundle)
    assert resumed.current == bundle["parent"] and resumed.pending
    monkeypatch.setattr(cli, "refine_run", lambda *a, **k: pytest.fail("No refinement replay"))
    read_bytes = Path.read_bytes
    import sys
    def no_new_receipt(path):
        if path == bundle["published"] and sys._getframe(1).f_code.co_name == "recover":
            pytest.fail("Completion must retain the prepublication digest")
        return read_bytes(path)
    monkeypatch.setattr(Path, "read_bytes", no_new_receipt)
    resumed.recover(True)
    assert resumed.current == bundle["published"]
    completed = resumed.events[-1]
    assert completed["artifact_sha256"] == bundle["prepared"]["commitment"]["artifact_sha256"]
    assert completed["prepared_sha256"] == bundle["prepared"]["sha256"]
    assert restart(bundle).current == bundle["published"]
    assert restart(bundle).current == bundle["published"]
    assert bundle["control"]["analyses"] == 1
    assert all(instance.released for instance in bundle["control"]["instances"])


def test_same_parent_sibling_with_identical_artifact_bytes_is_rejected(interrupted, tmp_path):
    b = interrupted
    sibling = b["published"].parent.parent.parent / "sibling"
    cli.refine_run(b["parent"], b["source"], Path(b["operation"]["actions"]), sibling,
        evidence_registry=b["session"].workspace, evidence_candidate_ids=[b["cid"]],
        analyser_factory=b["factory"])
    original = b["published"].read_bytes()
    assert (sibling / "c1/validated_requirements.json").read_bytes() == original
    for path in (sibling / "c1").rglob("*"):
        if path.is_file():
            target = b["published"].parent / path.relative_to(sibling / "c1")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.chmod(0o644)
            target.write_bytes(path.read_bytes())
    # This is a valid, self-consistent sibling, not merely corrupt JSON.
    resolve_workflow_policy(VerifiedWorkflowContext(b["published"], b["source"]))
    resumed = restart(b)
    with pytest.raises(ValueError, match="commitment mismatch"):
        resumed.recover(True)
    assert resumed.current == b["parent"] and resumed.pending


@pytest.mark.parametrize("part", ["artifact", "workflow", "manifest", "diagnostics", "reference", "receipt", "actions"])
def test_recovery_rejects_tampered_published_bundle(interrupted, part):
    b = interrupted
    child = b["published"]
    if part == "workflow":
        reseal_fixture(child, lambda state: state.__setitem__("unexpected", True))
    elif part == "manifest":
        path = child.parent / "internal/source_manifest.json"
        data = json.loads(path.read_bytes())
        data["unexpected"] = True
        path.chmod(0o644)
        path.write_text(json.dumps(data), encoding="utf-8")
    else:
        if part in {"receipt", "reference"}:
            key = "evidence_path" if part == "receipt" else "reference_path"
            path = candidate_evidence_path(child.parent, b["links"]["links"][0][key])
        elif part == "actions":
            path = Path(b["operation"]["actions"])
        else:
            path = child if part == "artifact" else child.parent / "refinement_diagnostics.json"
        path.chmod(0o644)
        path.write_bytes(path.read_bytes() + b" ")
    resumed = restart(b)
    with pytest.raises((ValueError, OSError)):
        resumed.recover(True)
    assert resumed.current == b["parent"] and resumed.pending


@pytest.mark.parametrize("field", ["parent_identity", "evidence_candidate_ids", "registry_anchor", "child_snapshot_id"])
def test_direct_internal_call_cannot_supply_forged_pending_context(interrupted, field):
    resumed = restart(interrupted)
    forged = copy.deepcopy(resumed.pending)
    forged[field] = "forged"
    with pytest.raises(ValueError, match="durable journal"):
        resumed._check_child(forged)


def test_direct_cli_cannot_forge_a_pending_operation(interrupted, tmp_path):
    b = interrupted
    forged = copy.deepcopy(b["operation"])
    forged["out"] = str(tmp_path / "forged")
    with pytest.raises(ValueError, match="operation provenance mismatch"):
        cli.refine_run(b["parent"], b["source"], Path(forged["actions"]), Path(forged["out"]),
            evidence_registry=b["session"].workspace, evidence_candidate_ids=[b["cid"]],
            analyser_factory=b["factory"], _operation=forged, _prepared=lambda _: {})
    assert not Path(forged["out"]).exists()


def test_operation_bound_child_cannot_downgrade_to_legacy_recovery(interrupted):
    resumed = restart(interrupted)
    forged = copy.deepcopy(resumed.pending)
    forged.pop("operation_version")
    with pytest.raises(ValueError, match="durable journal"):
        resumed._check_child(forged)


def test_forged_legacy_record_cannot_adopt_identical_sibling(interrupted):
    b = interrupted
    sibling = b["published"].parent.parent.parent / "legacy-sibling"
    cli.refine_run(b["parent"], b["source"], Path(b["operation"]["actions"]), sibling)
    assert (sibling / "c1/validated_requirements.json").read_bytes() == b["published"].read_bytes()
    resumed = restart(b)
    before = {p: p.read_bytes() for p in (resumed.workspace / "events").glob("*.json")}
    forged = copy.deepcopy(resumed.pending)
    forged.pop("operation_version")
    forged["out"] = str(sibling)
    with pytest.raises(ValueError, match="durable journal"):
        resumed._check_child(forged)
    resumed.pending = forged
    with pytest.raises(ValueError, match="durable journal"):
        resumed.recover(True)
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert len(list((resumed.workspace / "events").glob("*.json"))) == len(before)
    assert restart(b).pending == b["operation"]


def test_retry_after_durable_completion_is_idempotent(interrupted, monkeypatch):
    b = interrupted
    resumed = restart(b)
    append = resumed._append
    def interrupt(kind, **values):
        append(kind, **values)
        if kind == "completed":
            raise KeyboardInterrupt
    with monkeypatch.context() as patch:
        patch.setattr(resumed, "_append", interrupt)
        with pytest.raises(KeyboardInterrupt):
            resumed.recover(True)
    assert restart(b).current == b["published"]
    resumed.recover(True)
    assert len([e for e in resumed.events if e["kind"] == "completed"]) == 1
    assert restart(b).current == b["published"]
    assert b["control"]["analyses"] == 1


@pytest.mark.parametrize("terminal, retry", [("completed", True), ("completed", False),
                                            ("cancelled", False), ("cancelled", True)])
def test_terminal_write_before_memory_update_cannot_append_duplicate(interrupted, monkeypatch, terminal, retry):
    from c1_requirement_quality import demo_workflow
    b = interrupted
    resumed = restart(b)
    write = demo_workflow._write
    def interrupt(path, value):
        write(path, value)
        if isinstance(value, dict) and value.get("kind") == terminal:
            raise KeyboardInterrupt
    with monkeypatch.context() as patch:
        patch.setattr(demo_workflow, "_write", interrupt)
        with pytest.raises(KeyboardInterrupt):
            resumed.recover(terminal == "completed")
    before = {p: p.read_bytes() for p in (resumed.workspace / "events").glob("*.json")}
    if retry == (terminal == "completed"):
        resumed.recover(retry)
    else:
        with pytest.raises(ValueError, match="conflicting durable terminal"):
            resumed.recover(retry)
    verified = restart(b)
    assert len([e for e in verified.events if e["kind"] in {"completed", "cancelled"}]) == 1
    assert len(verified.events) == len(before)
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert verified.current == (b["published"] if terminal == "completed" else b["parent"])
    assert b["control"]["analyses"] == 1


def test_stale_second_object_cannot_reverse_completed_operation(interrupted):
    first, second = restart(interrupted), restart(interrupted)
    first.recover(True)
    with pytest.raises(ValueError, match="conflicting durable terminal"):
        second.recover(False)
    assert len([e for e in restart(interrupted).events if e["kind"] == "completed"]) == 1


@pytest.mark.parametrize("change", ["model", "policy"])
def test_recovery_rechecks_current_model_and_verification_policy(interrupted, monkeypatch, change):
    b = interrupted
    if change == "model":
        b["control"]["models"]["nli"]["asset_sha256"]["weights"] = "different"
    else:
        from c1_requirement_quality.rag import candidate_validation
        monkeypatch.setattr(candidate_validation, "verification_policy", lambda: {"version": "changed"})
    resumed = restart(b)
    with pytest.raises(ValueError):
        resumed.recover(True)
    assert resumed.current == b["parent"]


@pytest.mark.parametrize("change", ["missing", "corrupt"])
def test_missing_or_corrupt_prepared_record_cannot_authorize_recovery(interrupted, change):
    b = interrupted
    path = b["session"].workspace / "events" / f'{b["prepared"]["sequence"]:06}.json'
    if change == "corrupt":
        path.write_bytes(b'{"truncated":')
        with pytest.raises(ValueError):
            restart(b)
    else:
        path.rename(path.with_suffix(".retained"))
        resumed = restart(b)
        with pytest.raises(ValueError, match="prepared child receipt"):
            resumed.recover(True)


def test_unjournalled_prepared_commitment_is_not_trusted(interrupted):
    resumed = restart(interrupted)
    resumed.prepared = copy.deepcopy(resumed.prepared)
    resumed.prepared["commitment"]["artifact_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="independently journal-bound"):
        resumed.recover(True)


def test_conflicting_prepared_publication_cannot_overwrite_journal(interrupted):
    resumed = restart(interrupted)
    original = resumed.events.pop()
    path = resumed.workspace / "events" / f'{original["sequence"]:06}.json'
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        resumed._append("prepared", operation_id=resumed.pending["operation_id"],
            pending_sha256=resumed.pending["sha256"], commitment={"forged": True})
    assert path.read_bytes() == before


def test_bounded_registry_replay_stops_before_child_completion(interrupted):
    b = interrupted
    session = restart(b)
    session.recover(True)
    # Later child damage must not make the authentic historical registry prefix
    # recurse into the child it is being used to verify.
    b["published"].write_bytes(b"changed child")
    anchor = b["operation"]["registry_anchor"]
    links = build_parent_evidence_links(VerifiedWorkflowContext(b["parent"], b["source"]),
        session.workspace, [b["cid"]], analyser_factory=b["factory"], registry_anchor=anchor)
    assert links == b["links"]
    with pytest.raises(ValueError):
        restart(b)


@pytest.mark.parametrize("change", ["digest", "missing_event", "malformed"])
def test_registry_prefix_requires_exact_journal_anchor(interrupted, change):
    anchor = copy.deepcopy(interrupted["operation"]["registry_anchor"])
    if change == "digest":
        anchor["sha256"] = "0" * 64
    elif change == "missing_event":
        anchor["sequence"] = 10000
    else:
        anchor["sequence"] = True
    with pytest.raises(ValueError):
        DemoSession(interrupted["session"].workspace, _registry_anchor=anchor,
                    analyser_factory=interrupted["factory"])


def test_registry_prefix_is_read_only(interrupted):
    prefix = DemoSession(interrupted["session"].workspace,
        _registry_anchor=interrupted["operation"]["registry_anchor"], analyser_factory=interrupted["factory"])
    with pytest.raises(ValueError, match="read-only"):
        prefix._append("review")
    with pytest.raises(ValueError, match="read-only"):
        prefix.recover(True)
    with pytest.raises(ValueError, match="read-only"):
        prefix.validate_candidate_evidence(interrupted["rid"], CANDIDATE)


def test_multiple_linked_operations_replay_with_decreasing_registry_prefixes(interrupted):
    b = interrupted
    session = restart(b)
    session.recover(True)
    candidate = CANDIDATE + " "
    session.validate_candidate_evidence(b["rid"], candidate, analyser_factory=b["factory"])
    from c1_requirement_quality.refinement import stable_candidate_id
    session.apply({"requirement_id": b["rid"], "candidate_texts": [candidate]}, "reviewer", True,
        evidence_candidate_ids=[stable_candidate_id(b["rid"], candidate)], analyser_factory=b["factory"])
    assert restart(b).current == session.current
    assert b["control"]["analyses"] == 2


@pytest.mark.parametrize("boundary", ["staging", "rename"])
def test_interruption_before_publication_cannot_adopt_or_replay(linked, monkeypatch, boundary):
    session = linked["session"]
    if boundary == "staging":
        monkeypatch.setattr(cli, "copy_source_bundle", lambda *a, **k: (_ for _ in ()).throw(OSError("interrupted")))
    else:
        rename = Path.rename
        def interrupt(path, target):
            if ".c1-refine-pending-" in path.name:
                raise OSError("interrupted")
            return rename(path, target)
        monkeypatch.setattr(Path, "rename", interrupt)
    with pytest.raises(OSError, match="interrupted"):
        session.apply({"requirement_id": linked["rid"], "candidate_texts": [CANDIDATE]}, "reviewer", True,
            evidence_candidate_ids=[linked["cid"]], analyser_factory=linked["factory"])
    resumed = restart(linked)
    assert (resumed.prepared is not None) == (boundary == "rename")
    with pytest.raises((ValueError, OSError)):
        resumed.recover(True)
    assert resumed.current == linked["parent"]
    resumed.recover(False)
    assert restart(linked).pending is None
    assert list((session.workspace / "snapshots").glob(".c1-refine-pending-*"))


def test_prepared_callback_cannot_change_staging_before_rename(linked, monkeypatch):
    session = linked["session"]
    append = session._append
    def tamper(kind, **values):
        append(kind, **values)
        if kind == "prepared":
            child = next((session.workspace / "snapshots").glob(".c1-refine-pending-*/c1/validated_requirements.json"))
            child.write_bytes(b"changed after preparation")
    monkeypatch.setattr(session, "_append", tamper)
    with pytest.raises(ValueError):
        session.apply({"requirement_id": linked["rid"], "candidate_texts": [CANDIDATE]}, "reviewer", True,
            evidence_candidate_ids=[linked["cid"]], analyser_factory=linked["factory"])
    assert not Path(session.pending["out"]).exists()
    assert session.prepared is not None
