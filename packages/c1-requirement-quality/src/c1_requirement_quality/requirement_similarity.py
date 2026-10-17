"""Backward-compatibility forwarding shim for c1_requirement_quality.ml.requirement_similarity."""
from __future__ import annotations

import sys
from c1_requirement_quality.ml import requirement_similarity as _impl
from c1_requirement_quality.ml.requirement_similarity import (
    SentenceTransformersEmbedder,
    _cosine_similarity,
    requirement_pair_diagnostics,
)

__all__ = [
    "SentenceTransformersEmbedder",
    "_cosine_similarity",
    "requirement_pair_diagnostics",
]

sys.modules[__name__] = _impl
