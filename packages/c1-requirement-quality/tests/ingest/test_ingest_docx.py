"""Unit tests for Word DOCX SRS ingestion: headings, paragraph flow, and tables."""

from pathlib import Path
import docx

from c1_requirement_quality.ingest.docx_loader import load_docx_srs
from c1_requirement_quality.srs_parser import parse_srs


def test_docx_headings_paragraphs_and_table_extraction(tmp_path: Path):
    docx_path = tmp_path / "system_spec.docx"
    doc = docx.Document()

    # Add Heading 1
    doc.add_heading("1.0 Power Subsystem", level=1)
    doc.add_paragraph("1.1 The power manager shall regulate bus voltage to 28V +/- 1V.")

    # Add Heading 2
    doc.add_heading("1.1 Battery Backup", level=2)
    doc.add_paragraph("1.2 The battery backup shall provide emergency power for at least 45 minutes.")

    # Add Table
    table = doc.add_table(rows=3, cols=3)
    table.rows[0].cells[0].text = "Requirement ID"
    table.rows[0].cells[1].text = "Statement"
    table.rows[0].cells[2].text = "Criticality"

    table.rows[1].cells[0].text = "PWR-TAB-01"
    table.rows[1].cells[1].text = "The solar array shall recharge batteries within 120 minutes."
    table.rows[1].cells[2].text = "High"

    table.rows[2].cells[0].text = "PWR-TAB-02"
    table.rows[2].cells[1].text = "The thermal controller shall dissipate excess heat above 65C."
    table.rows[2].cells[2].text = "Moderate"

    doc.save(str(docx_path))

    nir = load_docx_srs(docx_path)
    assert nir.format == "docx"
    assert len(nir.tables) == 1
    assert len(nir.requirements) == 4

    # Verify paragraph requirements
    p_reqs = [r for r in nir.requirements if r.table_id is None]
    assert len(p_reqs) == 2
    assert p_reqs[0].doc_item_number == "1.1"
    assert "regulate bus voltage" in p_reqs[0].raw_text
    assert p_reqs[1].doc_item_number == "1.2"
    assert "emergency power" in p_reqs[1].raw_text

    # Verify table requirements
    t_reqs = [r for r in nir.requirements if r.table_id is not None]
    assert len(t_reqs) == 2
    assert t_reqs[0].doc_item_number == "PWR-TAB-01"
    assert "solar array shall recharge" in t_reqs[0].raw_text
    assert t_reqs[1].doc_item_number == "PWR-TAB-02"

    # Verify warning recorded for missing page boundaries in DOCX
    assert any(w.code == "DOCX_PAGE_NUMBERS_UNAVAILABLE" for w in nir.warnings)

    # Verify compatibility parse_srs assigns canonical REQ-EX IDs
    parsed = parse_srs(docx_path, "EX")
    assert len(parsed) == 4
    for idx, item in enumerate(parsed, start=1):
        assert item["requirement_id"] == f"REQ-EX-{idx:03d}"
