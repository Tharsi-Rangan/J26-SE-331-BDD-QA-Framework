"""Conservative candidate and human-decision processing for C1.

This module manages user-authored alternatives. It does not generate rewrites,
infer clarification answers, or assign refinement tiers.
"""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping
from typing import Any

from c1_requirement_quality.bdd_readiness import (
    bdd_check_from_validation,
    is_single_requirement_no_peers,
)
from c1_requirement_quality.grounding_analyser import analyse_grounding
from c1_requirement_quality.consistency_analyser import analyse_consistency, consistency_for_requirement
from c1_requirement_quality.quality_analyser import analyse_requirement
from c1_requirement_quality.severity_priority import assess_defects
from c1_requirement_quality.tier_classifier import classify_tier
from c1_requirement_quality.validation_lifecycle import (
    grounded_current, clarification_resolution, validation_signature,
)

DECISIONS = frozenset({"approved", "rejected", "edited", "pending", "not_required"})
ACCEPTED_DECISIONS = frozenset({"approved", "edited", "not_required"})
REQUIRED_READINESS_CHECKS = ("quality", "grounding", "consistency", "bdd_readiness")
PLACEHOLDER_PATTERN = re.compile(r"\[[^\]]+\]|\bTBD\b|\bTBC\b", re.IGNORECASE)


def stable_candidate_id(requirement_id: str, text: str) -> str:
    """Return a deterministic candidate ID scoped to a requirement and exact text."""
    if not requirement_id or not isinstance(text, str) or not text.strip():
        raise ValueError("requirement_id and non-empty candidate text are required")
    digest = hashlib.sha256(f"{requirement_id}\0{text}".encode("utf-8")).hexdigest()
    return f"CAND-{digest}"


def clarification_questions_for(text: str) -> list[str]:
    """Ask about explicit placeholders only; never fill them with inferred values."""
    questions: list[str] = []
    for match in PLACEHOLDER_PATTERN.finditer(text):
        marker = match.group(0)
        if marker.startswith("["):
            question = f"What value or rule should replace {marker}?"
        else:
            question = f"What information should replace {marker}?"
        if question not in questions:
            questions.append(question)
    return questions


def can_mark_bdd_ready(
    validation_status: str,
    checks: Mapping[str, str],
    human_decision: str,
    *,
    consistency_result: Mapping[str, Any] | None = None,
) -> bool:
    """Apply the frozen readiness guard without supplying missing policy checks."""
    consistency_satisfied = (
        checks.get("consistency") == "pass"
        or (
            checks.get("consistency") == "skipped"
            and is_single_requirement_no_peers(consistency_result)
        )
    )
    return (
        validation_status == "passed"
        and human_decision in ACCEPTED_DECISIONS
        and checks.get("quality") == "pass"
        and checks.get("grounding") == "pass"
        and checks.get("bdd_readiness") == "pass"
        and consistency_satisfied
    )


def _require_text_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise ValueError(f"{field} entries must not be empty")
    return value


def _candidate_index(requirement: dict[str, Any]) -> dict[str, str]:
    candidates = requirement.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("requirement candidates must be a list")
    result: dict[str, str] = {}
    text_to_id: dict[str, str] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("each candidate must be an object")
        candidate_id, text = candidate.get("candidate_id"), candidate.get("text")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError("each candidate requires a non-empty candidate_id")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("each candidate requires non-empty text")
        if candidate_id in result and result[candidate_id] != text:
            raise ValueError(f"candidate ID collision: {candidate_id}")
        if text in text_to_id and text_to_id[text] != candidate_id:
            raise ValueError("duplicate candidate text has different candidate IDs")
        result[candidate_id] = text
        text_to_id[text] = candidate_id
    return result


def _add_candidate(
    requirement_id: str,
    original_text: str,
    candidates: list[dict[str, Any]],
    text: str,
) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("candidate text must not be empty")
    if text == original_text:
        raise ValueError("candidate text must differ from original_text")

    candidate_id = stable_candidate_id(requirement_id, text)
    by_id = {str(candidate.get("candidate_id")): candidate for candidate in candidates}
    for existing in candidates:
        if existing.get("text") == text:
            return str(existing["candidate_id"])
    if candidate_id in by_id and by_id[candidate_id].get("text") != text:
        raise ValueError(f"candidate ID collision: {candidate_id}")
    candidates.append({"candidate_id": candidate_id, "text": text})
    return candidate_id


def _validate_answers(value: Any, questions: list[str]) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("clarification_answers must be a list")
    answers: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each clarification answer must be an object")
        question, answer = item.get("question"), item.get("answer")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("each clarification answer requires a question")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("clarification answers must not be empty")
        if question not in questions:
            raise ValueError("answer question must match a recorded clarification question")
        answers.append({"question": question, "answer": answer})
    return answers


