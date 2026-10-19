"""Analysis subpackage for Component 1 requirement quality and readiness.

Provides deterministic analyzers:
- quality_analyser: rule-based lexical quality checks
- grounding_analyser: conservative textual SRS claim grounding
- consistency_analyser: cross-requirement consistency and contradiction checks
- tier_classifier: conservative refinement tier recommendation
- bdd_readiness: BDD scenario generation eligibility evaluation
"""

from __future__ import annotations

from c1_requirement_quality.analysis.bdd_readiness import (
    bdd_check_from_validation,
    evaluate_bdd_readiness,
    is_single_requirement_no_peers,
)
from c1_requirement_quality.analysis.consistency_analyser import (
    analyse_consistency,
    consistency_for_requirement,
)
from c1_requirement_quality.analysis.grounding_analyser import (
    analyse_grounding,
)
from c1_requirement_quality.analysis.quality_analyser import (
    QUANTITATIVE_RELIABILITY_PATTERN,
    RULES,
    Rule,
    analyse_requirement,
    analyse_requirements,
)
from c1_requirement_quality.analysis.tier_classifier import (
    TIER_1,
    TIER_2,
    TIER_3,
    classify_tier,
)

__all__ = [
    # Quality
    "Rule",
    "RULES",
    "QUANTITATIVE_RELIABILITY_PATTERN",
    "analyse_requirement",
    "analyse_requirements",
    # Grounding
    "analyse_grounding",
    # Consistency
    "analyse_consistency",
    "consistency_for_requirement",
    # Tier classification
    "TIER_1",
    "TIER_2",
    "TIER_3",
    "classify_tier",
    # BDD readiness
    "is_single_requirement_no_peers",
    "evaluate_bdd_readiness",
    "bdd_check_from_validation",
]
