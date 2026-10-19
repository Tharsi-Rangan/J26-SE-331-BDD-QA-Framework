"""Advisory ML and similarity subpackage for Component 1 requirement quality.

Contains experimental, advisory-only models and diagnostics:
- DistilBERT defect classification (Experiment 2 checkpoint)
- MiniLM requirement semantic similarity pair diagnostics
"""
from __future__ import annotations

from c1_requirement_quality.ml.ml_defect_classifier import (
    DEFAULT_MODEL_DIR,
    DEFECT_LABELS,
    EXPERIMENT2_FILES,
    EXPERIMENT2_LABELS,
    EXPERIMENT2_PROVENANCE,
    ClassificationResult,
    DefectScore,
    DistilBertDefectClassifier,
    DistilBertModelLoadError,
)
from c1_requirement_quality.ml.ml_diagnostics import (
    MIN_AVAILABLE_BYTES as ML_MIN_AVAILABLE_BYTES,
    available_memory_bytes,
    defect_diagnostics_run,
)
from c1_requirement_quality.ml.requirement_similarity import (
    requirement_pair_diagnostics,
)
from c1_requirement_quality.ml.similarity_diagnostics import (
    CACHED_REVISION,
    checkpoint_provenance,
    default_model_directory,
    similarity_diagnostics_run,
)

__all__ = [
    "ClassificationResult",
    "DefectScore",
    "DistilBertDefectClassifier",
    "DistilBertModelLoadError",
    "DEFAULT_MODEL_DIR",
    "DEFECT_LABELS",
    "EXPERIMENT2_FILES",
    "EXPERIMENT2_LABELS",
    "EXPERIMENT2_PROVENANCE",
    "ML_MIN_AVAILABLE_BYTES",
    "available_memory_bytes",
    "defect_diagnostics_run",
    "requirement_pair_diagnostics",
    "CACHED_REVISION",
    "checkpoint_provenance",
    "default_model_directory",
    "similarity_diagnostics_run",
]