def _evaluate_candidate(text: str, srs_text: str, original_text: str | None = None,
                        workflow_record: dict[str, Any] | None = None) -> dict[str, Any]:
    findings = analyse_requirement(text)
    grounding = grounded_current(text, srs_text, original_text, workflow_record)
    grounding_status = grounding.get("status")
    if grounding_status == "supported":
        grounding_check = "pass"
    elif grounding_status in {"unsupported", "partially_supported"}:
        grounding_check = "fail"
    else:
        grounding_check = "skipped"
    return {
        "quality_findings": findings,
        "severity_priority": assess_defects(findings),
        "quality_check": "fail" if findings else "pass",
        "grounding": grounding,
        "grounding_check": grounding_check,
    }


def _consistency_with_candidate(
    requirement_id: str,
    candidate_text: str,
    requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    comparison_rows = []
    for requirement in requirements:
        other_id = requirement.get("requirement_id")
        text = candidate_text if other_id == requirement_id else requirement.get(
            "final_text", requirement.get("original_text")
        )
        comparison_rows.append({"requirement_id": other_id, "text": text})
    analysis = analyse_consistency(comparison_rows)
    return consistency_for_requirement(requirement_id, analysis)


def _candidate_validation(
    evaluation: Mapping[str, Any],
    consistency: Mapping[str, Any],
    *,
    text: str,
    tier: str | None = None,
    clarification_questions: list[str] | None = None,
    escalation_active: bool = False,
) -> dict[str, Any]:
    """Record independent candidate checks including BDD-readiness."""
    checks: dict[str, str] = {
        "quality": str(evaluation["quality_check"]),
        "grounding": str(evaluation["grounding_check"]),
        "consistency": str(consistency["check"]),
        "bdd_readiness": "skipped",  # provisional; overwritten below
    }
    bdd_result = bdd_check_from_validation(
        text,
        checks,
        tier=tier,
        clarification_questions=clarification_questions,
        consistency_result=consistency,
        escalation_active=escalation_active,
    )
    checks["bdd_readiness"] = bdd_result["check"]
    status = "failed" if "fail" in checks.values() else "needs_review"
    # Candidate evaluation never implies human approval.
    ready = can_mark_bdd_ready(status, checks, "pending")
    return {
        "status": status,
        "checks": checks,
        "bdd_readiness": {
            "check": bdd_result["check"],
            "bdd_ready": ready,
            "reasons": bdd_result["reasons"],
            "explanation": bdd_result["explanation"],
        },
    }


def process_refinement_actions(
    validated_requirements: dict[str, Any],
    actions: dict[str, Any],
    srs_text: str,
    *,
    workflow_records: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply explicit user-authored candidates and decisions to a C1 artifact.

    The returned sidecar diagnostics contain candidate analyses and supplied
    clarification answers. Only schema-approved fields are written to the
    validated requirements object.
    """
    if not isinstance(validated_requirements, dict) or not isinstance(actions, dict):
        raise ValueError("validated requirements and actions must be JSON objects")
    if validated_requirements.get("contract") != "c1.validated-requirements":
        raise ValueError("input is not a C1 validated-requirements artifact")
    if validated_requirements.get("schema_version") != "1.0.0":
        raise ValueError("only the frozen C1 contract schema version 1.0.0 is supported")
    if not isinstance(srs_text, str):
        raise ValueError("srs_text must be a string")

    requirement_rows = validated_requirements.get("requirements")
    action_rows = actions.get("requirements")
    if set(actions) != {"requirements"}:
        raise ValueError("actions may contain only the requirements list")
    if not isinstance(requirement_rows, list) or not isinstance(action_rows, list):
        raise ValueError("requirements must be lists in both input objects")

    output = copy.deepcopy(validated_requirements)
    baseline_requirements = copy.deepcopy(requirement_rows)
    by_requirement_id: dict[str, dict[str, Any]] = {}
    for requirement in output["requirements"]:
        if not isinstance(requirement, dict):
            raise ValueError("each requirement must be an object")
        requirement_id = requirement.get("requirement_id")
        if not isinstance(requirement_id, str) or requirement_id in by_requirement_id:
            raise ValueError("requirement IDs must be present and unique")
        by_requirement_id[requirement_id] = requirement

    seen_action_ids: set[str] = set()
    diagnostics: list[dict[str, Any]] = []
    allowed_action_fields = {
        "requirement_id",
        "clarification_questions",
        "clarification_answers",
        "candidate_texts",
        "selected_candidate_id",
        "selected_candidate_text",
        "human_decision",
        "edited_text",
    }
    for action in action_rows:
        if not isinstance(action, dict):
            raise ValueError("each refinement action must be an object")
        unknown_fields = set(action) - allowed_action_fields
        if unknown_fields:
            raise ValueError(f"unsupported refinement action fields: {sorted(unknown_fields)}")
        requirement_id = action.get("requirement_id")
        if not isinstance(requirement_id, str) or requirement_id not in by_requirement_id:
            raise ValueError(f"unknown requirement_id: {requirement_id}")
        if requirement_id in seen_action_ids:
            raise ValueError(f"duplicate action for requirement_id: {requirement_id}")
        seen_action_ids.add(requirement_id)

        requirement = by_requirement_id[requirement_id]
        original_text = requirement.get("original_text")
        if not isinstance(original_text, str) or not original_text.strip():
            raise ValueError(f"{requirement_id} has invalid original_text")

        questions = list(dict.fromkeys(
            clarification_questions_for(original_text)
            + _require_text_list(requirement.get("clarification_questions", []), "existing clarification_questions")
            + _require_text_list(action.get("clarification_questions", []), "clarification_questions")
        ))
        answers = _validate_answers(action.get("clarification_answers", []), questions)

        candidates = copy.deepcopy(requirement.get("candidates", []))
        _candidate_index({"candidates": candidates})
        candidate_texts = _require_text_list(action.get("candidate_texts", []), "candidate_texts")
        for text in candidate_texts:
            _add_candidate(requirement_id, original_text, candidates, text)

        previous_selected_id = requirement.get("selected_candidate_id")
        explicit_decision = "human_decision" in action
        decision = action.get("human_decision", requirement.get("human_decision", "pending"))
        if decision not in DECISIONS:
            raise ValueError(f"invalid human_decision: {decision}")
        if not explicit_decision and (
            action.get("selected_candidate_id", previous_selected_id) != previous_selected_id
            or "selected_candidate_text" in action and action["selected_candidate_text"] != _candidate_index(requirement).get(previous_selected_id)
            or "edited_text" in action and action["edited_text"] != _candidate_index(requirement).get(previous_selected_id)
        ):
            decision = "pending"

        edited_text = action.get("edited_text")
        if decision == "edited":
            if not explicit_decision and edited_text is None:
                edited_text = _candidate_index(requirement).get(previous_selected_id)
            if not isinstance(edited_text, str) or not edited_text.strip():
                raise ValueError("edited decision requires non-empty edited_text")
            selected_id = _add_candidate(requirement_id, original_text, candidates, edited_text)
        else:
            selected_id = action.get("selected_candidate_id", requirement.get("selected_candidate_id"))
            selected_text = action.get("selected_candidate_text", action.get("edited_text"))
            if selected_text is not None:
                if not isinstance(selected_text, str) or not selected_text.strip():
                    raise ValueError("selected_candidate_text must not be empty")
                selected_id = _add_candidate(requirement_id, original_text, candidates, selected_text)
            elif selected_id is not None and not isinstance(selected_id, str):
                raise ValueError("selected_candidate_id must be a string or null")

        candidate_by_id = _candidate_index({"candidates": candidates})
        if selected_id is not None and selected_id not in candidate_by_id:
            raise ValueError(f"selected candidate does not exist: {selected_id}")
        if not explicit_decision and selected_id != previous_selected_id:
            # A new selection is not an approval, even if the source artifact
            # records an earlier decision for a different candidate.
            decision = "pending"
        if decision == "approved" and selected_id is None:
            raise ValueError("approved decision requires a selected candidate")
        if decision == "not_required" and "human_decision" not in action and requirement.get("human_decision") != "not_required":
            raise ValueError("not_required must be explicitly supplied by a human action")

        candidate_diagnostics = []
        for candidate in candidates:
            record = workflow_records.get(requirement_id) if workflow_records else None
            candidate_resolution = clarification_resolution(record, original_text, questions)
            candidate_escalation = bool(record.get("escalation_active") if record else requirement.get("tier") == "TIER_3_ESCALATE")
            evaluation = _evaluate_candidate(candidate["text"], srs_text, original_text, record)
            candidate_consistency = _consistency_with_candidate(
                requirement_id, candidate["text"], baseline_requirements
            )
            candidate_tier_result = classify_tier(
                evaluation["quality_findings"],
                evaluation["grounding"],
                candidate_consistency,
                original_text=original_text,
                candidate_text=candidate["text"],
                human_reviewed=(decision in ACCEPTED_DECISIONS and candidate["candidate_id"] == selected_id
                                and not candidate_resolution["unresolved_questions"] and not candidate_escalation),
                unresolved_clarification=bool(candidate_resolution["unresolved_questions"]),
            )
            candidate_validation = _candidate_validation(
                evaluation,
                candidate_consistency,
                text=candidate["text"],
                tier=candidate_tier_result["tier"],
                clarification_questions=candidate_resolution["unresolved_questions"] + clarification_questions_for(candidate["text"]),
                escalation_active=candidate_escalation,
            )
            candidate_diagnostics.append({
                "candidate_id": candidate["candidate_id"],
                "text": candidate["text"],
                **evaluation,
                "consistency": candidate_consistency,
                "validation": candidate_validation,
                "bdd_readiness": candidate_validation["bdd_readiness"],
                "tier": candidate_tier_result,
            })

        requirement["clarification_questions"] = questions
        requirement["candidates"] = candidates
        requirement["selected_candidate_id"] = selected_id
        requirement["human_decision"] = decision

        if decision in {"approved", "edited"}:
            final_text = candidate_by_id[selected_id]
            evaluation = _evaluate_candidate(final_text, srs_text)
            checks = requirement.setdefault("validation", {}).setdefault("checks", {})
            checks["quality"] = evaluation["quality_check"]
            checks["grounding"] = evaluation["grounding_check"]
            # Pair analysis is recomputed across the final selected text set
            # after all actions have been applied.
            checks["consistency"] = "skipped"
            # BDD-readiness is evaluated provisionally here; it is recomputed
            # in the final reconciliation pass once consistency is resolved.
            checks["bdd_readiness"] = "skipped"  # will be updated below
            if "fail" in checks.values():
                validation_status = "failed"
            elif any(checks.get(name) != "pass" for name in REQUIRED_READINESS_CHECKS):
                validation_status = "needs_review"
            else:
                validation_status = "passed"
            requirement["validation"]["status"] = validation_status
            requirement["defects"] = evaluation["quality_findings"]
            requirement["grounding"] = {
                "status": evaluation["grounding"]["status"],
                "evidence": evaluation["grounding"]["evidence"],
            }
        elif decision in {"pending", "rejected", "not_required"}:
            final_text = original_text

        requirement["final_text"] = final_text
        validation = requirement.get("validation", {})
        requirement["bdd_ready"] = can_mark_bdd_ready(
            validation.get("status", "needs_review"),
            validation.get("checks", {}),
            decision,
        )

        diagnostics.append({
            "requirement_id": requirement_id,
            "human_decision": decision,
            "selected_candidate_id": selected_id,
            "clarification_answers": answers,
            "candidates": candidate_diagnostics,
            "final_text_severity_priority": assess_defects(
                analyse_requirement(final_text)
            ),
            "readiness_blockers": [
                name for name in REQUIRED_READINESS_CHECKS
                if requirement["validation"].get("checks", {}).get(name) != "pass"
            ],
        })

    final_analysis = analyse_consistency([
        {
            "requirement_id": requirement["requirement_id"],
            "text": requirement.get("final_text", requirement.get("original_text")),
        }
        for requirement in output["requirements"]
    ])
    diagnostic_by_id = {item["requirement_id"]: item for item in diagnostics}
    final_peers = [{"requirement_id": r["requirement_id"], "text": r["final_text"]} for r in output["requirements"]]
    for requirement in output["requirements"]:
        requirement_id = str(requirement["requirement_id"])
        consistency = consistency_for_requirement(requirement_id, final_analysis)
        final_text = requirement.get("final_text", requirement.get("original_text"))
        final_findings = analyse_requirement(final_text)
        record = workflow_records.get(requirement_id) if workflow_records else None
        evaluation = _evaluate_candidate(final_text, srs_text, requirement["original_text"], record)
        final_grounding = evaluation["grounding"]
        resolution = clarification_resolution(record, requirement["original_text"], list(requirement.get("clarification_questions") or []))
        unresolved = resolution["unresolved_questions"]
        if record and record.get("clarification_requested"):
            unresolved = unresolved + ["Explicit clarification review is still requested."]
        baseline_tier = next(r["tier"] for r in baseline_requirements if r["requirement_id"] == requirement_id)
        escalation = bool(record.get("escalation_active") if record else baseline_tier == "TIER_3_ESCALATE")
        tier_options = (
            {"original_text": requirement["original_text"], "candidate_text": final_text,
             "human_reviewed": requirement["human_decision"] in ACCEPTED_DECISIONS and not unresolved and not escalation}
            if final_text != requirement["original_text"] else {}
        )
        tier = classify_tier(final_findings, final_grounding, consistency,
                             unresolved_clarification=bool(unresolved), **tier_options)
        requirement["tier"] = tier["tier"]
        requirement["consistency"] = {
            "status": consistency["status"],
            "related_requirement_ids": consistency["related_requirement_ids"],
            "conflicts": consistency["conflicts"],
        }
        validation = requirement.setdefault("validation", {})
        checks = validation.setdefault("checks", {})
        # Every final-text/decision transition replaces all dependent fields.
        requirement["defects"] = evaluation["quality_findings"]
        requirement["grounding"] = {"status": final_grounding["status"], "evidence": final_grounding["evidence"]}
        checks["quality"] = evaluation["quality_check"]
        checks["grounding"] = evaluation["grounding_check"]
        checks["consistency"] = consistency["check"]
        # Now that consistency is resolved, compute the definitive BDD-readiness
        # result using all four upstream check values and the current tier.
        bdd_result = bdd_check_from_validation(
            final_text,
            checks,
            tier=tier["tier"],
            clarification_questions=unresolved,
            consistency_result=consistency,
            escalation_active=escalation,
        )
        checks["bdd_readiness"] = bdd_result["check"]
        consistency_satisfied = (
            checks.get("consistency") == "pass"
            or (
                checks.get("consistency") == "skipped"
                and is_single_requirement_no_peers(consistency)
            )
        )
        if "fail" in checks.values():
            validation["status"] = "failed"
        elif (
            checks.get("quality") == "pass"
            and checks.get("grounding") == "pass"
            and checks.get("bdd_readiness") == "pass"
            and consistency_satisfied
        ):
            validation["status"] = "passed"
        else:
            validation["status"] = "needs_review"
        requirement["bdd_ready"] = can_mark_bdd_ready(
            validation["status"],
            checks,
            requirement.get("human_decision", "pending"),
            consistency_result=consistency,
        )
        if requirement_id in diagnostic_by_id:
            diagnostic = diagnostic_by_id[requirement_id]
            diagnostic["candidate_pre_action_assessments"] = copy.deepcopy(diagnostic["candidates"])
            # Current candidate diagnostics use the complete final peer set,
            # not stale pre-action peers from an earlier snapshot.
            for candidate in diagnostic["candidates"]:
                candidate_evaluation = _evaluate_candidate(candidate["text"], srs_text, requirement["original_text"], record)
                candidate_consistency = _consistency_with_candidate(requirement_id, candidate["text"], output["requirements"])
                candidate_tier = classify_tier(
                    candidate_evaluation["quality_findings"], candidate_evaluation["grounding"], candidate_consistency,
                    original_text=requirement["original_text"], candidate_text=candidate["text"],
                    human_reviewed=(requirement["human_decision"] in ACCEPTED_DECISIONS
                                    and candidate["candidate_id"] == requirement.get("selected_candidate_id")
                                    and not unresolved and not escalation),
                    unresolved_clarification=bool(unresolved),
                )
                candidate_validation = _candidate_validation(
                    candidate_evaluation, candidate_consistency, text=candidate["text"], tier=candidate_tier["tier"],
                    clarification_questions=unresolved + clarification_questions_for(candidate["text"]),
                    escalation_active=escalation,
                )
                candidate.update(**candidate_evaluation, consistency=candidate_consistency, tier=candidate_tier,
                                 validation=candidate_validation, bdd_readiness=candidate_validation["bdd_readiness"],
                                 validation_signature=validation_signature(candidate["text"], requirement, srs_text, final_peers, record),
                                 comparison_basis="current_final_peer_set")
            blockers = [
                name for name in ("quality", "grounding", "bdd_readiness")
                if checks.get(name) != "pass"
            ]
            if not consistency_satisfied:
                blockers.append("consistency")
            diagnostic_by_id[requirement_id]["readiness_blockers"] = blockers
            diagnostic_by_id[requirement_id]["consistency"] = consistency
            diagnostic_by_id[requirement_id]["tier"] = tier
            diagnostic_by_id[requirement_id]["clarification_resolution"] = resolution
            diagnostic_by_id[requirement_id]["grounding_categories"] = final_grounding
            diagnostic_by_id[requirement_id]["validation_signature"] = validation_signature(
                final_text, requirement, srs_text, final_peers, record,
            )
            diagnostic_by_id[requirement_id]["bdd_readiness"] = {
                "check": bdd_result["check"],
                "bdd_ready": requirement["bdd_ready"],
                "reasons": bdd_result["reasons"],
                "explanation": bdd_result["explanation"],
            }
    for diagnostic in diagnostics:
        diagnostic["consistency_analysis"] = final_analysis

    return output, diagnostics
