"""Content-only relocation tests: no ACL copying, models or external requests."""
import hashlib
import json
import socket
from pathlib import Path
from unittest.mock import patch

import pytest

from c1_requirement_quality import cli
from c1_requirement_quality.source_integrity import verify_source
from c1_requirement_quality.workflow_persistence import load_state
from c1_requirement_quality.rewrite_generator import generate_candidates_run
from c1_requirement_quality.clarification_proposals import propose_clarifications_run
from c1_requirement_quality.groq_generator import GroqGeneratorBackend


def copy_contents(source, destination):
    files = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert not destination.exists()
    destination.mkdir()
    for relative, raw in files.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
    assert all(hashlib.sha256((destination / rel).read_bytes()).digest() == hashlib.sha256(raw).digest()
               and (source / rel).read_bytes() == raw for rel, raw in files.items())
    return files


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No external network in portability checks")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def test_multiround_family_relocates_without_rewriting_parent_references(tmp_path):
    family = tmp_path / "original"
    family.mkdir()
    srs = family / "source.md"
    srs.write_text("# Requirements\n1. The system shall send email.\n", encoding="utf-8")
    cli.run(srs, family / "round0", "RUN-20261015-230000-pt01", registry_path=family / "registry.json")
    actions = family / "actions.json"
    actions.write_text('{"requirements": []}')
    cli.refine_run(family / "round0/c1/validated_requirements.json", srs, actions, family / "round1")
    original = family / "round1/c1/validated_requirements.json"
    before, _ = load_state(original, srs)
    destination = tmp_path / "relocated"
    copy_contents(family, destination)
    relocated = destination / "round1/c1/validated_requirements.json"
    source = destination / "round1/c1/internal/source/source.md"
    after, _ = load_state(relocated, source)
    assert after == before
    assert after["round"] == 1 and after["parent"] is not None
    parent = (relocated.parent / after["parent"]["artifact_path"]).resolve()
    assert parent == (destination / "round0/c1/validated_requirements.json").resolve()
    verify_source(relocated, source)
    cli._validate_contract_artifact(json.loads(relocated.read_text()))


def test_relocated_kinmail_supports_all_three_workflows_without_input_mutation(tmp_path):
    original = Path(__file__).resolve().parents[1] / "local-inference/kinmail-portable-001"
    if not (original / "run/c1/validated_requirements.json").is_file():
        pytest.skip("Exported local Kinmail bundle not available")
    destination = tmp_path / "portable"
    copy_contents(original, destination)
    artifact = destination / "run/c1/validated_requirements.json"
    source = destination / "run/c1/internal/source/SRS.docx"
    protected = {p: p.read_bytes() for p in destination.rglob("*") if p.is_file()}
    verify_source(artifact, source)
    state, _ = load_state(artifact, source)
    assert state["round"] == 0 and state["parent"] is None
    generate_candidates_run(artifact, source, tmp_path / "candidate-check.json")
    actions = tmp_path / "empty-actions.json"
    actions.write_text('{"requirements": []}')
    cli.refine_run(artifact, source, actions, tmp_path / "refine-check")
    child = tmp_path / "refine-check/c1/validated_requirements.json"
    load_state(child, source)
    value = json.loads(child.read_text(encoding="utf-8"))
    assert len(value["requirements"]) == 21
    assert all(r["human_decision"] == "pending" and r["bdd_ready"] is False for r in value["requirements"])
    def completion(messages):
        context = json.loads(messages[1]["content"])
        ref = context["source_evidence"][0]["ref"]
        proposal = {"schema_version": 1, "requirement_id": context["requirement_id"],
            "source_evidence_refs": [ref], "advisory_refs": [],
            "clarification_questions": [{"question": "Which acceptance criteria are required?",
                "reason": "The source leaves acceptance criteria unspecified.",
                "source_evidence_refs": [ref], "advisory_refs": []}],
            "proposed_rewrite": None, "unresolved_assumptions": [], "claimed_grounding_status": "insufficient"}
        return {"model": "qwen/qwen3.8-27b", "choices": [{"finish_reason": "stop",
                "message": {"content": json.dumps(proposal)}}]}
    backend = GroqGeneratorBackend("mock-portability-key", "qwen/qwen3.8-27b")
    with patch.object(GroqGeneratorBackend, "from_environment", return_value=backend), patch.object(backend, "_complete", side_effect=completion) as calls:
        propose_clarifications_run(artifact, source, tmp_path / "MOCKED-clarification-check.json", ["REQ-EX-017"])
        assert calls.call_count == 1
    assert all(p.read_bytes() == raw for p, raw in protected.items())
    cli._validate_contract_artifact(value)
