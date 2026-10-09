
from pathlib import Path

import pytest

from c1_requirement_quality.srs_parser import parse_srs


def test_extracts_requirement_and_source_location(tmp_path: Path):
    srs = tmp_path / "sample.md"
    srs.write_text(
        "# 3. Registration\n"
        "3.1: The system shall allow users to register.\n",
        encoding="utf-8",
    )

    requirements = parse_srs(srs, "EX")

    assert len(requirements) == 1
    assert requirements[0]["requirement_id"] == "REQ-EX-001"
    assert requirements[0]["source"] == {
        "section": "3. Registration",
        "line": 2,
    }
    assert requirements[0]["original_text"] == (
        "The system shall allow users to register."
    )


def test_empty_file_returns_no_requirements(tmp_path: Path):
    srs = tmp_path / "empty.md"
    srs.write_text("", encoding="utf-8")

    assert parse_srs(srs, "EX") == []


def test_duplicate_source_number_raises_error(tmp_path: Path):
    srs = tmp_path / "duplicate.md"
    srs.write_text(
        "1. The system shall allow registration.\n"
        "1. The system shall allow login.\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate requirement number"):
        parse_srs(srs, "EX")


def test_invalid_project_code_raises_error(tmp_path: Path):
    srs = tmp_path / "sample.md"
    srs.write_text(
        "1. The system shall allow registration.\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="project_code"):
        parse_srs(srs, "ex")
