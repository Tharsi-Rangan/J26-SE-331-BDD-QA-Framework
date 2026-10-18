"""Deterministic BDD-readiness evaluator for C1 requirement text.

Checks whether a single requirement text is structurally suitable for
handover to Component 2 as a BDD scenario source.  This module is
intentionally conservative: it only flags issues that can be detected
from the text itself without any ML model or semantic inference.

The check result is expressed as ``"pass"`` or ``"fail"`` (matching the
``checkStatus`` enum in the frozen shared contract schema), accompanied by
an ordered list of diagnostic reason objects that explain every failed
criterion.  An empty reasons list is only possible when the check passes.

Design constraints
------------------
- No ML / embedding / NLI calls.
- Does not duplicate quality_analyser defect detection; instead it
  consumes the quality-check outcome that is already computed upstream.
- Does not require numeric thresholds: many legitimate requirements
  (e.g. "The system shall allow users to register.") contain no numbers.
- All patterns are conservative; a false-positive block is worse than a
  missed pass because it would permanently lock BDD promotion.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

# ---------------------------------------------------------------------------
# Patterns – conservative, deliberately narrow
# ---------------------------------------------------------------------------

# An actor / responsible subject: a noun phrase that could carry an obligation.
# Broadened beyond fact_extractor.py to cover non-system actors such as
# "the operator", "the administrator", "the client", "the server", etc.
_ACTOR_PATTERN = re.compile(
    r"\bthe\s+\w+\b"           # "the system", "the user", "the client" …
    r"|\busers?\b"             # bare "user" or "users"
    r"|\badministrators?\b"
    r"|\boperators?\b"
    r"|\bclients?\b"
    r"|\bservers?\b"
    r"|\bmembers?\b"
    r"|\bapplication\b"
    r"|\bservice\b"
    r"|\bsystem\b",            # bare "system" (e.g. "System shall …")
    re.IGNORECASE,
)

# Obligation modal that signals a testable system behaviour.
# "shall" and "must" are the only obligation-strength modals in IEEE 830 /
# ISO 29148 that imply a verifiable commitment.
_OBLIGATION_PATTERN = re.compile(r"\b(?:shall|must)\b", re.IGNORECASE)

# Observable action verb immediately or shortly after the obligation modal.
# We only require that *some* verb follows — we do not prescribe which verb.
_OBLIGATION_WITH_VERB_PATTERN = re.compile(
    r"\b(?:shall|must)\s+(?:not\s+)?\w+",
    re.IGNORECASE,
)

from c1_requirement_quality.lexical_patterns import PLACEHOLDER_PATTERN

_PLACEHOLDER_PATTERN = PLACEHOLDER_PATTERN

# Tier labels that block BDD promotion.
_BLOCKING_TIERS = frozenset({"TIER_2_CLARIFY", "TIER_3_ESCALATE"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_single_requirement_no_peers(consistency_result: Mapping[str, Any] | None) -> bool:
    """Return True when consistency analysis confirms there are no peer requirements to compare."""
    if not consistency_result or not isinstance(consistency_result, Mapping):
        return False
    return (
        not consistency_result.get("pairs")
        and consistency_result.get("requirements_analyzed") == 1
        and consistency_result.get("pairs_unassessed", 0) == 0
        and not consistency_result.get("conflicts")
    )


def evaluate_bdd_readiness(
    text: str,
    *,
    quality_check: str,
    grounding_check: str,
    consistency_check: str,
    consistency_result: Mapping[str, Any] | None = None,
    tier: str | None = None,
    clarification_questions: Sequence[str] | None = None,
    escalation_active: bool = False,
) -> dict[str, Any]:
    """Evaluate whether a requirement text is BDD-ready.

    Parameters
    ----------
    text:
        The final requirement text to evaluate (after any candidate
        selection).
    quality_check:
        The upstream quality-check result: ``"pass"``, ``"fail"``, or
        ``"skipped"``.  Anything other than ``"pass"`` is a blocker.
    grounding_check:
        The upstream grounding-check result (same values).
    consistency_check:
        The upstream consistency-check result (same values).  A
        ``"skipped"`` value arising from a single-requirement analysis
        (no peer pairs) is treated as a pass-through rather than a
        blocker, mirroring the behaviour of ``tier_classifier.classify_tier``.
    consistency_result:
        Optional full consistency result mapping (as returned by
        ``consistency_for_requirement``).  When supplied, the evaluator
        can detect the single-requirement case and treat a ``"skipped"``
        check as non-blocking.
    tier:
        The current tier label for the requirement.  ``TIER_2_CLARIFY``
        and ``TIER_3_ESCALATE`` are blockers.
    clarification_questions:
        Validation-unresolved questions (including invalid/deferred/waived
        closures), rather than historical question text. Any
        non-empty list is a blocker.

    Returns
    -------
    dict with keys:

    ``"check"``
        ``"pass"`` or ``"fail"`` (``checkStatus`` contract enum).
    ``"reasons"``
        List of reason dicts.  Each has ``"criterion"`` (str) and
        ``"explanation"`` (str).  Empty when check is ``"pass"``.
    ``"explanation"``
        Human-readable summary string suitable for diagnostics.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Requirement text must be a non-empty string")

    reasons: list[dict[str, str]] = []
    if escalation_active:
        reasons.append({"criterion": "active_escalation", "explanation": "An unresolved escalation requires explicit resolution and successful revalidation."})

    # ------------------------------------------------------------------
    # 1. Upstream gate results — if any upstream check has failed or is
    #    still skipped (i.e. not yet evaluated), BDD promotion is blocked.
    #    Exception: a "skipped" consistency check arising from a single-
    #    requirement analysis (no peer pairs) is treated as non-blocking,
    #    mirroring the logic in tier_classifier.classify_tier.
    # ------------------------------------------------------------------
    def _consistency_skipped_is_noop() -> bool:
        """Return True when consistency was skipped only because there are no peers."""
        return consistency_check == "skipped" and is_single_requirement_no_peers(consistency_result)

    for check_name, check_value in (
        ("quality", quality_check),
        ("grounding", grounding_check),
        ("consistency", consistency_check),
    ):
        if check_value == "pass":
            continue
        if check_name == "consistency" and _consistency_skipped_is_noop():
            # Single-requirement analysis: no peers to compare; treat as non-blocking.
            continue
        reasons.append({
            "criterion": f"{check_name}_gate",
            "explanation": (
                f"The {check_name} check has not passed "
                f"(status: '{check_value}'). "
                "All upstream gates must pass before BDD promotion."
            ),
        })

    # ------------------------------------------------------------------
    # 2. Tier gate — Tier 2 and Tier 3 requirements are not yet resolved.
    # ------------------------------------------------------------------
    if tier in _BLOCKING_TIERS:
        reasons.append({
            "criterion": "tier_gate",
            "explanation": (
                f"Requirement is classified as '{tier}'. "
                "Tier 2 requirements require clarification and Tier 3 "
                "requirements require escalation before BDD promotion."
            ),
        })

    # ------------------------------------------------------------------
    # 3. Open clarification questions
    # ------------------------------------------------------------------
    open_questions = list(clarification_questions or [])
    if open_questions:
        reasons.append({
            "criterion": "open_clarification_questions",
            "explanation": (
                f"{len(open_questions)} unresolved clarification question(s) "
                "remain. Replace all placeholders and provide answers before "
                "promoting the requirement."
            ),
        })

    # ------------------------------------------------------------------
    # 4. Unresolved placeholders in the text itself
    # ------------------------------------------------------------------
    placeholder_matches = _PLACEHOLDER_PATTERN.findall(text)
    if placeholder_matches:
        reasons.append({
            "criterion": "unresolved_placeholders",
            "explanation": (
                "The requirement text contains unresolved placeholder(s): "
                + ", ".join(repr(m) for m in placeholder_matches)
                + ". Replace all placeholders with concrete values before "
                "BDD promotion."
            ),
        })

    # ------------------------------------------------------------------
    # 5. Actor / responsible subject
    #    Many legitimate requirements are written in passive voice or use
    #    implicit subjects; we only flag complete absence of any
    #    subject-like noun phrase.
    # ------------------------------------------------------------------
    if not _ACTOR_PATTERN.search(text):
        reasons.append({
            "criterion": "no_identifiable_actor",
            "explanation": (
                "No identifiable actor or responsible entity was found in the "
                "requirement text. A BDD scenario needs a subject (e.g. "
                "'the system', 'the user', 'users') to generate a Given/When "
                "clause."
            ),
        })

    # ------------------------------------------------------------------
    # 6. Observable action or system behaviour
    #    The requirement must contain an obligation modal ('shall' or
    #    'must') followed by a verb.  'should', 'may', and 'can' are
    #    permissive, not obligatory, and cannot drive a verifiable BDD
    #    scenario on their own.
    # ------------------------------------------------------------------
    if not _OBLIGATION_WITH_VERB_PATTERN.search(text):
        if _OBLIGATION_PATTERN.search(text):
            reasons.append({
                "criterion": "no_observable_action",
                "explanation": (
                    "An obligation modal ('shall'/'must') was found but is "
                    "not followed by an action verb. The requirement must "
                    "state what the system does."
                ),
            })
        else:
            reasons.append({
                "criterion": "no_obligation_modal",
                "explanation": (
                    "No obligation modal ('shall' or 'must') was found. "
                    "A BDD-ready requirement must express a testable system "
                    "obligation. Requirements using only 'should', 'may', or "
                    "'can' are not yet ready for automated scenario generation."
                ),
            })

    # ------------------------------------------------------------------
    # Build result
    # ------------------------------------------------------------------
    if reasons:
        summary = "; ".join(r["criterion"] for r in reasons)
        return {
            "check": "fail",
            "reasons": reasons,
            "explanation": (
                f"BDD-readiness check failed ({len(reasons)} criterion/criteria): "
                f"{summary}."
            ),
        }

    return {
        "check": "pass",
        "reasons": [],
        "explanation": (
            "All BDD-readiness criteria passed: upstream gates (quality, "
            "grounding, consistency) passed; no open placeholders or "
            "clarification questions; actor and obligation identified."
        ),
    }


def bdd_check_from_validation(
    text: str,
    validation_checks: Mapping[str, str],
    tier: str | None,
    clarification_questions: Sequence[str] | None,
    *,
    consistency_result: Mapping[str, Any] | None = None,
    escalation_active: bool = False,
) -> dict[str, Any]:
    """Convenience wrapper that reads upstream check results from a validation dict.

    This is the single call-site used by ``refinement.py`` and the CLI.
    It extracts quality / grounding / consistency results from the already-
    computed ``validation.checks`` mapping and calls ``evaluate_bdd_readiness``.

    Parameters
    ----------
    consistency_result:
        Optional full consistency result mapping (from
        ``consistency_for_requirement``).  Pass this to allow the evaluator
        to distinguish a single-requirement no-peer skip from a genuinely
        unresolved analysis.
    """
    return evaluate_bdd_readiness(
        text,
        quality_check=validation_checks.get("quality", "skipped"),
        grounding_check=validation_checks.get("grounding", "skipped"),
        consistency_check=validation_checks.get("consistency", "skipped"),
        consistency_result=consistency_result,
        tier=tier,
        clarification_questions=clarification_questions,
        escalation_active=escalation_active,
    )
