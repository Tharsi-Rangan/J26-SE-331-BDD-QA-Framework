"""Backward-compatibility forwarding shim for c1_requirement_quality.analysis.consistency_analyser."""
from __future__ import annotations

from c1_requirement_quality.analysis.consistency_analyser import (
    analyse_consistency,
    consistency_for_requirement,
)

__all__ = [
    "analyse_consistency",
    "consistency_for_requirement",
]
