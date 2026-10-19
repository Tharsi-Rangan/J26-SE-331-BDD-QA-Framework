"""Backward-compatibility forwarding shim for c1_requirement_quality.ml.ml_diagnostics."""
from __future__ import annotations

import sys
from c1_requirement_quality.ml import ml_diagnostics as _impl
from c1_requirement_quality.ml.ml_diagnostics import (
    DEFAULT_MODEL_DIR,
    EXPERIMENT2_LABELS,
    EXPERIMENT2_PROVENANCE,
    MIN_AVAILABLE_BYTES,
    DistilBertDefectClassifier,
    available_memory_bytes,
    defect_diagnostics_run,
)

__all__ = [
    "DEFAULT_MODEL_DIR",
    "EXPERIMENT2_LABELS",
    "EXPERIMENT2_PROVENANCE",
    "MIN_AVAILABLE_BYTES",
    "DistilBertDefectClassifier",
    "available_memory_bytes",
    "defect_diagnostics_run",
]

sys.modules[__name__] = _impl
