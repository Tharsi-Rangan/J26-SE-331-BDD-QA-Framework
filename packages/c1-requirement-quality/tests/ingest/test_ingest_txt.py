"""Unit tests for Plain Text SRS ingestion."""

from pathlib import Path
from c1_requirement_quality.ingest.txt_loader import load_txt_srs
from c1_requirement_quality.srs_parser import parse_srs


def test_txt_outline_sections_and_numbered_requirements(tmp_path: Path):
    srs = tmp_path / "spec.txt"
    srs.write_text(
        "SECTION 1: SYSTEM OVERVIEW\n\n"
        "1.1 The system shall initialize hardware controllers at startup.\n\n"
        "SECTION 2: SECURITY POLICY\n\n"
        "2.1 The system shall encrypt local storage using AES-256.\n"
        "2.2 The system shall rotate cryptographic keys every 90 days.\n",
        encoding="utf-8",
    )

    doc = load_txt_srs(srs)
    assert doc.format == "txt"
    assert len(doc.requirements) == 3

    r1 = doc.requirements[0]
    assert r1.doc_item_number == "1.1"
    assert r1.section_title == "SECTION 1: SYSTEM OVERVIEW"
    assert r1.raw_text == "The system shall initialize hardware controllers at startup."

    r2 = doc.requirements[1]
    assert r2.doc_item_number == "2.1"
    assert r2.section_title == "SECTION 2: SECURITY POLICY"

    r3 = doc.requirements[2]
    assert r3.doc_item_number == "2.2"
    assert r3.section_title == "SECTION 2: SECURITY POLICY"


def test_txt_multiline_continuation(tmp_path: Path):
    srs = tmp_path / "multiline.txt"
    srs.write_text(
        "1. The telemetry processor shall publish metrics:\n"
        "CPU utilization percentage\n"
        "Heap allocation size\n\n"
        "2. The system shall send heartbeat alerts every 5 seconds.\n",
        encoding="utf-8",
    )

    doc = load_txt_srs(srs)
    assert len(doc.requirements) == 2
    r1 = doc.requirements[0]
    assert "CPU utilization percentage" in r1.raw_text
    assert "Heap allocation size" in r1.raw_text


def test_txt_parse_srs_backward_compatibility(tmp_path: Path):
    srs = tmp_path / "legacy.txt"
    srs.write_text(
        "# 1.0 General\n"
        "1.1: The system shall log all audit events.\n",
        encoding="utf-8",
    )

    parsed = parse_srs(srs, "EX")
    assert len(parsed) == 1
    assert parsed[0]["requirement_id"] == "REQ-EX-001"
    assert parsed[0]["original_text"] == "The system shall log all audit events."
