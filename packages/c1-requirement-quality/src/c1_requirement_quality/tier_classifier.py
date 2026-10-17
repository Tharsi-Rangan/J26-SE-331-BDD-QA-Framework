"""Deterministic C1 refinement-tier assessment from existing analyses.

Tier is a handling recommendation. It is independent of defect severity,
priority, validation status, human approval, and BDD readiness.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from c1_requirement_quality.consistency_analyser import analyse_consistency


TIER_1 = "TIER_1_AUTO_REFINE"
TIER_2 = "TIER_2_CLARIFY"
TIER_3 = "TIER_3_ESCALATE"


def classify_tier(
    quality_findings: Sequence[Mapping[str, Any]],
    grounding: Mapping[str, Any],
    consistency: Mapping[str, Any],
    *,
    original_text: str | None = None,
    candidate_text: str | None = None,
) -> dict[str, Any]:
    """Classify a requirement conservatively using quality, grounding and pairs.

    Tier 1 requires no quality findings, supported grounding with source
    evidence, and no unresolved peer comparison. Tier 2 is used whenever
    clarification or further evidence may be needed. Tier 3 is reserved for
    explicit supported contradictions; the current analyses provide no
    approved standalone threshold for calling other defects ``too broken``.
    """
    if isinstance(quality_findings, (str, bytes)):
        raise TypeError("quality_findings must be a sequence of finding objects")
    if not isinstance(grounding, Mapping) or not isinstance(consistency, Mapping):
        raise TypeError("grounding and consistency must be objects")
    if (original_text is None) != (candidate_text is None):
        raise ValueError("original_text and candidate_text must be supplied together")

    findings = [dict(item) for item in quality_findings]
    consistency_pairs = [
        item for item in consistency.get("pairs", []) if isinstance(item, Mapping)
    ]
    conflicts = [
        pair for pair in consistency_pairs
        if pair.get("classification") == "conflict"
    ]
    if consistency.get("status") == "conflict" and not conflicts:
        conflicts = [{
            "classification": "conflict",
            "explanation": "The consistency analysis reports a confirmed conflict.",
            "evidence": [],
        }]
    source_conflicts = _verified_grounding_conflicts(grounding)

    if conflicts or source_conflicts:
        reasons: list[dict[str, Any]] = []
        for pair in conflicts:
            reasons.append({
                "kind": "confirmed_requirement_conflict",
                "explanation": str(pair.get("explanation", "Explicit contradiction detected.")),
                "requirement_ids": list(pair.get("requirement_ids", [])),
                "evidence": [dict(item) for item in pair.get("evidence", []) if isinstance(item, Mapping)],
            })
        for conflict in (source_conflicts if not conflicts else []):
            reasons.append({
                "kind": "grounding_conflict",
                "explanation": str(conflict.get("explanation", "Grounding found an explicit contradiction.")),
                "claim": conflict.get("claim"),
                "evidence_chunk_id": conflict.get("evidence_chunk_id"),
                "evidence_text": conflict.get("evidence_text"),
            })
        return _assessment(
            TIER_3,
            "A supported contradiction requires human resolution before proceeding.",
            reasons,
            "assessed",
        )

    reasons = []
    for finding in findings:
        reasons.append({
            "kind": "quality_defect",
            "defect_type": finding.get("type", "unknown"),
            "explanation": finding.get("explanation", "A quality finding requires review."),
            "evidence_span": finding.get("evidence_span"),
        })

    grounding_status = grounding.get("status")
    grounding_evidence = [
        dict(item) for item in grounding.get("evidence", []) if isinstance(item, Mapping)
    ]
    if grounding_status != "supported":
        reasons.append({
            "kind": "grounding_insufficient",
            "explanation": (
                f"Grounding status is {grounding_status!r}; facts needed for a safe structural-only change "
                "are not established by the available evidence."
            ),
            "unsupported_claims": list(grounding.get("unsupported_claims", [])),
        })
    elif not grounding_evidence:
        reasons.append({
            "kind": "grounding_evidence_missing",
            "explanation": "Grounding reports support but provides no traceable evidence items.",
        })

    pair_states = [pair.get("analysis_state", "unassessed") for pair in consistency_pairs]
    pair_classifications = [pair.get("classification") for pair in consistency_pairs]
    no_peer_pairs = (
        not consistency_pairs and consistency.get("requirements_analyzed") == 1
        and consistency.get("pairs_unassessed") == 0
    )
    all_peers_consistent = bool(consistency_pairs) and all(
        state == "analyzed" and classification == "consistent"
        for state, classification in zip(pair_states, pair_classifications, strict=True)
    )
    no_consistency_uncertainty = no_peer_pairs or all_peers_consistent
    if not no_consistency_uncertainty:
        unresolved = [
            dict(pair) for pair in consistency_pairs
            if pair.get("analysis_state") != "analyzed" or pair.get("classification") != "consistent"
        ]
        reasons.append({
            "kind": "consistency_unresolved",
            "explanation": "One or more requirement pairs are potential conflicts or were not analyzable.",
            "pairs": unresolved,
        })

    candidate_is_structural_only = True
    if original_text is not None and candidate_text is not None:
        candidate_is_structural_only = (
            re.sub(r"\s+", " ", original_text).strip()
            == re.sub(r"\s+", " ", candidate_text).strip()
        )
        if not candidate_is_structural_only:
            reasons.append({
                "kind": "candidate_changes_requirement_content",
                "explanation": "Tier 1 only permits whitespace normalization; this candidate changes the original text content and needs human review.",
                "original_text": original_text,
                "candidate_text": candidate_text,
            })

    if (
        not findings and grounding_status == "supported" and grounding_evidence
        and no_consistency_uncertainty and candidate_is_structural_only
    ):
        return _assessment(
            TIER_1,
            "No quality defect was detected, the requirement has traceable SRS support, and no peer conflict was found; only meaning-preserving structural edits are suitable for this tier.",
            [{
                "kind": "safe_structural_only",
                "explanation": "No facts or behavior changes are authorized by this tier assessment.",
                "grounding_evidence": grounding_evidence,
                "consistent_pairs": [
                    dict(pair) for pair in consistency_pairs
                    if pair.get("classification") == "consistent"
                ],
            }],
            "assessed",
        )

    review_status = "needs_review" if (
        grounding_status not in {"supported", "unsupported", "partially_supported", "not_applicable"}
        or any(pair.get("analysis_state") == "unassessed" for pair in consistency_pairs)
        or not grounding_evidence and grounding_status == "supported"
    ) else "assessed"
    explanation = (
        "Clarification or additional evidence is required before missing facts or behavior can be added."
        if grounding_status != "supported" or any(item.get("type") == "incomplete" for item in findings)
        else "A detected quality defect needs human review before changing requirement meaning."
    )
    if not reasons:
        reasons.append({
            "kind": "insufficient_safe_edit_evidence",
            "explanation": "Available analyses do not establish that a change is strictly structural and meaning-preserving.",
        })
    return _assessment(TIER_2, explanation, reasons, review_status)


def _assessment(
    tier: str,
    explanation: str,
    reasons: list[dict[str, Any]],
    analysis_status: str,
) -> dict[str, Any]:
    return {
        "tier": tier,
        "analysis_status": analysis_status,
        "explanation": explanation,
        "reasons": reasons,
    }


def _verified_grounding_conflicts(grounding: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Require the deterministic pair checker to corroborate grounding conflict flags."""
    verified: list[dict[str, Any]] = []
    evidence_items = [
        item for item in grounding.get("evidence", []) if isinstance(item, Mapping)
    ]
    for conflict in grounding.get("conflicts", []):
        if not isinstance(conflict, Mapping) or not isinstance(conflict.get("claim"), str):
            continue
        candidate_ids = set(conflict.get("evidence_chunk_ids", []))
        for evidence in evidence_items:
            if evidence.get("chunk_id") not in candidate_ids or not isinstance(evidence.get("text"), str):
                continue
            pair = analyse_consistency([
                {"requirement_id": "REQ-TIER-001", "text": conflict["claim"]},
                {"requirement_id": "REQ-TIER-002", "text": evidence["text"]},
            ])["pairs"][0]
            if pair["classification"] == "conflict":
                verified.append({
                    "claim": conflict["claim"],
                    "evidence_chunk_id": evidence.get("chunk_id"),
                    "evidence_text": evidence["text"],
                    "explanation": pair["explanation"],
                })
    for diagnostic in grounding.get("diagnostics", []):
        if not isinstance(diagnostic, Mapping) or diagnostic.get("outcome") != "CONTRADICTED":
            continue
        fact = diagnostic.get("fact", {})
        fact_text = fact.get("text") if isinstance(fact, Mapping) else None
        if not isinstance(fact_text, str):
            continue
        for evidence in diagnostic.get("retrieved_evidence", []):
            if not isinstance(evidence, Mapping) or not isinstance(evidence.get("text"), str):
                continue
            pair = analyse_consistency([
                {"requirement_id": "REQ-TIER-001", "text": fact_text},
                {"requirement_id": "REQ-TIER-002", "text": evidence["text"]},
            ])["pairs"][0]
            if pair["classification"] == "conflict":
                verified.append({
                    "claim": fact_text,
                    "evidence_chunk_id": evidence.get("chunk_id"),
                    "evidence_text": evidence["text"],
                    "explanation": pair["explanation"],
                })
    return verified
