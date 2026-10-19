"""Unit tests for Markdown SRS ingestion: multiline, tables, hierarchy, and repeated numbers."""

from pathlib import Path
import pytest

from c1_requirement_quality.ingest.markdown_loader import load_markdown_srs
from c1_requirement_quality.srs_parser import parse_srs


def test_markdown_multiline_requirement_with_indented_subbullets(tmp_path: Path):
    srs = tmp_path / "multiline.md"
    srs.write_text(
        "# 3. User Authentication\n\n"
        "3.1: The system shall support multi-factor authentication:\n"
        "  - Support SMS one-time passcodes\n"
        "  - Support Time-based OTP (TOTP) authenticator apps\n"
        "  - Enforce fallback security questions\n\n"
        "3.2: The system shall lock accounts after 5 failed attempts.\n",
        encoding="utf-8",
    )

    doc = load_markdown_srs(srs)
    assert len(doc.requirements) == 2

    mfa_req = doc.requirements[0]
    assert mfa_req.doc_item_number == "3.1"
    assert "The system shall support multi-factor authentication:" in mfa_req.raw_text
    assert "Support SMS one-time passcodes" in mfa_req.raw_text
    assert "Support Time-based OTP (TOTP)" in mfa_req.raw_text
    assert "Enforce fallback security questions" in mfa_req.raw_text

    lock_req = doc.requirements[1]
    assert lock_req.doc_item_number == "3.2"
    assert lock_req.raw_text == "The system shall lock accounts after 5 failed attempts."


def test_markdown_section_hierarchy_tracking(tmp_path: Path):
    srs = tmp_path / "hierarchy.md"
    srs.write_text(
        "# 1.0 System Architecture\n"
        "## 1.1 Ingestion Layer\n"
        "### 1.1.1 Normalization Engine\n"
        "1. The normalization engine shall parse UTF-8 text streams.\n",
        encoding="utf-8",
    )

    doc = load_markdown_srs(srs)
    assert len(doc.requirements) == 1
    req = doc.requirements[0]
    assert req.section_title == "1.1.1 Normalization Engine"
    assert req.section_hierarchy == [
        "1.0 System Architecture",
        "1.1 Ingestion Layer",
        "1.1.1 Normalization Engine",
    ]


def test_markdown_setext_headings(tmp_path: Path):
    srs = tmp_path / "setext.md"
    srs.write_text(
        "Module A: Navigation\n"
        "====================\n"
        "Submodule A.1: GPS Tracking\n"
        "---------------------------\n"
        "1. The GPS module shall acquire satellite lock within 30 seconds.\n",
        encoding="utf-8",
    )

    doc = load_markdown_srs(srs)
    assert len(doc.requirements) == 1
    req = doc.requirements[0]
    assert req.section_title == "Submodule A.1: GPS Tracking"
    assert req.section_hierarchy == [
        "Module A: Navigation",
        "Submodule A.1: GPS Tracking",
    ]


def test_markdown_table_extraction_without_inventing_text(tmp_path: Path):
    srs = tmp_path / "table.md"
    srs.write_text(
        "# 4.0 Performance Requirements\n\n"
        "| Req ID | Parameter | Threshold | Unit | Verification |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| REQ-PERF-01 | Max Latency | 200 | ms | Automated Benchmark |\n"
        "| REQ-PERF-02 | Max Memory | 1024 | MB | Profile Inspection |\n",
        encoding="utf-8",
    )

    doc = load_markdown_srs(srs)
    assert len(doc.tables) == 1
    table = doc.tables[0]
    assert table.headers == ["Req ID", "Parameter", "Threshold", "Unit", "Verification"]
    assert len(table.rows) == 2
    assert table.rows[0] == ["REQ-PERF-01", "Max Latency", "200", "ms", "Automated Benchmark"]

    # Requirements extracted verbatim from table
    assert len(doc.requirements) == 2
    r1 = doc.requirements[0]
    assert r1.doc_item_number == "REQ-PERF-01"
    assert r1.table_id == "Table-1"
    assert "Table: Table-1" in r1.to_source_dict()["section"]


def test_markdown_repeated_numbering_across_sections(tmp_path: Path):
    srs = tmp_path / "restarts.md"
    srs.write_text(
        "# 3.1 Network Subsystem\n"
        "1. The system shall reconnect upon connection drop.\n\n"
        "# 4.1 Storage Subsystem\n"
        "1. The system shall sync data to disk every 60 seconds.\n",
        encoding="utf-8",
    )

    parsed = parse_srs(srs, "EX")
    assert len(parsed) == 2
    assert parsed[0]["requirement_id"] == "REQ-EX-001"
    assert parsed[0]["source"]["section"] == "3.1 Network Subsystem"
    assert parsed[1]["requirement_id"] == "REQ-EX-002"
    assert parsed[1]["source"]["section"] == "4.1 Storage Subsystem"


def test_markdown_duplicate_number_within_same_section_raises_error(tmp_path: Path):
    srs = tmp_path / "dup_same_sec.md"
    srs.write_text(
        "# 3.1 Network Subsystem\n"
        "1. The system shall reconnect upon connection drop.\n"
        "1. The system shall retry up to 3 times.\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate requirement number"):
        parse_srs(srs, "EX")
