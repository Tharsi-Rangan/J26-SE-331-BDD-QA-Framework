"""Unit tests for text-based PDF SRS ingestion."""

from pathlib import Path
from c1_requirement_quality.ingest.pdf_loader import load_pdf_srs
from c1_requirement_quality.srs_parser import parse_srs


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


def test_pdf_multipage_requirement_extraction_with_page_provenance(tmp_path: Path):
    pdf_path = tmp_path / "system_spec.pdf"
    pdf_path.write_bytes(
        _make_multipage_pdf([
            [
                "SECTION 1: SENSORS",
                "1.1 The radar sensor shall scan at 20 Hz.",
                "1.2 The lidar unit shall generate 1M points per second.",
            ],
            [
                "SECTION 2: ACTUATORS",
                "2.1 The steering actuator shall respond within 50 ms.",
            ],
        ])
    )

    doc = load_pdf_srs(pdf_path)
    assert doc.format == "pdf"
    assert len(doc.requirements) == 3

    # Check page numbers
    r1 = doc.requirements[0]
    assert r1.doc_item_number == "1.1"
    assert r1.page == 1
    assert "The radar sensor shall scan at 20 Hz." in r1.raw_text

    r2 = doc.requirements[1]
    assert r2.doc_item_number == "1.2"
    assert r2.page == 1

    r3 = doc.requirements[2]
    assert r3.doc_item_number == "2.1"
    assert r3.page == 2
    assert "The steering actuator shall respond within 50 ms." in r3.raw_text

    # Parse SRS assigns stable canonical REQ-EX IDs
    parsed = parse_srs(pdf_path, "EX")
    assert len(parsed) == 3
    assert parsed[0]["requirement_id"] == "REQ-EX-001"
    assert parsed[1]["requirement_id"] == "REQ-EX-002"
    assert parsed[2]["requirement_id"] == "REQ-EX-003"
    assert parsed[2]["source"]["section"] == "SECTION 2: ACTUATORS [p. 2]"
