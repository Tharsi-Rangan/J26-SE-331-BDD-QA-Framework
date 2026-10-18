"""Unit tests for edge cases: text disambiguation, provenance, and C1-to-C2 traceability."""

import re
from pathlib import Path

from c1_requirement_quality.ingest.dispatcher import extract_srs_requirements
from c1_requirement_quality.requirement_registry import RequirementRegistry


def test_registry_disambiguates_identical_text_across_sections(tmp_path: Path):
    reg_path = tmp_path / "registry.json"
    registry = RequirementRegistry(reg_path, "EX")

    # Identical standard clause in two distinct modules
    texts = [
        "The subsystem shall log all critical errors to persistent storage.",
        "The subsystem shall log all critical errors to persistent storage.",
    ]
    contexts = [
        "Module 1: Navigation",
        "Module 2: Propulsion",
    ]

    ids = registry.assign_ids(texts, contexts=contexts)
    assert len(ids) == 2
    assert ids[0] == "REQ-EX-001"
    assert ids[1] == "REQ-EX-002"
    assert ids[0] != ids[1]

    # Reload registry and verify stable persistence
    reloaded = RequirementRegistry(reg_path, "EX")
    reloaded_ids = reloaded.assign_ids(texts, contexts=contexts)
    assert reloaded_ids == ids


def test_c1_to_c2_scenario_traceability_compliance(tmp_path: Path):
    srs = tmp_path / "spec.md"
    srs.write_text(
        "# 3.0 Core\n"
        "3.1: The system shall process input within 10 ms.\n"
        "3.2: The system shall buffer telemetry samples.\n",
        encoding="utf-8",
    )

    items = extract_srs_requirements(srs)
    reg_path = tmp_path / "registry.json"
    registry = RequirementRegistry(reg_path, "NAV")
    req_ids = registry.assign_ids([str(i["original_text"]) for i in items])

    c1_id_pattern = re.compile(r"^REQ-[A-Z0-9]{2,10}-[0-9]{3,4}$")
    c2_scenario_pattern = re.compile(r"^SCN-[A-Z0-9]{2,10}-[0-9]{3,4}-[0-9]{2}$")

    for req_id in req_ids:
        # 1. Assert C1 ID conforms to frozen contract pattern
        assert c1_id_pattern.match(req_id) is not None

        # 2. Derive downstream C2 scenario IDs and assert conformance
        parts = req_id.split("-")
        proj_code = parts[1]
        req_num = parts[2]
        scenario_id = f"SCN-{proj_code}-{req_num}-01"
        assert c2_scenario_pattern.match(scenario_id) is not None


def test_table_values_preserved_verbatim_without_synthetic_prose(tmp_path: Path):
    srs = tmp_path / "matrix.md"
    srs.write_text(
        "# Parameter Thresholds\n\n"
        "| Parameter | Min | Max | Unit | Req ID |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Core Temp | -40.0 | 85.0 | Celsius | REQ-TEMP-01 |\n"
        "| Bus Voltage | 24.0 | 32.0 | Volts | REQ-VOLT-02 |\n",
        encoding="utf-8",
    )

    items = extract_srs_requirements(srs)
    assert len(items) == 2

    # Verbatim preservation without hallucinated prose
    temp_item = items[0]
    assert temp_item["doc_item_number"] == "REQ-TEMP-01"
    assert "Core Temp" in temp_item["original_text"]
    assert "-40.0" in temp_item["original_text"]
    assert "85.0" in temp_item["original_text"]
    assert "Celsius" in temp_item["original_text"]
