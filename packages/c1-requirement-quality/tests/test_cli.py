import pytest

from c1_requirement_quality.cli import build_parser, main


def test_reads_run_options():
    args = build_parser().parse_args([
        "run",
        "--srs",
        "srs.md",
        "--out",
        "runs/example",
        "--run-id",
        "RUN-20261009-181600-ab12",
    ])
    assert args.srs == "srs.md"
    assert args.out == "runs/example"
    assert args.run_id == "RUN-20261009-181600-ab12"


def test_rejects_missing_out():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--srs", "srs.md"])


def test_run_creates_c1_folder(tmp_path):
    srs = tmp_path / "sample.md"
    srs.write_text(
        "1. The system shall allow users to register.\n",
        encoding="utf-8",
    )

    assert main([
        "run",
        "--srs",
        str(srs),
        "--out",
        str(tmp_path),
        "--run-id",
        "RUN-20261009-181600-ab12",
    ]) == 0
    assert (tmp_path / "c1").is_dir()
    assert (tmp_path / "c1" / "parsed_requirements.json").is_file()
    assert (tmp_path / "c1" / "validated_requirements.json").is_file()


def test_run_rejects_missing_srs_file(tmp_path):
    missing_srs = tmp_path / "missing.md"
    output_dir = tmp_path / "runs" / "RUN-TEST"

    result = main([
        "run",
        "--srs",
        str(missing_srs),
        "--out",
        str(output_dir),
        "--run-id",
        "RUN-20261009-181600-ab12",
    ])

    assert result == 1


def test_run_preserves_requirement_ids_when_new_requirement_is_added(tmp_path):
    srs = tmp_path / "sample.md"
    registry = tmp_path / "registry.json"

    srs.write_text(
        "1. The system shall allow users to log in.\n"
        "2. The system shall allow users to reset passwords.\n",
        encoding="utf-8",
    )

    first_result = main([
        "run",
        "--srs",
        str(srs),
        "--out",
        str(tmp_path / "RUN-1"),
        "--run-id",
        "RUN-20261009-181600-ab12",
        "--project-code",
        "EX",
        "--registry",
        str(registry),
    ])

    assert first_result == 0

    first_output = (
        tmp_path / "RUN-1" / "c1" / "parsed_requirements.json"
    )
    import json

    first_requirements = json.loads(first_output.read_text(encoding="utf-8"))
    first_ids = [item["requirement_id"] for item in first_requirements]

    srs.write_text(
        "1. The system shall allow users to log in.\n"
        "2. The system shall allow users to reset passwords.\n"
        "3. The system shall allow administrators to deactivate accounts.\n",
        encoding="utf-8",
    )

    second_result = main([
        "run",
        "--srs",
        str(srs),
        "--out",
        str(tmp_path / "RUN-2"),
        "--run-id",
        "RUN-20261009-181601-ab12",
        "--project-code",
        "EX",
        "--registry",
        str(registry),
    ])

    assert second_result == 0

    second_output = (
        tmp_path / "RUN-2" / "c1" / "parsed_requirements.json"
    )
    second_requirements = json.loads(
        second_output.read_text(encoding="utf-8")
    )
    second_ids = [item["requirement_id"] for item in second_requirements]

    assert first_ids == ["REQ-EX-001", "REQ-EX-002"]
    assert second_ids == ["REQ-EX-001", "REQ-EX-002", "REQ-EX-003"]


@pytest.mark.parametrize("run_id", ["RUN-1", "RUN-20261009-181600-AB12"])
def test_run_rejects_invalid_run_id(tmp_path, run_id):
    srs = tmp_path / "sample.md"
    srs.write_text("1. The system shall allow registration.\n", encoding="utf-8")

    assert main([
        "run",
        "--srs",
        str(srs),
        "--out",
        str(tmp_path / "run"),
        "--run-id",
        run_id,
    ]) == 1
    assert not (tmp_path / "run" / "c1" / "validated_requirements.json").exists()


def test_run_rejects_empty_srs_without_contract_output(tmp_path):
    srs = tmp_path / "empty.md"
    srs.write_text("", encoding="utf-8")

    assert main([
        "run",
        "--srs",
        str(srs),
        "--out",
        str(tmp_path / "run"),
        "--run-id",
        "RUN-20261009-181600-ab12",
    ]) == 1
    assert not (tmp_path / "run" / "c1" / "validated_requirements.json").exists()


def test_validated_output_has_contract_fields_and_pending_analysis(tmp_path):
    srs = tmp_path / "sample.md"
    srs.write_text("1. The system shall allow registration.\n", encoding="utf-8")

    assert main([
        "run",
        "--srs",
        str(srs),
        "--out",
        str(tmp_path / "run"),
        "--run-id",
        "RUN-20261009-181600-ab12",
    ]) == 0

    import json

    output = json.loads(
        (tmp_path / "run" / "c1" / "validated_requirements.json")
        .read_text(encoding="utf-8")
    )
    assert output["contract"] == "c1.validated-requirements"
    assert output["schema_version"] == "1.0.0"
    assert output["producer"]["component"] == "C1"
    assert output["run_id"] == "RUN-20261009-181600-ab12"
    assert output["source_document"] == {
        "name": "sample.md",
        "project_code": "EX",
        "path": "sample.md",
        "redaction_applied": False,
    }
    requirement = output["requirements"][0]
    assert requirement["defects"] == []
    assert requirement["consistency"]["status"] == "potential_conflict"
    assert requirement["validation"]["status"] == "needs_review"
    assert requirement["validation"]["checks"]["consistency"] == "skipped"
    assert requirement["human_decision"] == "pending"
    assert requirement["bdd_ready"] is False
