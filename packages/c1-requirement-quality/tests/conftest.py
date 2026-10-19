"""Integrity-aware setup for hand-authored CLI fixture artifacts."""
import pytest
import json

from c1_requirement_quality.source_integrity import snapshot_source, seal_source


@pytest.fixture
def archive_test_source():
    def archive(input_path, source):
        _, manifest = snapshot_source(input_path.parent, source, "TEST-DOCUMENT")
        seal_source(input_path.parent, manifest)
    return archive


@pytest.fixture
def verified_legacy(tmp_path):
    """Archive each hand-authored kernel input; do not mock policy resolution."""
    from c1_requirement_quality.source_integrity import VerifiedWorkflowContext, resolve_workflow_policy
    count = 0
    def bind(artifact, text):
        nonlocal count
        count += 1
        root = tmp_path / f"legacy-{count}"
        root.mkdir()
        source = root / artifact["source_document"]["name"]
        source.write_text(text, encoding="utf-8")
        target = root / "c1"
        target.mkdir()
        path = target / "validated_requirements.json"
        path.write_text(json.dumps(artifact), encoding="utf-8")
        _, manifest = snapshot_source(target, source, "TEST-LEGACY")
        seal_source(target, manifest)
        context = VerifiedWorkflowContext(path, source)
        resolve_workflow_policy(context, artifact=artifact, source_text=text)
        return context
    return bind
