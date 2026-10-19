"""Focused tests for Stage 4F.1A architecture foundation, contract validation, and model path resolution."""
from __future__ import annotations

from pathlib import Path

import pytest

from c1_requirement_quality import cli
from c1_requirement_quality.contract import (
    get_schema_dir,
    validate_contract_artifact,
    _validate_contract_artifact,
)
from c1_requirement_quality.model_paths import (
    MINILM_CACHED_REVISION,
    DEBERTA_NLI_CACHED_REVISION,
    get_package_root,
    get_models_dir,
    get_distilbert_model_dir,
    get_minilm_cache_dir,
    get_deberta_nli_cache_dir,
)
from c1_requirement_quality.similarity_diagnostics import (
    CACHED_REVISION as SIM_CACHED_REVISION,
    default_model_directory,
)


def _valid_minimal_artifact() -> dict:
    return {
        "contract": "c1.validated-requirements",
        "schema_version": "1.0.0",
        "producer": {
            "component": "C1",
            "tool_version": "0.1.0",
        },
        "run_id": "RUN-20261009-181600-ab12",
        "generated_at": "2026-10-09T18:16:00Z",
        "source_document": {
            "name": "SRS.md",
            "project_code": "EX",
            "path": "SRS.md",
            "redaction_applied": False,
        },
        "requirements": [
            {
                "requirement_id": "REQ-EX-001",
                "source": {
                    "section": "Requirements",
                    "line": 1,
                },
                "original_text": "The system shall log in.",
                "defects": [],
                "tier": "TIER_1_AUTO_REFINE",
                "grounding": {
                    "status": "supported",
                    "evidence": [{"chunk_id": "SRS-L0001-L0001", "text": "The system shall log in."}],
                },
                "consistency": {
                    "status": "potential_conflict",
                    "related_requirement_ids": [],
                    "conflicts": [],
                },
                "validation": {
                    "status": "needs_review",
                    "checks": {
                        "quality": "pass",
                        "grounding": "pass",
                        "consistency": "skipped",
                        "bdd_readiness": "skipped",
                    },
                },
                "human_decision": "pending",
                "final_text": "The system shall log in.",
                "bdd_ready": False,
            }
        ],
    }


def test_schema_directory_resolution():
    schema_dir = get_schema_dir()
    assert schema_dir.is_dir(), f"Schema directory must exist: {schema_dir}"
    assert (schema_dir / "c1-validated-requirements.schema.json").is_file()
    assert (schema_dir / "common.schema.json").is_file()


def test_contract_artifact_validation_success():
    artifact = _valid_minimal_artifact()
    validate_contract_artifact(artifact)
    # Alias must behave identically
    _validate_contract_artifact(artifact)
    cli._validate_contract_artifact(artifact)


def test_contract_artifact_validation_failure_on_invalid_data():
    invalid_artifact = _valid_minimal_artifact()
    invalid_artifact["requirements"][0]["bdd_ready"] = "not-a-boolean"
    with pytest.raises(ValueError, match="C1 contract validation failed"):
        validate_contract_artifact(invalid_artifact)


def test_package_root_detection(tmp_path, monkeypatch):
    from c1_requirement_quality import model_paths
    root = tmp_path / "checkout"
    module = root / "src/c1_requirement_quality/model_paths.py"
    module.parent.mkdir(parents=True)
    (root / "pyproject.toml").touch()
    monkeypatch.setattr(model_paths, "__file__", str(module))
    assert get_package_root() == root


def test_distilbert_path_compatibility(tmp_path, monkeypatch):
    from c1_requirement_quality import model_paths
    root = tmp_path / "package"
    monkeypatch.setattr(model_paths, "get_package_root", lambda: root)
    monkeypatch.delenv("C1_MODELS_DIR", raising=False)
    expected_default = root / "models" / "distilbert-requirement-defects"
    assert get_distilbert_model_dir() == expected_default

    # Test override via C1_MODELS_DIR
    custom_models = tmp_path / "custom-models"
    custom_models.mkdir()
    monkeypatch.setenv("C1_MODELS_DIR", str(custom_models))
    assert get_models_dir() == custom_models


def test_minilm_cache_path_compatibility(tmp_path, monkeypatch):
    from c1_requirement_quality import model_paths
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    monkeypatch.setattr(model_paths, "get_package_root", lambda: tmp_path / "repo/packages/c1")
    assert SIM_CACHED_REVISION == MINILM_CACHED_REVISION
    minilm_dir = get_minilm_cache_dir()
    assert minilm_dir.name == MINILM_CACHED_REVISION
    assert default_model_directory() == minilm_dir


