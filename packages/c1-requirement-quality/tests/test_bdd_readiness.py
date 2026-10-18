"""Unit tests for the deterministic BDD-readiness evaluator (bdd_readiness.py)."""

from __future__ import annotations

import pytest

from c1_requirement_quality.bdd_readiness import (
    evaluate_bdd_readiness,
    bdd_check_from_validation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_PASS_CHECKS = {
    "quality": "pass",
    "grounding": "pass",
    "consistency": "pass",
}

GOOD_TIER = "TIER_1_AUTO_REFINE"
TIER2 = "TIER_2_CLARIFY"
TIER3 = "TIER_3_ESCALATE"


def _eval(text, *, tier=GOOD_TIER, questions=None, **overrides):
    """Shorthand that passes all upstream gates unless overridden."""
    checks = {**_ALL_PASS_CHECKS, **overrides}
    return evaluate_bdd_readiness(
        text,
        quality_check=checks["quality"],
        grounding_check=checks["grounding"],
        consistency_check=checks["consistency"],
        tier=tier,
        clarification_questions=questions or [],
    )


# ---------------------------------------------------------------------------
# 1. Clear, testable requirement — should pass when all gates pass
# ---------------------------------------------------------------------------

class TestPassingRequirements:
    def test_canonical_bdd_ready_requirement_passes(self):
        result = _eval("The system shall allow users to register an account.")
        assert result["check"] == "pass"
        assert result["reasons"] == []
        assert "All BDD-readiness criteria passed" in result["explanation"]

    def test_must_modal_also_passes(self):
        result = _eval("The system must reject invalid login attempts.")
        assert result["check"] == "pass"

    def test_requirement_without_numeric_threshold_passes(self):
        # Legitimate requirements need not contain numbers.
        result = _eval("The system shall display an error message when login fails.")
        assert result["check"] == "pass"

    def test_multi_word_actor_passes(self):
        result = _eval("The application shall log all authentication events.")
        assert result["check"] == "pass"

    def test_negated_shall_not_passes(self):
        result = _eval("The system shall not allow concurrent logins from the same account.")
        assert result["check"] == "pass"

    def test_bare_user_actor_passes(self):
        result = _eval("Users shall be able to reset their password via email.")
        assert result["check"] == "pass"

    def test_requirement_with_numeric_threshold_passes(self):
        result = _eval("The system shall respond within 2 seconds under normal load.")
        assert result["check"] == "pass"


# ---------------------------------------------------------------------------
# 2. Vague / ambiguous requirements — quality gate blocks them
# ---------------------------------------------------------------------------

class TestQualityGateBlocking:
    def test_vague_requirement_blocked_by_quality_gate(self):
        result = _eval(
            "The system shall provide a suitable interface.",
            quality="fail",
        )
        assert result["check"] == "fail"
        criteria = [r["criterion"] for r in result["reasons"]]
        assert "quality_gate" in criteria

    def test_ambiguous_requirement_blocked_by_quality_gate(self):
        result = _eval(
            "The system may or may not log events.",
            quality="fail",
        )
        assert result["check"] == "fail"
        assert any(r["criterion"] == "quality_gate" for r in result["reasons"])

    def test_skipped_quality_check_blocks_promotion(self):
        result = _eval(
            "The system shall store records.",
            quality="skipped",
        )
        assert result["check"] == "fail"
        assert any(r["criterion"] == "quality_gate" for r in result["reasons"])


# ---------------------------------------------------------------------------
# 3. Missing observable outcome / obligation
# ---------------------------------------------------------------------------

class TestObligationModalChecks:
    def test_no_obligation_modal_blocks_promotion(self):
        # "should" is not an obligation-strength modal in IEEE 830.
        result = _eval("The system should send a confirmation email.")
        assert result["check"] == "fail"
        criteria = [r["criterion"] for r in result["reasons"]]
        assert "no_obligation_modal" in criteria

    def test_may_modal_is_not_sufficient(self):
        result = _eval("The system may generate a report.")
        assert result["check"] == "fail"
        assert any(r["criterion"] == "no_obligation_modal" for r in result["reasons"])

    def test_shall_without_verb_blocks_promotion(self):
        # Degenerate edge-case: "shall" with nothing after it.
        result = _eval("The system shall.")
        assert result["check"] == "fail"
        criteria = [r["criterion"] for r in result["reasons"]]
        assert "no_observable_action" in criteria or "no_obligation_modal" in criteria


# ---------------------------------------------------------------------------
# 4. Unresolved placeholders
# ---------------------------------------------------------------------------

class TestPlaceholderBlocking:
    def test_bracket_placeholder_blocks_promotion(self):
        result = _eval("The system shall respond within [timeout] seconds.")
        assert result["check"] == "fail"
        criteria = [r["criterion"] for r in result["reasons"]]
        assert "unresolved_placeholders" in criteria

    def test_tbd_placeholder_blocks_promotion(self):
        result = _eval("The system shall store data in TBD format.")
        assert result["check"] == "fail"
        assert any(r["criterion"] == "unresolved_placeholders" for r in result["reasons"])

    def test_tbc_placeholder_blocks_promotion(self):
        result = _eval("The system shall use TBC authentication method.")
        assert result["check"] == "fail"
        assert any(r["criterion"] == "unresolved_placeholders" for r in result["reasons"])

    def test_open_clarification_questions_block_promotion(self):
        result = _eval(
            "The system shall respond within 2 seconds.",
            questions=["What value should replace [timeout]?"],
        )
        assert result["check"] == "fail"
        assert any(
            r["criterion"] == "open_clarification_questions"
            for r in result["reasons"]
        )


# ---------------------------------------------------------------------------
# 5. Failed grounding or consistency checks
# ---------------------------------------------------------------------------

class TestUpstreamGateBlocking:
    def test_failed_grounding_blocks_promotion(self):
        result = _eval(
            "The system shall transfer up to 100000 dollars.",
            grounding="fail",
        )
        assert result["check"] == "fail"
        assert any(r["criterion"] == "grounding_gate" for r in result["reasons"])

    def test_unsupported_grounding_blocks_promotion(self):
        result = _eval(
            "The system shall transfer up to 100000 dollars.",
            grounding="skipped",
        )
        assert result["check"] == "fail"

    def test_failed_consistency_blocks_promotion(self):
        result = _eval(
            "The system shall allow account deletion.",
            consistency="fail",
        )
        assert result["check"] == "fail"
        assert any(r["criterion"] == "consistency_gate" for r in result["reasons"])

    def test_skipped_consistency_blocks_promotion(self):
        result = _eval(
            "The system shall allow account deletion.",
            consistency="skipped",
        )
        assert result["check"] == "fail"
        assert any(r["criterion"] == "consistency_gate" for r in result["reasons"])

    def test_multiple_failed_gates_report_all_reasons(self):
        result = _eval(
            "The system shall allow account deletion.",
            quality="fail",
            grounding="fail",
            consistency="fail",
        )
        assert result["check"] == "fail"
        criteria = [r["criterion"] for r in result["reasons"]]
        assert "quality_gate" in criteria
        assert "grounding_gate" in criteria
        assert "consistency_gate" in criteria


# ---------------------------------------------------------------------------
# 6. Pending or rejected human decisions (via can_mark_bdd_ready)
#    These are tested at the integration level in test_refinement.py, but
#    we verify the raw check result is "pass" for a clean text — the
#    human-decision gate sits on top via can_mark_bdd_ready().
# ---------------------------------------------------------------------------

class TestHumanDecisionIsASeperateGate:
    def test_clean_text_evaluates_to_pass_without_human_gate(self):
        # The evaluator itself does not know about human_decision.
        # That gate is enforced in can_mark_bdd_ready().
        result = _eval("The system shall send a notification to the user.")
        assert result["check"] == "pass"


# ---------------------------------------------------------------------------
# 7. Legitimate requirements without numeric thresholds
# ---------------------------------------------------------------------------

class TestNoFalsePositivesForLegitimateRequirements:
    def test_functional_requirement_no_numbers(self):
        result = _eval("The system shall send a confirmation email after registration.")
        assert result["check"] == "pass"

    def test_access_control_requirement(self):
        result = _eval("The system shall restrict access to admin pages to authorised users.")
        assert result["check"] == "pass"

    def test_state_transition_requirement(self):
        result = _eval("The system shall log the user out after a session expires.")
        assert result["check"] == "pass"

    def test_data_integrity_requirement(self):
        result = _eval("The system shall reject duplicate registration requests.")
        assert result["check"] == "pass"


# ---------------------------------------------------------------------------
# 8. Tier 2 and Tier 3 blocking
# ---------------------------------------------------------------------------

class TestTierGateBlocking:
    def test_tier2_blocks_bdd_promotion(self):
        result = _eval(
            "The system shall respond within [timeout] seconds.",
            tier=TIER2,
        )
        assert result["check"] == "fail"
        criteria = [r["criterion"] for r in result["reasons"]]
        assert "tier_gate" in criteria

    def test_tier3_blocks_bdd_promotion(self):
        result = _eval(
            "The system shall allow account deletion.",
            tier=TIER3,
        )
        assert result["check"] == "fail"
        assert any(r["criterion"] == "tier_gate" for r in result["reasons"])

    def test_tier1_does_not_block_promotion(self):
        # Tier 1 is safe; passing it through should not add a tier_gate reason.
        result = _eval("The system shall allow users to register.")
        criteria = [r["criterion"] for r in result["reasons"]]
        assert "tier_gate" not in criteria


# ---------------------------------------------------------------------------
# 9. No identifiable actor
# ---------------------------------------------------------------------------

class TestActorCheck:
    def test_text_without_any_actor_blocks_promotion(self):
        # Deliberately crafted to have no actor noun phrase.
        result = _eval("Shall process all incoming requests within 5 seconds.")
        assert result["check"] == "fail"
        assert any(r["criterion"] == "no_identifiable_actor" for r in result["reasons"])


# ---------------------------------------------------------------------------
# 10. bdd_check_from_validation convenience wrapper
# ---------------------------------------------------------------------------

class TestConvenienceWrapper:
    def test_wrapper_passes_clean_requirement(self):
        result = bdd_check_from_validation(
            "The system shall send a notification to the user.",
            {
                "quality": "pass",
                "grounding": "pass",
                "consistency": "pass",
            },
            tier=GOOD_TIER,
            clarification_questions=[],
        )
        assert result["check"] == "pass"

    def test_wrapper_fails_with_failed_quality(self):
        result = bdd_check_from_validation(
            "The system shall provide a suitable interface.",
            {
                "quality": "fail",
                "grounding": "pass",
                "consistency": "pass",
            },
            tier=GOOD_TIER,
            clarification_questions=[],
        )
        assert result["check"] == "fail"

    def test_wrapper_treats_missing_key_as_skipped(self):
        # If a check is missing from the dict, it defaults to "skipped" → blocks.
        result = bdd_check_from_validation(
            "The system shall allow users to log in.",
            {},  # no checks at all
            tier=GOOD_TIER,
            clarification_questions=[],
        )
        assert result["check"] == "fail"

    def test_wrapper_propagates_all_reasons(self):
        result = bdd_check_from_validation(
            "The system shall respond within [timeout].",
            {
                "quality": "fail",
                "grounding": "fail",
                "consistency": "fail",
            },
            tier=TIER2,
            clarification_questions=["What is the timeout?"],
        )
        assert result["check"] == "fail"
        criteria = {r["criterion"] for r in result["reasons"]}
        assert "quality_gate" in criteria
        assert "grounding_gate" in criteria
        assert "consistency_gate" in criteria
        assert "tier_gate" in criteria
        assert "open_clarification_questions" in criteria
        assert "unresolved_placeholders" in criteria


# ---------------------------------------------------------------------------
# 11. Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_empty_text_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            evaluate_bdd_readiness(
                "",
                quality_check="pass",
                grounding_check="pass",
                consistency_check="pass",
            )

    def test_whitespace_only_text_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            evaluate_bdd_readiness(
                "   \n\t  ",
                quality_check="pass",
                grounding_check="pass",
                consistency_check="pass",
            )
