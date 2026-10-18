"""Deterministic, explainable severity and remediation-priority assessments.

The labels describe specification-quality impact only. They do not estimate
business, safety, security, or operational risk.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_RULES: dict[str, tuple[str, str, str]] = {
    "incomplete": (
        "high",
        "high",
        "An explicit unresolved placeholder can leave required behavior undefined.",
    ),
    "ambiguous": (
        "high",
        "high",
        "Multiple plausible interpretations can lead to different implementations.",
    ),
    "vague": (
        "moderate",
        "normal",
        "Subjective wording makes the intended behavior or acceptance boundary unclear.",
    ),
    "non_measurable": (
        "moderate",
        "normal",
        "The stated target lacks a measurable threshold for assessing whether it is met.",
    ),
    "non_verifiable": (
        "moderate",
        "normal",
        "The stated quality lacks an objective verification criterion.",
    ),
}
_RANK = {"low": 1, "moderate": 2, "high": 3}


def assess_defects(defects: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Assess existing defect findings without changing or rescoring them.

    Priority is a local remediation ordering derived only from this severity
    rubric. No project dependency or business-impact data is inferred.
    """
    if isinstance(defects, (str, bytes)):
        raise TypeError("defects must be a sequence of defect objects")

    assessed: list[dict[str, Any]] = []
    needs_review_reasons: list[str] = []
    for index, defect in enumerate(defects):
        if not isinstance(defect, Mapping):
            raise TypeError(f"defect at index {index} must be an object")
        defect_type = defect.get("type")
        evidence = defect.get("evidence_span")
        rule = _RULES.get(defect_type) if isinstance(defect_type, str) else None
        if rule is None:
            severity, priority = "unknown", "needs_review"
            explanation = "The defect type has no approved severity rule; human review is required."
            needs_review_reasons.append(f"finding {index} has an unrecognized defect type")
        else:
            severity, priority, explanation = rule
            if not isinstance(evidence, str) or not evidence:
                priority = "needs_review"
                needs_review_reasons.append(f"finding {index} has no evidence span")
        assessed.append({
            "finding_index": index,
            "defect_type": defect_type if isinstance(defect_type, str) else "unknown",
            "evidence_span": evidence if isinstance(evidence, str) else None,
            "severity": severity,
            "priority": priority,
            "explanation": explanation,
        })

    known = [item for item in assessed if item["severity"] in _RANK]
    if not assessed:
        return {
            "status": "needs_review",
            "severity": "unknown",
            "priority": "needs_review",
            "explanation": (
                "No implemented quality rule reported a defect. This is not evidence "
                "that the requirement is defect-free; human review remains necessary."
            ),
            "findings": [],
            "review_reasons": ["no detector findings; absence of findings is inconclusive"],
        }

    overall_severity = max((item["severity"] for item in known), key=_RANK.get, default="unknown")
    if needs_review_reasons or overall_severity == "unknown":
        overall_priority = "needs_review"
        status = "needs_review"
    else:
        overall_priority = "high" if overall_severity == "high" else "normal"
        status = "assessed"
    summary = (
        f"Highest detected specification-quality severity is {overall_severity}; "
        f"remediation priority is {overall_priority}. Priority uses severity only."
    )
    return {
        "status": status,
        "severity": overall_severity,
        "priority": overall_priority,
        "explanation": summary,
        "findings": assessed,
        "review_reasons": needs_review_reasons,
    }
