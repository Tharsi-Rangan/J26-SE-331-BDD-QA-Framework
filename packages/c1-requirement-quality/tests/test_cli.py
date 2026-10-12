import pytest

from c1_requirement_quality.cli import build_parser, main


def _run_cli_with_temporary_registry(tmp_path, argv: list[str]) -> int:
    """Keep CLI tests isolated from either persistent default registry."""
    if "--registry" not in argv:
        argv = [*argv, "--registry", str(tmp_path / "registry.json")]
    return main(argv)


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
    assert args.grounding_mode == "lexical"


def test_reads_explicit_rag_grounding_mode():
    args = build_parser().parse_args([
        "run", "--srs", "srs.md", "--out", "runs/example",
        "--run-id", "RUN-20261009-181600-ab12", "--grounding-mode", "rag",
    ])
    assert args.grounding_mode == "rag"


def test_rejects_missing_out():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--srs", "srs.md"])


def test_run_creates_c1_folder(tmp_path):
    srs = tmp_path / "sample.md"
    srs.write_text(
        "1. The system shall allow users to register.\n",
        encoding="utf-8",
    )

    assert _run_cli_with_temporary_registry(tmp_path, [
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

    result = _run_cli_with_temporary_registry(tmp_path, [
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

    first_result = _run_cli_with_temporary_registry(tmp_path, [
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

    second_result = _run_cli_with_temporary_registry(tmp_path, [
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

    assert _run_cli_with_temporary_registry(tmp_path, [
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

    assert _run_cli_with_temporary_registry(tmp_path, [
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

    assert _run_cli_with_temporary_registry(tmp_path, [
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
    # SRS text "The system shall allow registration." fires no lexical rule.
    assert requirement["defects"] == []
    assert requirement["consistency"]["status"] == "potential_conflict"
    assert requirement["validation"]["status"] == "needs_review"
    # Quality analysis is now live: a clean requirement yields "pass", not "skipped".
    assert requirement["validation"]["checks"]["quality"] == "pass"
    assert requirement["validation"]["checks"]["consistency"] == "skipped"
    assert requirement["human_decision"] == "pending"
    assert requirement["bdd_ready"] is False


def test_defective_requirement_populates_defects_and_quality_fail(tmp_path):
    """A requirement containing a lexical defect signal must surface in defects[]
    and set validation.checks.quality to 'fail'. The BDD gate must stay closed."""
    srs = tmp_path / "defective.md"
    # "may" triggers the ambiguous rule in quality_analyser.
    srs.write_text(
        "1. The system may allow users to log in.\n",
        encoding="utf-8",
    )

    assert _run_cli_with_temporary_registry(tmp_path, [
        "run",
        "--srs", str(srs),
        "--out", str(tmp_path / "run"),
        "--run-id", "RUN-20261009-181600-ab12",
    ]) == 0

    import json

    output = json.loads(
        (tmp_path / "run" / "c1" / "validated_requirements.json")
        .read_text(encoding="utf-8")
    )
    requirement = output["requirements"][0]

    # Defects must be non-empty and each entry must have the required contract keys.
    assert len(requirement["defects"]) >= 1
    for defect in requirement["defects"]:
        assert "type" in defect
        assert "detector" in defect
        assert "explanation" in defect
        assert "confidence" not in defect  # rule-based detector carries no confidence

    # quality check must be "fail" when defects are found.
    assert requirement["validation"]["checks"]["quality"] == "fail"

    # Conservative gates are unchanged: quality analysis alone does not promote readiness.
    assert requirement["validation"]["status"] == "needs_review"
    assert requirement["human_decision"] == "pending"
    assert requirement["bdd_ready"] is False


def test_clean_requirement_produces_empty_defects_and_quality_pass(tmp_path):
    """A requirement with no lexical defect signals must have defects=[] and
    validation.checks.quality='pass'. The BDD gate must stay closed."""
    srs = tmp_path / "clean.md"
    # This text is used in the quality_analyser unit test to assert zero findings.
    srs.write_text(
        "1. The system shall reject an invalid password with a validation error.\n",
        encoding="utf-8",
    )

    assert _run_cli_with_temporary_registry(tmp_path, [
        "run",
        "--srs", str(srs),
        "--out", str(tmp_path / "run"),
        "--run-id", "RUN-20261009-181600-ab12",
    ]) == 0

    import json

    output = json.loads(
        (tmp_path / "run" / "c1" / "validated_requirements.json")
        .read_text(encoding="utf-8")
    )
    requirement = output["requirements"][0]

    assert requirement["defects"] == []
    assert requirement["validation"]["checks"]["quality"] == "pass"

    # Conservative gates are unchanged: quality analysis alone does not promote readiness.
    assert requirement["validation"]["status"] == "needs_review"
    assert requirement["human_decision"] == "pending"
    assert requirement["bdd_ready"] is False


def test_quality_assessments_are_separate_and_do_not_change_readiness(tmp_path):
    import json

    srs = tmp_path / "sample.md"
    srs.write_text("1. The system may respond quickly.\n", encoding="utf-8")
    assert _run_cli_with_temporary_registry(tmp_path, [
        "run", "--srs", str(srs), "--out", str(tmp_path / "run"),
        "--run-id", "RUN-20261009-181600-ab12",
    ]) == 0
    c1_dir = tmp_path / "run" / "c1"
    validated = json.loads((c1_dir / "validated_requirements.json").read_text(encoding="utf-8"))
    sidecar = json.loads((c1_dir / "quality_assessments.json").read_text(encoding="utf-8"))

    requirement = validated["requirements"][0]
    assert requirement["original_text"] == "The system may respond quickly."
    assert requirement["bdd_ready"] is False
    assert "severity" not in requirement and "priority" not in requirement
    assert sidecar[0]["requirement_id"] == requirement["requirement_id"]
    assert sidecar[0]["assessment"]["severity"] == "high"
    assert len(sidecar[0]["assessment"]["findings"]) >= 2


def test_run_reports_explicit_consistency_conflict_with_traceable_pair_evidence(tmp_path):
    import json

    srs = tmp_path / "conflicting.md"
    first_text = "The system shall allow account deletion."
    second_text = "The system shall not allow account deletion."
    srs.write_text(f"1. {first_text}\n2. {second_text}\n", encoding="utf-8")
    out = tmp_path / "run"
    assert _run_cli_with_temporary_registry(tmp_path, [
        "run", "--srs", str(srs), "--out", str(out),
        "--run-id", "RUN-20261009-181600-ab12",
    ]) == 0
    c1_dir = out / "c1"
    validated = json.loads((c1_dir / "validated_requirements.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((c1_dir / "consistency_diagnostics.json").read_text(encoding="utf-8"))

    first, second = validated["requirements"]
    assert first["consistency"]["status"] == second["consistency"]["status"] == "conflict"
    assert first["consistency"]["conflicts"][0]["with_requirement_id"] == second["requirement_id"]
    assert first["validation"]["checks"]["consistency"] == "fail"
    assert first["tier"] == second["tier"] == "TIER_3_ESCALATE"
    assert first["bdd_ready"] is second["bdd_ready"] is False
    pair = diagnostics["pairs"][0]
    assert pair["classification"] == "conflict"
    for evidence in pair["evidence"]:
        text = next(req["original_text"] for req in validated["requirements"]
                    if req["requirement_id"] == evidence["requirement_id"])
        assert text[evidence["start_offset"] : evidence["end_offset"]] == evidence["text"]


def test_clean_supported_single_requirement_receives_tier_one(tmp_path):
    import json

    srs = tmp_path / "clean.md"
    srs.write_text("1. The system shall allow users to register.\n", encoding="utf-8")
    out = tmp_path / "run"
    assert _run_cli_with_temporary_registry(tmp_path, [
        "run", "--srs", str(srs), "--out", str(out),
        "--run-id", "RUN-20261009-181600-ab12",
    ]) == 0
    requirement = json.loads(
        (out / "c1" / "validated_requirements.json").read_text(encoding="utf-8")
    )["requirements"][0]
    tier_diagnostics = json.loads(
        (out / "c1" / "tier_diagnostics.json").read_text(encoding="utf-8")
    )
    assert requirement["tier"] == "TIER_1_AUTO_REFINE"
    assert requirement["bdd_ready"] is False
    assert tier_diagnostics[0]["assessment"]["tier"] == requirement["tier"]


def test_unsupported_grounding_receives_tier_two(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(
        "c1_requirement_quality.cli.analyse_grounding",
        lambda candidate, source: {
            "status": "unsupported", "evidence": [],
            "unsupported_claims": [candidate], "conflicts": [],
        },
    )
    srs = tmp_path / "unsupported.md"
    srs.write_text("1. The system shall allow transfers up to 5 dollars.\n", encoding="utf-8")
    out = tmp_path / "run"
    assert _run_cli_with_temporary_registry(tmp_path, [
        "run", "--srs", str(srs), "--out", str(out),
        "--run-id", "RUN-20261009-181600-ab12",
    ]) == 0
    requirement = json.loads(
        (out / "c1" / "validated_requirements.json").read_text(encoding="utf-8")
    )["requirements"][0]
    assert requirement["tier"] == "TIER_2_CLARIFY"
    assert requirement["bdd_ready"] is False


def test_grounding_supported_populates_evidence_and_grounding_pass(tmp_path):
    """A requirement fully supported by SRS text must set grounding status to 'supported',
    populate evidence with exact trace info, set validation.checks.grounding to 'pass',
    and keep BDD gates closed."""
    srs = tmp_path / "supported.md"
    srs.write_text(
        "# User Management\n"
        "The system shall allow users to register.\n"
        "1. The system shall allow users to register.\n",
        encoding="utf-8",
    )

    assert _run_cli_with_temporary_registry(tmp_path, [
        "run",
        "--srs", str(srs),
        "--out", str(tmp_path / "run"),
        "--run-id", "RUN-20261009-181600-ab12",
    ]) == 0

    import json

    output = json.loads(
        (tmp_path / "run" / "c1" / "validated_requirements.json")
        .read_text(encoding="utf-8")
    )
    requirement = output["requirements"][0]

    assert requirement["grounding"]["status"] == "supported"
    assert len(requirement["grounding"]["evidence"]) >= 1
    assert requirement["grounding"]["evidence"][0]["text"] == "The system shall allow users to register."
    assert requirement["grounding"]["evidence"][0]["section"] == "User Management"
    assert "chunk_id" in requirement["grounding"]["evidence"][0]

    # Check mapping
    assert requirement["validation"]["checks"]["grounding"] == "pass"

    # Verify no disallowed diagnostic keys leaked into grounding object
    assert "unsupported_claims" not in requirement["grounding"]
    assert "conflicts" not in requirement["grounding"]

    # Conservative gate checks
    assert requirement["validation"]["status"] == "needs_review"
    assert requirement["human_decision"] == "pending"
    assert requirement["bdd_ready"] is False


def test_grounding_unsupported_populates_unsupported_status_and_grounding_fail(tmp_path, monkeypatch):
    """When analyse_grounding returns 'unsupported', CLI must set grounding status to 'unsupported',
    have empty evidence [], set validation.checks.grounding to 'fail', and keep BDD gates closed."""
    srs = tmp_path / "unsupported.md"
    srs.write_text(
        "1. The system shall allow users to log in.\n",
        encoding="utf-8",
    )

    def mock_analyse_grounding(candidate_text: str, srs_text: str) -> dict[str, object]:
        return {
            "status": "unsupported",
            "evidence": [],
            "unsupported_claims": [candidate_text],
            "conflicts": [],
        }

    monkeypatch.setattr("c1_requirement_quality.cli.analyse_grounding", mock_analyse_grounding)

    assert _run_cli_with_temporary_registry(tmp_path, [
        "run",
        "--srs", str(srs),
        "--out", str(tmp_path / "run"),
        "--run-id", "RUN-20261009-181600-ab12",
    ]) == 0

    import json

    output = json.loads(
        (tmp_path / "run" / "c1" / "validated_requirements.json")
        .read_text(encoding="utf-8")
    )
    requirement = output["requirements"][0]

    assert requirement["grounding"]["status"] == "unsupported"
    assert requirement["grounding"]["evidence"] == []
    assert requirement["validation"]["checks"]["grounding"] == "fail"

    # Verify schema safety: diagnostic fields not leaked into contract grounding dict
    assert "unsupported_claims" not in requirement["grounding"]
    assert "conflicts" not in requirement["grounding"]

    # Conservative gate checks
    assert requirement["validation"]["status"] == "needs_review"
    assert requirement["human_decision"] == "pending"
    assert requirement["bdd_ready"] is False



def test_grounding_partially_supported_sets_grounding_fail(tmp_path):
    """A requirement with conflicting evidence in SRS text must set status to 'partially_supported'
    and validation.checks.grounding to 'fail'."""
    srs = tmp_path / "conflict.md"
    srs.write_text(
        "# Security Policy\n"
        "The system shall allow registration.\n\n"
        "1. The system shall not allow registration.\n",
        encoding="utf-8",
    )

    assert _run_cli_with_temporary_registry(tmp_path, [
        "run",
        "--srs", str(srs),
        "--out", str(tmp_path / "run"),
        "--run-id", "RUN-20261009-181600-ab12",
    ]) == 0

    import json

    output = json.loads(
        (tmp_path / "run" / "c1" / "validated_requirements.json")
        .read_text(encoding="utf-8")
    )
    requirement = output["requirements"][0]

    assert requirement["grounding"]["status"] == "partially_supported"
    assert requirement["validation"]["checks"]["grounding"] == "fail"
    assert requirement["validation"]["status"] == "needs_review"
    assert requirement["human_decision"] == "pending"
    assert requirement["bdd_ready"] is False


def test_rag_mode_keeps_internal_diagnostics_out_of_contract(tmp_path, monkeypatch):
    class FakeRAG:
        loaded_model_names = ("test-embedding-model", "test-nli-model")

        def __init__(self, srs_text, **kwargs):
            pass

        def analyse(self, text):
            return {
                "status": "unsupported", "evidence": [],
                "diagnostics": [{"outcome": "INCONCLUSIVE"}], "errors": [],
            }

    monkeypatch.setattr("c1_requirement_quality.cli.RAGGroundingAnalyser", FakeRAG)
    srs = tmp_path / "rag.md"
    srs.write_text("1. The system shall allow login.\n", encoding="utf-8")
    assert _run_cli_with_temporary_registry(tmp_path, [
        "run", "--srs", str(srs), "--out", str(tmp_path / "run"),
        "--run-id", "RUN-20261009-181600-ab12", "--grounding-mode", "rag",
    ]) == 0
    import json
    base = tmp_path / "run" / "c1"
    output = json.loads((base / "validated_requirements.json").read_text(encoding="utf-8"))
    assert output["requirements"][0]["grounding"]["status"] == "unsupported"
    assert output["producer"]["model"] == "test-embedding-model, test-nli-model"
    assert "diagnostics" not in output["requirements"][0]["grounding"]
    assert (base / "rag_diagnostics.json").is_file()


def test_lexical_default_uses_parser_text_when_srs_has_utf8_bom(tmp_path, monkeypatch):
    captured = {}

    def capture_grounding(candidate_text, srs_text):
        captured["srs_text"] = srs_text
        return {"status": "unsupported", "evidence": []}

    def rag_must_not_be_created(*args, **kwargs):
        raise AssertionError("default lexical mode must not construct the RAG analyzer")

    monkeypatch.setattr("c1_requirement_quality.cli.analyse_grounding", capture_grounding)
    monkeypatch.setattr("c1_requirement_quality.cli.RAGGroundingAnalyser", rag_must_not_be_created)
    srs = tmp_path / "bom.md"
    srs.write_bytes(
        "\ufeff# Security\n1. The system shall require login.\n".encode("utf-8")
    )

    assert _run_cli_with_temporary_registry(tmp_path, [
        "run", "--srs", str(srs), "--out", str(tmp_path / "run"),
        "--run-id", "RUN-20261009-181600-ab12",
    ]) == 0
    assert captured["srs_text"] == "# Security\n1. The system shall require login.\n"


def test_rag_model_load_failure_stays_internal_and_keeps_readiness_closed(tmp_path, monkeypatch):
    class FailedRAG:
        loaded_model_names = ()

        def __init__(self, srs_text, **kwargs):
            pass

        def analyse(self, text):
            message = (
                "embedding model 'sentence-transformers/all-MiniLM-L6-v2' "
                "could not be loaded locally: cache missing"
            )
            return {
                "status": "unsupported",
                "evidence": [],
                "diagnostics": [{
                    "outcome": "ERROR",
                    "component": "embedding",
                    "model": "sentence-transformers/all-MiniLM-L6-v2",
                    "diagnostic": message,
                }],
                "errors": [message],
            }

    monkeypatch.setattr("c1_requirement_quality.cli.RAGGroundingAnalyser", FailedRAG)
    srs = tmp_path / "missing-model.md"
    srs.write_text("1. The system shall allow login.\n", encoding="utf-8")
    out = tmp_path / "run"
    assert _run_cli_with_temporary_registry(tmp_path, [
        "run", "--srs", str(srs), "--out", str(out),
        "--run-id", "RUN-20261009-181600-ab12", "--grounding-mode", "rag",
    ]) == 0

    import json

    c1_dir = out / "c1"
    validated = json.loads((c1_dir / "validated_requirements.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((c1_dir / "rag_diagnostics.json").read_text(encoding="utf-8"))
    requirement = validated["requirements"][0]
    assert requirement["grounding"] == {"status": "unsupported", "evidence": []}
    assert requirement["bdd_ready"] is False
    assert requirement["human_decision"] == "pending"
    assert "model" not in validated["producer"]
    assert diagnostics[0]["diagnostics"][0]["component"] == "embedding"
    assert diagnostics[0]["diagnostics"][0]["model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert "cache missing" in diagnostics[0]["errors"][0]
