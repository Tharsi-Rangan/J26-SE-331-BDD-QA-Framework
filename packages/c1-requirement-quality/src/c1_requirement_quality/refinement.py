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

from c1_requirement_quality.grounding_analyser import analyse_grounding
from c1_requirement_quality.consistency_analyser import analyse_consistency, consistency_for_requirement
from c1_requirement_quality.quality_analyser import analyse_requirement
from c1_requirement_quality.severity_priority import assess_defects
from c1_requirement_quality.tier_classifier import classify_tier

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
) -> bool:
    """Apply the frozen readiness guard without supplying missing policy checks."""
    return (
        validation_status == "passed"
        and human_decision in ACCEPTED_DECISIONS
        and all(checks.get(name) == "pass" for name in REQUIRED_READINESS_CHECKS)
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


def _evaluate_candidate(text: str, srs_text: str) -> dict[str, Any]:
    findings = analyse_requirement(text)
    grounding = analyse_grounding(text, srs_text)
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
    evaluation: Mapping[str, Any], consistency: Mapping[str, Any]
) -> dict[str, Any]:
    """Record independent candidate checks without inventing a BDD rule."""
    checks = {
        "quality": str(evaluation["quality_check"]),
        "grounding": str(evaluation["grounding_check"]),
        "consistency": str(consistency["check"]),
        "bdd_readiness": "skipped",
    }
    status = "failed" if "fail" in checks.values() else "needs_review"
    ready = can_mark_bdd_ready(status, checks, "pending")
    return {
        "status": status,
        "checks": checks,
        "bdd_readiness": {
            "check": checks["bdd_readiness"],
            "bdd_ready": ready,
            "explanation": (
                "No approved C1 BDD-readiness criteria are defined; the check is skipped. "
                "Candidate evaluation does not imply human approval."
            ),
        },
    }


def process_refinement_actions(
    validated_requirements: dict[str, Any],
    actions: dict[str, Any],
    srs_text: str,
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
            evaluation = _evaluate_candidate(candidate["text"], srs_text)
            candidate_consistency = _consistency_with_candidate(
                requirement_id, candidate["text"], baseline_requirements
            )
            candidate_validation = _candidate_validation(evaluation, candidate_consistency)
            candidate_diagnostics.append({
                "candidate_id": candidate["candidate_id"],
                "text": candidate["text"],
                **evaluation,
                "consistency": candidate_consistency,
                "validation": candidate_validation,
                "bdd_readiness": candidate_validation["bdd_readiness"],
                "tier": classify_tier(
                    evaluation["quality_findings"],
                    evaluation["grounding"],
                    candidate_consistency,
                    original_text=original_text,
                    candidate_text=candidate["text"],
                ),
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
            checks["bdd_readiness"] = "skipped"
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
    for requirement in output["requirements"]:
        requirement_id = str(requirement["requirement_id"])
        consistency = consistency_for_requirement(requirement_id, final_analysis)
        final_text = requirement.get("final_text", requirement.get("original_text"))
        final_findings = analyse_requirement(final_text)
        final_grounding = analyse_grounding(final_text, srs_text)
        tier_options = (
            {"original_text": requirement["original_text"], "candidate_text": final_text}
            if final_text != requirement["original_text"] else {}
        )
        tier = classify_tier(final_findings, final_grounding, consistency, **tier_options)
        requirement["tier"] = tier["tier"]
        requirement["consistency"] = {
            "status": consistency["status"],
            "related_requirement_ids": consistency["related_requirement_ids"],
            "conflicts": consistency["conflicts"],
        }
        validation = requirement.setdefault("validation", {})
        checks = validation.setdefault("checks", {})
        checks["consistency"] = consistency["check"]
        if "fail" in checks.values():
            validation["status"] = "failed"
        elif all(checks.get(name) == "pass" for name in REQUIRED_READINESS_CHECKS):
            validation["status"] = "passed"
        else:
            validation["status"] = "needs_review"
        requirement["bdd_ready"] = can_mark_bdd_ready(
            validation["status"], checks, requirement.get("human_decision", "pending")
        )
        if requirement_id in diagnostic_by_id:
            diagnostic_by_id[requirement_id]["consistency"] = consistency
            diagnostic_by_id[requirement_id]["tier"] = tier
            diagnostic_by_id[requirement_id]["bdd_readiness"] = {
                "check": checks.get("bdd_readiness", "skipped"),
                "bdd_ready": requirement["bdd_ready"],
                "explanation": (
                    "No approved C1 BDD-readiness criteria are defined; the check remains skipped."
                    if checks.get("bdd_readiness") != "pass"
                    else "All required validation checks and the human-decision gate passed."
                ),
            }
    for diagnostic in diagnostics:
        diagnostic["consistency_analysis"] = final_analysis

    return output, diagnostics
