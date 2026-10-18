"""Backward-compatibility forwarding shim for c1_requirement_quality.analysis.grounding_analyser."""
from __future__ import annotations

from c1_requirement_quality.analysis.grounding_analyser import (
    CLAIM_SEPARATOR,
    HEADING_PATTERN,
    NEGATION_TOKENS,
    TOKEN_PATTERN,
    analyse_grounding,
)

__all__ = [
    "HEADING_PATTERN",
    "CLAIM_SEPARATOR",
    "TOKEN_PATTERN",
    "NEGATION_TOKENS",
    "analyse_grounding",
]