def test_deberta_nli_cache_detection(tmp_path, monkeypatch):
    from c1_requirement_quality import model_paths
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    monkeypatch.setenv("C1_MODELS_DIR", str(tmp_path / "models"))
    (tmp_path / "models").mkdir()
    monkeypatch.setattr(model_paths, "get_package_root", lambda: tmp_path / "repo/packages/c1")
    assert get_deberta_nli_cache_dir() is None
    local = tmp_path / "models/cross-encoder-nli-deberta-v3-small"
    local.mkdir()
    assert get_deberta_nli_cache_dir() == local
    primary = tmp_path / "hub/models--cross-encoder--nli-deberta-v3-small/snapshots" / DEBERTA_NLI_CACHED_REVISION
    primary.mkdir(parents=True)
    assert get_deberta_nli_cache_dir() == primary


def test_ml_subpackage_exports():
    """Verify that c1_requirement_quality.ml exports the expected public symbols."""
    import c1_requirement_quality.ml as ml_pkg
    assert hasattr(ml_pkg, "DistilBertDefectClassifier")
    assert hasattr(ml_pkg, "DistilBertModelLoadError")
    assert hasattr(ml_pkg, "DEFAULT_MODEL_DIR")
    assert hasattr(ml_pkg, "DEFECT_LABELS")
    assert hasattr(ml_pkg, "defect_diagnostics_run")
    assert hasattr(ml_pkg, "available_memory_bytes")
    assert hasattr(ml_pkg, "requirement_pair_diagnostics")
    assert hasattr(ml_pkg, "similarity_diagnostics_run")
    assert hasattr(ml_pkg, "checkpoint_provenance")
    assert hasattr(ml_pkg, "default_model_directory")


def test_ml_legacy_shims_forward_correctly():
    """Verify that legacy import paths forward to the ml subpackage implementations."""
    import c1_requirement_quality.ml_defect_classifier as legacy_classifier
    import c1_requirement_quality.ml.ml_defect_classifier as subpkg_classifier
    assert legacy_classifier.DistilBertDefectClassifier is subpkg_classifier.DistilBertDefectClassifier
    assert legacy_classifier.DEFAULT_MODEL_DIR == subpkg_classifier.DEFAULT_MODEL_DIR
    assert legacy_classifier.EXPERIMENT2_FILES == subpkg_classifier.EXPERIMENT2_FILES

    import c1_requirement_quality.ml_diagnostics as legacy_diagnostics
    import c1_requirement_quality.ml.ml_diagnostics as subpkg_diagnostics
    assert legacy_diagnostics.defect_diagnostics_run is subpkg_diagnostics.defect_diagnostics_run
    assert legacy_diagnostics.available_memory_bytes is subpkg_diagnostics.available_memory_bytes

    import c1_requirement_quality.requirement_similarity as legacy_sim
    import c1_requirement_quality.ml.requirement_similarity as subpkg_sim
    assert legacy_sim.requirement_pair_diagnostics is subpkg_sim.requirement_pair_diagnostics

    import c1_requirement_quality.similarity_diagnostics as legacy_sim_diag
    import c1_requirement_quality.ml.similarity_diagnostics as subpkg_sim_diag
    assert legacy_sim_diag.similarity_diagnostics_run is subpkg_sim_diag.similarity_diagnostics_run
    assert legacy_sim_diag.checkpoint_provenance is subpkg_sim_diag.checkpoint_provenance
    assert legacy_sim_diag.default_model_directory is subpkg_sim_diag.default_model_directory


def test_placeholder_pattern_consolidation():
    """Verify that bdd_readiness and refinement share the canonical lexical pattern."""
    from c1_requirement_quality.lexical_patterns import PLACEHOLDER_PATTERN
    from c1_requirement_quality.refinement import PLACEHOLDER_PATTERN as REF_PATTERN
    from c1_requirement_quality.bdd_readiness import _PLACEHOLDER_PATTERN as BDD_PATTERN

    assert REF_PATTERN is PLACEHOLDER_PATTERN
    assert BDD_PATTERN is PLACEHOLDER_PATTERN

    sample = "The system shall display [VALUE] before TBD deadline."
    assert PLACEHOLDER_PATTERN.findall(sample) == ["[VALUE]", "TBD"]


