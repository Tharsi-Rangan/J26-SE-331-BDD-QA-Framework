"""Backward-compatibility forwarding shim for c1_requirement_quality.analysis.quality_analyser."""
from __future__ import annotations

from c1_requirement_quality.analysis.quality_analyser import (
    QUANTITATIVE_RELIABILITY_PATTERN,
    RULES,
    Rule,
    analyse_requirement,
    analyse_requirements,
)

__all__ = [
    "Rule",
    "RULES",
    "QUANTITATIVE_RELIABILITY_PATTERN",
    "analyse_requirement",
    "analyse_requirements",
]
