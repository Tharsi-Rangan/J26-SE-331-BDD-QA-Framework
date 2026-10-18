"""Backward-compatibility forwarding shim for c1_requirement_quality.analysis.tier_classifier."""
from __future__ import annotations

from c1_requirement_quality.analysis.tier_classifier import (
    TIER_1,
    TIER_2,
    TIER_3,
    classify_tier,
)

__all__ = [
    "TIER_1",
    "TIER_2",
    "TIER_3",
    "classify_tier",
]
