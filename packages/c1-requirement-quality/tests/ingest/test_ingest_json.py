"""Unit tests for Structured JSON SRS ingestion."""

import json
from pathlib import Path

from c1_requirement_quality.ingest.json_loader import load_json_srs
from c1_requirement_quality.srs_parser import parse_srs


def test_json_array_of_requirements(tmp_path: Path):
    srs = tmp_path / "requirements.json"
    data = [
        {
            "id": "NAV-01",
            "section": "Navigation Module",
            "text": "The guidance computer shall update course every 100 milliseconds.",
        },
        {
            "id": "NAV-02",
            "section": "Navigation Module",
            "text": "The guidance computer shall maintain positional error under 2 meters.",
        },
    ]
    srs.write_text(json.dumps(data, indent=2), encoding="utf-8")

    doc = load_json_srs(srs)
    assert doc.format == "json"
    assert len(doc.requirements) == 2

    r1 = doc.requirements[0]
    assert r1.doc_item_number == "NAV-01"
    assert r1.section_title == "Navigation Module"
    assert r1.raw_text == "The guidance computer shall update course every 100 milliseconds."


def test_json_object_with_requirements_list(tmp_path: Path):
    srs = tmp_path / "project_export.json"
    data = {
        "project_code": "AV",
        "requirements": [
            {
                "requirement_id": "REQ-101",
                "section": "Telemetry",
                "statement": "The telemetry subsystem shall stream metrics via UDP port 5000.",
                "line": 15,
            }
        ],
    }
    srs.write_text(json.dumps(data, indent=2), encoding="utf-8")

    parsed = parse_srs(srs, "AV")
    assert len(parsed) == 1
    assert parsed[0]["requirement_id"] == "REQ-AV-001"
    assert parsed[0]["source"]["section"] == "Telemetry"
    assert parsed[0]["original_text"] == "The telemetry subsystem shall stream metrics via UDP port 5000."


def test_json_object_with_sections_hierarchy(tmp_path: Path):
    srs = tmp_path / "modular_srs.json"
    data = {
        "sections": [
            {
                "title": "3.1 Diagnostics",
                "requirements": [
                    {"id": "DIAG-1", "text": "The diagnostics service shall report DTC fault codes."}
                ],
            },
            {
                "title": "3.2 Recovery",
                "requirements": [
                    {"id": "REC-1", "text": "The system shall execute failover within 500 ms."}
                ],
            },
        ]
    }
    srs.write_text(json.dumps(data, indent=2), encoding="utf-8")

    doc = load_json_srs(srs)
    assert len(doc.requirements) == 2
    assert doc.requirements[0].section_title == "3.1 Diagnostics"
    assert doc.requirements[1].section_title == "3.2 Recovery"
