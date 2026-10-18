"""Backward-compatibility forwarding shim for c1_requirement_quality.ml.ml_defect_classifier."""
from __future__ import annotations

import sys
from c1_requirement_quality.ml import ml_defect_classifier as _impl
from c1_requirement_quality.ml.ml_defect_classifier import (
    CONTRACT_LABEL_MAP,
    DEFAULT_MODEL_DIR,
    DEFECT_LABELS,
    EXPERIMENT2_FILES,
    EXPERIMENT2_LABELS,
    EXPERIMENT2_PROVENANCE,
    LABEL_INDEX_MAP,
    TRAINING_MAX_LENGTH,
    ClassificationResult,
    DefectScore,
    DistilBertDefectClassifier,
    DistilBertModelLoadError,
    _sigmoid,
    _validate_threshold,
)

__all__ = [
    "DEFECT_LABELS",
    "LABEL_INDEX_MAP",
    "CONTRACT_LABEL_MAP",
    "DEFAULT_MODEL_DIR",
    "EXPERIMENT2_LABELS",
    "TRAINING_MAX_LENGTH",
    "EXPERIMENT2_FILES",
    "EXPERIMENT2_PROVENANCE",
    "DistilBertModelLoadError",
    "DefectScore",
    "ClassificationResult",
    "DistilBertDefectClassifier",
    "_validate_threshold",
    "_sigmoid",
]

sys.modules[__name__] = _impl
