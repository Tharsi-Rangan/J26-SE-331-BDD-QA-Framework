"""Backward-compatibility forwarding shim for c1_requirement_quality.ml.similarity_diagnostics."""
from __future__ import annotations

import sys
from c1_requirement_quality.ml import similarity_diagnostics as _impl
from c1_requirement_quality.ml.similarity_diagnostics import (
    CACHED_REVISION,
    DEFAULT_MODEL_NAME,
    MIN_AVAILABLE_BYTES,
    MINILM_CACHED_REVISION,
    SentenceTransformersEmbedder,
    available_memory_bytes,
    checkpoint_provenance,
    default_model_directory,
    get_minilm_cache_dir,
    requirement_pair_diagnostics,
    similarity_diagnostics_run,
)

__all__ = [
    "available_memory_bytes",
    "DEFAULT_MODEL_NAME",
    "SentenceTransformersEmbedder",
    "requirement_pair_diagnostics",
    "get_minilm_cache_dir",
    "MINILM_CACHED_REVISION",
    "CACHED_REVISION",
    "MIN_AVAILABLE_BYTES",
    "default_model_directory",
    "checkpoint_provenance",
    "similarity_diagnostics_run",
]

sys.modules[__name__] = _impl
