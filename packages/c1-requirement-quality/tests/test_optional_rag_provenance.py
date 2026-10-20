"""Optional diagnostics confer no mandatory authority; no models or network."""
import json

import pytest

from c1_requirement_quality import cli
from c1_requirement_quality.source_integrity import VerifiedWorkflowContext, resolve_workflow_policy
from test_candidate_validation import context
from test_clarification_proposals import transport


@pytest.fixture
def optional_rag(context, tmp_path, monkeypatch):
    _, source, rid, _, _, factory = context
    monkeypatch.setattr(cli, "RAGGroundingAnalyser", factory)
    monkeypatch.setattr(cli, "LocalNLI", lambda: None)
    # Factory uses the real analyser/verifier with injected local test models.
    def optional_factory(text, **kwargs):
        return factory(text)
    monkeypatch.setattr(cli, "RAGGroundingAnalyser", optional_factory)
    cli.run(source, tmp_path / "optional", "RUN-20261020-120000-opt1",
            registry_path=tmp_path / "optional-registry.json", grounding_mode="rag")
    return tmp_path / "optional/c1/validated_requirements.json", source, rid


def test_optional_diagnostics_are_not_mandatory_provenance(optional_rag):
    path, source, _ = optional_rag
    assert (path.parent / "rag_diagnostics.json").is_file()
    rag, _, manifest, _ = resolve_workflow_policy(VerifiedWorkflowContext(path, source))
    assert not rag and "rag_policy" not in manifest
    assert not (path.parent / "internal/rag_provenance.json").exists()


def test_optional_rag_clarification_cli_preserves_bundle(optional_rag, tmp_path, transport):
    path, source, rid = optional_rag
    before = {p: p.read_bytes() for p in path.parent.rglob("*") if p.is_file()}
    out = tmp_path / "proposals.json"
    assert cli.main(["propose-clarifications", "--in", str(path), "--srs", str(source),
                     "--out", str(out), "--requirement-id", rid, "--backend", "groq"]) == 0
    assert len(transport["calls"]) == 1
    assert json.loads(out.read_text())["decision_effect"] == "none"
    assert all(p.read_bytes() == raw for p, raw in before.items())


@pytest.mark.parametrize("marker", ["rag_provenance_sha256", "rag_diagnostics_sha256", "rag_ancestry_version", "provenance_file"])
def test_orphan_mandatory_markers_rejected_before_provider(optional_rag, tmp_path, transport, marker):
    path, source, rid = optional_rag
    manifest = path.parent / "internal/source_manifest.json"
    if marker == "provenance_file":
        (path.parent / "internal/rag_provenance.json").write_text("{}")
    else:
        data = json.loads(manifest.read_text())
        data[marker] = 1 if marker == "rag_ancestry_version" else "0" * 64
        manifest.chmod(0o644)
        manifest.write_text(json.dumps(data))
    assert cli.main(["propose-clarifications", "--in", str(path), "--srs", str(source),
                     "--out", str(tmp_path / "never.json"), "--requirement-id", rid, "--backend", "groq"]) == 1
    assert not transport["calls"]
    assert not (tmp_path / "never.json").exists()


def test_local_only_campuscare_is_rejected_before_provider(tmp_path, transport):
    source = tmp_path / "CampusCare_synthetic_privacy_fixture.md"
    source.write_text("# Requirements\n1. The system shall record events.\n")
    cli.run(source, tmp_path / "private", "RUN-20261020-120000-priv", registry_path=tmp_path / "private-registry.json")
    path = tmp_path / "private/c1/validated_requirements.json"
    assert cli.main(["propose-clarifications", "--in", str(path), "--srs", str(source),
        "--out", str(tmp_path / "never.json"), "--requirement-id", "REQ-EX-001", "--backend", "groq"]) == 1
    assert not transport["calls"] and not (tmp_path / "never.json").exists()
