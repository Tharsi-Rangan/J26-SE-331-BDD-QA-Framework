from pathlib import Path

import pytest

from c1_requirement_quality.requirement_registry import RequirementRegistry


def test_assigns_ids_on_first_run(tmp_path: Path):
    registry = RequirementRegistry(tmp_path / "registry.json", "EX")

    ids = registry.assign_ids([
        "The system shall allow registration.",
        "The system shall allow login.",
    ])

    assert ids == ["REQ-EX-001", "REQ-EX-002"]


def test_preserves_ids_after_reloading_registry(tmp_path: Path):
    path = tmp_path / "registry.json"
    first = RequirementRegistry(path, "EX")

    original_ids = first.assign_ids([
        "The system shall allow registration.",
        "The system shall allow login.",
    ])

    second = RequirementRegistry(path, "EX")
    reloaded_ids = second.assign_ids([
        "The system shall allow registration.",
        "The system shall allow login.",
    ])

    assert reloaded_ids == original_ids


def test_new_requirement_does_not_renumber_existing_ids(tmp_path: Path):
    path = tmp_path / "registry.json"
    registry = RequirementRegistry(path, "EX")

    registry.assign_ids([
        "The system shall allow registration.",
        "The system shall allow login.",
    ])

    ids = registry.assign_ids([
        "The system shall allow registration.",
        "The system shall allow login.",
        "The system shall allow password reset.",
    ])

    assert ids == ["REQ-EX-001", "REQ-EX-002", "REQ-EX-003"]


def test_deleted_requirement_id_is_retired_and_not_reused(tmp_path: Path):
    path = tmp_path / "registry.json"
    registry = RequirementRegistry(path, "EX")

    registry.assign_ids([
        "The system shall allow registration.",
        "The system shall allow login.",
    ])

    registry.assign_ids(["The system shall allow registration."])

    ids = registry.assign_ids([
        "The system shall allow registration.",
        "The system shall allow password reset.",
    ])

    assert ids == ["REQ-EX-001", "REQ-EX-003"]

    saved = path.read_text(encoding="utf-8")
    assert "REQ-EX-002" in saved


def test_rejects_duplicate_requirement_text(tmp_path: Path):
    registry = RequirementRegistry(tmp_path / "registry.json", "EX")

    with pytest.raises(ValueError, match="Duplicate requirement text"):
        registry.assign_ids([
            "The system shall allow login.",
            "The system shall allow login.",
        ])


def test_rejects_wrong_project_code_when_loading_registry(tmp_path: Path):
    path = tmp_path / "registry.json"
    RequirementRegistry(path, "EX").assign_ids([
        "The system shall allow login.",
    ])

    with pytest.raises(ValueError, match="project code"):
        RequirementRegistry(path, "AB")