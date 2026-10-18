"""Backward-compatibility forwarding shim for c1_requirement_quality.analysis.bdd_readiness."""
from __future__ import annotations

from c1_requirement_quality.analysis.bdd_readiness import (
    _PLACEHOLDER_PATTERN,
    bdd_check_from_validation,
    evaluate_bdd_readiness,
    is_single_requirement_no_peers,
)

__all__ = [
    "is_single_requirement_no_peers",
    "evaluate_bdd_readiness",
    "bdd_check_from_validation",
    "_PLACEHOLDER_PATTERN",
]