def test_cosine_similarity_exposure():
    """Verify that cosine_similarity is public and _cosine_similarity alias is preserved."""
    from c1_requirement_quality.rag.retriever import cosine_similarity, _cosine_similarity
    assert cosine_similarity is _cosine_similarity
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_local_nli_default_model_alignment():
    """Verify that LocalNLI uses DEBERTA_NLI_MODEL_NAME from model_paths."""
    from c1_requirement_quality.rag.verifier import LocalNLI
    from c1_requirement_quality.model_paths import DEBERTA_NLI_MODEL_NAME
    nli = LocalNLI()
    assert nli.model_name == DEBERTA_NLI_MODEL_NAME


def test_analysis_subpackage_exports():
    """Verify that c1_requirement_quality.analysis exposes public analyzers and types."""
    import c1_requirement_quality.analysis as analysis_pkg

    # Quality exports
    assert hasattr(analysis_pkg, "Rule")
    assert hasattr(analysis_pkg, "RULES")
    assert hasattr(analysis_pkg, "QUANTITATIVE_RELIABILITY_PATTERN")
    assert hasattr(analysis_pkg, "analyse_requirement")
    assert hasattr(analysis_pkg, "analyse_requirements")

    # Grounding exports
    assert hasattr(analysis_pkg, "analyse_grounding")

    # Consistency exports
    assert hasattr(analysis_pkg, "analyse_consistency")
    assert hasattr(analysis_pkg, "consistency_for_requirement")

    # Tier classifier exports
    assert hasattr(analysis_pkg, "TIER_1")
    assert hasattr(analysis_pkg, "TIER_2")
    assert hasattr(analysis_pkg, "TIER_3")
    assert hasattr(analysis_pkg, "classify_tier")

    # BDD readiness exports
    assert hasattr(analysis_pkg, "is_single_requirement_no_peers")
    assert hasattr(analysis_pkg, "evaluate_bdd_readiness")
    assert hasattr(analysis_pkg, "bdd_check_from_validation")


def test_analysis_legacy_shims_forward_correctly():
    """Verify that legacy root modules forward to analysis subpackage implementations."""
    import c1_requirement_quality.quality_analyser as legacy_qa
    import c1_requirement_quality.analysis.quality_analyser as subpkg_qa
    assert legacy_qa.Rule is subpkg_qa.Rule
    assert legacy_qa.RULES is subpkg_qa.RULES
    assert legacy_qa.QUANTITATIVE_RELIABILITY_PATTERN is subpkg_qa.QUANTITATIVE_RELIABILITY_PATTERN
    assert legacy_qa.analyse_requirement is subpkg_qa.analyse_requirement
    assert legacy_qa.analyse_requirements is subpkg_qa.analyse_requirements

    import c1_requirement_quality.grounding_analyser as legacy_ga
    import c1_requirement_quality.analysis.grounding_analyser as subpkg_ga
    assert legacy_ga.analyse_grounding is subpkg_ga.analyse_grounding
    assert legacy_ga.HEADING_PATTERN is subpkg_ga.HEADING_PATTERN
    assert legacy_ga.CLAIM_SEPARATOR is subpkg_ga.CLAIM_SEPARATOR
    assert legacy_ga.TOKEN_PATTERN is subpkg_ga.TOKEN_PATTERN
    assert legacy_ga.NEGATION_TOKENS is subpkg_ga.NEGATION_TOKENS

    import c1_requirement_quality.consistency_analyser as legacy_ca
    import c1_requirement_quality.analysis.consistency_analyser as subpkg_ca
    assert legacy_ca.analyse_consistency is subpkg_ca.analyse_consistency
    assert legacy_ca.consistency_for_requirement is subpkg_ca.consistency_for_requirement

    import c1_requirement_quality.tier_classifier as legacy_tc
    import c1_requirement_quality.analysis.tier_classifier as subpkg_tc
    assert legacy_tc.TIER_1 is subpkg_tc.TIER_1
    assert legacy_tc.TIER_2 is subpkg_tc.TIER_2
    assert legacy_tc.TIER_3 is subpkg_tc.TIER_3
    assert legacy_tc.classify_tier is subpkg_tc.classify_tier

    import c1_requirement_quality.bdd_readiness as legacy_br
    import c1_requirement_quality.analysis.bdd_readiness as subpkg_br
    assert legacy_br.is_single_requirement_no_peers is subpkg_br.is_single_requirement_no_peers
    assert legacy_br.evaluate_bdd_readiness is subpkg_br.evaluate_bdd_readiness
    assert legacy_br.bdd_check_from_validation is subpkg_br.bdd_check_from_validation
    assert legacy_br._PLACEHOLDER_PATTERN is subpkg_br._PLACEHOLDER_PATTERN
