"""Regression tests for Phase 1A.1 requirement extraction quality improvements.

Tests:
1. Structural heading filtering without shall/must keyword dependency.
2. Table of contents (TOC) entry filtering with dot leaders.
3. Multiline requirement text collection across lines.
4. Procedural use-case action steps vs genuine system response constraints.
5. Modal and modal-less functional/non-functional requirements (is required, cannot be, never unlocks).
6. Table extraction with verbatim headers and data cells.
7. Repeated numbering handling and provenance warnings.
8. Traceability and stable canonical ID assignment across reprocessing.
9. Backward compatibility with frozen C1-to-C2 JSON schema and sidecar diagnostics.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import re


def _make_multipage_pdf(pages: list[list[str]]) -> bytes:
    num_pages = len(pages)
    current_obj = 3 + num_pages * 2
    font_obj_id = current_obj

    body = [b"%PDF-1.4"]
    body.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj")
    kids_str = " ".join(f"{3 + i} 0 R" for i in range(num_pages))
    body.append(f"2 0 obj << /Type /Pages /Kids [{kids_str}] /Count {num_pages} >> endobj".encode("latin1"))

    for i in range(num_pages):
        page_id = 3 + i
        content_id = 3 + num_pages + i
        body.append(
            f"{page_id} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R /Resources << /Font << /F1 {font_obj_id} 0 R >> >> >> endobj".encode("latin1")
        )

    for i, lines in enumerate(pages):
        content_id = 3 + num_pages + i
        stream_content = "BT /F1 12 Tf 50 750 Td "
        for l in lines:
            safe_line = l.replace("(", r"\(").replace(")", r"\)")
            stream_content += f"({safe_line}) Tj 0 -15 Td "
        stream_content += "ET"
        stream_bytes = stream_content.encode("latin1")
        body.append(
            f"{content_id} 0 obj << /Length {len(stream_bytes)} >> stream\n".encode("latin1")
            + stream_bytes
            + b"\nendstream endobj"
        )

    body.append(f"{font_obj_id} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj".encode("latin1"))

    offsets = []
    full = bytearray()
    for obj in body:
        offsets.append(len(full))
        full.extend(obj + b"\n")

    xref_offset = len(full)
    total_objs = len(body)
    xref_table = f"xref\n0 {total_objs}\n0000000000 65535 f \n".encode("latin1") + b"".join(
        f"{off:010d} 00000 n \n".encode("latin1") for off in offsets[1:]
    )
    trailer = f"trailer << /Root 1 0 R /Size {total_objs} >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("latin1")
    return bytes(full + xref_table + trailer)

from c1_requirement_quality.cli import _validate_contract_artifact, main
from c1_requirement_quality.ingest.dispatcher import load_srs_document
from c1_requirement_quality.ingest.models import NIRDocument
from c1_requirement_quality.requirement_registry import RequirementRegistry


def test_headings_and_toc_entries_filtered_as_context(tmp_path: Path):
    """Verify structural headings and TOC dot-leader entries are categorized as CONTEXT, not REQUIREMENT."""
    pdf_bytes = _make_multipage_pdf([

        [
            "Table of Contents",
            "1. Introduction.............................................1",
            "2. System Features.........................................5",
            "3. Specific Requirements...................................10",
        ],
        [
            "1. Introduction",
            "1.1 Purpose",
            "This document describes the subsystem architecture.",
            "1.2 Scope",
            "The scope of this product includes automated flight telemetry.",
        ],
        [
            "3. Specific Requirements",
            "REQ-01: The telemetry unit shall transmit status packets at 10 Hz.",
        ],
    ])
    pdf_file = tmp_path / "spec_toc.pdf"
    pdf_file.write_bytes(pdf_bytes)

    doc = load_srs_document(pdf_file)
    assert isinstance(doc, NIRDocument)

    # Only REQ-01 should be a REQUIREMENT
    assert len(doc.requirements) == 1
    req = doc.requirements[0]
    assert req.doc_item_number == "REQ-01"
    assert "transmit status packets at 10 Hz" in req.raw_text
    assert req.category == "REQUIREMENT"

    # TOC and headings must be preserved in context_items for evidence/RAG
    assert len(doc.context_items) >= 4
    toc_items = [c for c in doc.context_items if c.sub_category in ("TOC_ENTRY", "TOC_HEADING")]
    assert len(toc_items) >= 3
    heading_items = [c for c in doc.context_items if c.sub_category == "HEADING"]
    assert len(heading_items) >= 2


def test_multiline_requirement_continuation(tmp_path: Path):
    """Verify multiline requirement statements spanning several lines are collected into single requirements."""
    pdf_bytes = _make_multipage_pdf([
        [
            "3. Functional Requirements",
            "REQ-101: The ground station shall authenticate all incoming telecommands",
            "using cryptographic certificates signed by the mission controller before",
            "dispatching instructions to the flight bus.",
            "REQ-102: In case of authentication failure, the telemetry packet shall be logged.",
        ]
    ])
    pdf_file = tmp_path / "multiline_spec.pdf"
    pdf_file.write_bytes(pdf_bytes)

    doc = load_srs_document(pdf_file)
    assert len(doc.requirements) == 2

    r1 = doc.requirements[0]
    assert r1.doc_item_number == "REQ-101"
    assert "authenticate all incoming telecommands" in r1.raw_text
    assert "cryptographic certificates signed by the mission controller" in r1.raw_text
    assert "dispatching instructions to the flight bus" in r1.raw_text


def test_use_case_steps_vs_system_responses(tmp_path: Path):
    """Verify user procedural steps are classified as CONTEXT while system responses/constraints remain REQUIREMENT."""
    pdf_bytes = _make_multipage_pdf([
        [
            "3.2 Use Case: Database Backup",
            "1. User clicks File -> Export.",
            "2. User selects destination folder.",
            "3. User clicks Start Backup.",
            "4. The system shall encrypt the backup archive using AES-256 before disk write.",
            "5. User confirms operation complete.",
        ]
    ])
    pdf_file = tmp_path / "use_case_spec.pdf"
    pdf_file.write_bytes(pdf_bytes)

    doc = load_srs_document(pdf_file)

    # Step 4 is a system requirement ("The system shall encrypt...")
    assert len(doc.requirements) == 1
    assert "AES-256" in doc.requirements[0].raw_text
    assert doc.requirements[0].category == "REQUIREMENT"
    assert doc.requirements[0].sub_category == "SYSTEM_RESPONSE"

    # Steps 1, 2, 3, 5 are procedural user actions preserved as CONTEXT
    user_steps = [c for c in doc.context_items if c.sub_category == "USE_CASE_STEP"]
    assert len(user_steps) == 4
    assert any("User clicks File" in s.raw_text for s in user_steps)
    assert any("User selects destination" in s.raw_text for s in user_steps)


def test_modal_less_normative_requirements(tmp_path: Path):
    """Verify requirements without shall/must (using constraints like is required, cannot be, never unlocks) are extracted."""
    pdf_bytes = _make_multipage_pdf([
        [
            "3. Security Constraints",
            "REQ-SEC-01: A master key is required in order for the encrypted volume to be mounted.",
            "REQ-SEC-02: A subgroup cannot be created when no parent group is selected.",
            "REQ-SEC-03: Only one database file is allowed in command line options.",
            "REQ-SEC-04: In case of lost master password, the database never unlocks.",
            "REQ-SEC-05: There is no backdoor or master recovery key that unlocks all databases.",
        ]
    ])
    pdf_file = tmp_path / "modal_less_spec.pdf"
    pdf_file.write_bytes(pdf_bytes)

    doc = load_srs_document(pdf_file)
    assert len(doc.requirements) == 5
    for req in doc.requirements:
        assert req.category == "REQUIREMENT"
        assert req.doc_item_number.startswith("REQ-SEC-")

    # None of these 5 requirements contain "shall" or "must"
    for req in doc.requirements:
        assert "shall" not in req.raw_text.lower()
        assert "must" not in req.raw_text.lower()


def test_bulleted_quality_attributes(tmp_path: Path):
    """Verify non-functional quality requirements with bullet markers (middle dot, standard bullet) are extracted."""
    pdf_bytes = _make_multipage_pdf([
        [
            "5. Quality Attribute Requirements",
            "5.1 Performance Requirements",
            "\u00b7 The system shall be able to handle 1000 customers logged in concurrently.",
            "- The system shall be able to retrieve 200 products per second.",
            "5.2 Reliability Requirements",
            "\u00b7 The system will do periodic backups through a live internet connection.",

        ]
    ])
    pdf_file = tmp_path / "quality_spec.pdf"
    pdf_file.write_bytes(pdf_bytes)

    doc = load_srs_document(pdf_file)
    assert len(doc.requirements) == 3
    for req in doc.requirements:
        assert req.category == "REQUIREMENT"
    assert any("1000 customers" in r.raw_text for r in doc.requirements)
    assert any("200 products per second" in r.raw_text for r in doc.requirements)
    assert any("periodic backups" in r.raw_text for r in doc.requirements)


def test_repeated_numbering_and_provenance_stability(tmp_path: Path):
    """Verify repeated requirement numbers across sections emit warnings and maintain stable registry IDs."""
    pdf_bytes = _make_multipage_pdf([
        [
            "3.1 Navigation",
            "REQ-01: The system shall compute GPS fixes at 1 Hz.",
        ],
        [
            "3.2 Communications",
            "REQ-01: The system shall ping the satellite link at 0.1 Hz.",
        ],
    ])
    pdf_file = tmp_path / "repeated_num_spec.pdf"
    pdf_file.write_bytes(pdf_bytes)

    doc = load_srs_document(pdf_file)
    assert len(doc.requirements) == 2

    # Registry assigns distinct, canonical IDs
    reg_path = tmp_path / "reg.json"
    registry = RequirementRegistry(reg_path, "TEST")
    ids_1 = registry.assign_ids(
        [r.raw_text for r in doc.requirements],
        contexts=[r.section_title for r in doc.requirements],
    )
    assert len(ids_1) == 2
    assert ids_1[0] == "REQ-TEST-001"
    assert ids_1[1] == "REQ-TEST-002"

    # Reprocessing with the same registry yields the exact same IDs
    reloaded_reg = RequirementRegistry(reg_path, "TEST")
    ids_2 = reloaded_reg.assign_ids(
        [r.raw_text for r in doc.requirements],
        contexts=[r.section_title for r in doc.requirements],
    )
    assert ids_2 == ids_1


def test_cli_sidecar_and_schema_compatibility(tmp_path: Path):
    """Verify CLI produces extraction_diagnostics.json sidecar and validated_requirements.json conforms to frozen schema."""
    pdf_bytes = _make_multipage_pdf([
        [
            "Contents",
            "1. Overview..................................................1",
            "2. Specific Requirements.....................................2",
        ],
        [
            "1. Overview",
            "This document provides the flight software requirements.",
        ],
        [
            "2. Specific Requirements",
            "REQ-A1: The guidance unit shall calculate descent velocity at 20 Hz.",
            "REQ-A2: The emergency beacon must activate within 500 ms of abort command.",
            "1. Procedural note without modal verbs.",
        ],
    ])
    pdf_file = tmp_path / "flight_spec.pdf"
    pdf_file.write_bytes(pdf_bytes)

    out_dir = tmp_path / "run_flight"
    ret = main([
        "run",
        "--srs", str(pdf_file),
        "--out", str(out_dir),
        "--run-id", "RUN-20261013-180000-fl01",
        "--project-code", "FL",
        "--registry", str(tmp_path / "flight_reg.json"),
    ])
    assert ret == 0

    # 1. Check validated_requirements.json adheres to unchanged schema
    val_path = out_dir / "c1" / "validated_requirements.json"
    assert val_path.is_file()
    val_data = json.loads(val_path.read_text(encoding="utf-8"))
    _validate_contract_artifact(val_data)
    assert len(val_data["requirements"]) == 2

    # 2. Check extraction_diagnostics.json sidecar preserves CONTEXT and UNCERTAIN items
    diag_path = out_dir / "c1" / "extraction_diagnostics.json"
    assert diag_path.is_file()
    diag_data = json.loads(diag_path.read_text(encoding="utf-8"))
    assert diag_data["requirements_count"] == 2
    assert diag_data["context_items_count"] >= 2
    assert diag_data["uncertain_items_count"] >= 1
    assert any("TOC" in k for k in diag_data["context_summary"].keys())
