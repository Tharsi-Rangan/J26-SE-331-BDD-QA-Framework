"""Automated requirement rewrite candidate generation for Component 1.

Generates evidence-grounded candidate rewrites using a pluggable GeneratorBackend.
Validates each candidate using existing C1 quality, grounding, consistency,
and BDD-readiness checks.

Produces a candidate_suggestions.json sidecar without modifying the frozen
C1 contract or mutating input artifacts.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Protocol

from c1_requirement_quality.bdd_readiness import (
    evaluate_bdd_readiness,
    is_single_requirement_no_peers,
)
from c1_requirement_quality.consistency_analyser import (
    analyse_consistency,
    consistency_for_requirement,
)
from c1_requirement_quality.grounding_analyser import analyse_grounding
from c1_requirement_quality.quality_analyser import analyse_requirement
from c1_requirement_quality.refinement import (
    PLACEHOLDER_PATTERN,
    _candidate_validation,
    _consistency_with_candidate,
    _evaluate_candidate,
    can_mark_bdd_ready,
    clarification_questions_for,
    stable_candidate_id,
)
from c1_requirement_quality.severity_priority import assess_defects
from c1_requirement_quality.tier_classifier import (
    TIER_1,
    TIER_2,
    TIER_3,
    classify_tier,
)


def _get_tier_classification(tier_val: Any) -> str:
    if isinstance(tier_val, str):
        return tier_val
    if isinstance(tier_val, dict):
        return str(tier_val.get("tier", tier_val.get("classification", "")))
    return ""


class GeneratorBackend(Protocol):
    """Pluggable candidate generation strategy protocol."""

    def generate(
        self,
        requirement_text: str,
        defects: list[dict[str, Any]],
        evidence_chunks: list[dict[str, Any]],
        clarification_answers: list[dict[str, str]],
        *,
        max_candidates: int = 3,
    ) -> list[dict[str, Any]]:
        """Generate candidate rewrite proposals.

        Returns a list of dicts with keys:
          - "text": proposed candidate text (str)
          - "strategy": strategy name (str)
          - "source_evidence": evidence provenance dict (dict)
        """
        ...


class DeterministicSubstitutionBackend:
    """Rule-based baseline rewrite generator.

    Applies deterministic, evidence-grounded text transformations:
    1. modal_normalization: replaces weak modals (may, can, could, should) with shall.
    2. vague_qualifier_removal: substitutes vague terms with measurable values from SRS chunks.
    3. placeholder_substitution: resolves placeholders with user-confirmed clarification answers.
    """

    def __init__(self, *, structural_only_alternative: bool = False):
        self.structural_only_alternative = structural_only_alternative

    def generate(
        self,
        requirement_text: str,
        defects: list[dict[str, Any]],
        evidence_chunks: list[dict[str, Any]],
        clarification_answers: list[dict[str, str]],
        *,
        max_candidates: int = 3,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []

        if self.structural_only_alternative:
            normalized = re.sub(r"\s+", " ", requirement_text).strip()
            if normalized and not normalized.endswith((".", "!", "?")):
                candidates.append({"text": normalized + ".", "strategy": "terminal_punctuation",
                                   "source_evidence": {"kind": "srs_chunk", "text": requirement_text,
                                                       "source": "original_srs"}})

        # Strategy 1: Modal normalization
        modal_candidate = self._apply_modal_normalization(requirement_text, evidence_chunks)
        if modal_candidate and modal_candidate["text"] != requirement_text:
            candidates.append(modal_candidate)

        # Strategy 2: Vague qualifier substitution using SRS evidence
        vague_candidate = self._apply_vague_substitution(requirement_text, defects, evidence_chunks)
        if vague_candidate and vague_candidate["text"] != requirement_text:
            candidates.append(vague_candidate)

        # Strategy 3: Placeholder substitution using user-confirmed clarification answers
        placeholder_candidate = self._apply_placeholder_substitution(
            requirement_text, clarification_answers
        )
        if placeholder_candidate and placeholder_candidate["text"] != requirement_text:
            candidates.append(placeholder_candidate)

        # Deduplicate candidates by text preserving order
        unique_candidates: list[dict[str, Any]] = []
        seen_texts: set[str] = set()
        for cand in candidates:
            norm_text = re.sub(r"\s+", " ", cand["text"]).strip()
            if norm_text not in seen_texts and norm_text != re.sub(r"\s+", " ", requirement_text).strip():
                seen_texts.add(norm_text)
                unique_candidates.append(cand)

        return unique_candidates[:max_candidates]

    def _apply_modal_normalization(
        self,
        text: str,
        evidence_chunks: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        pattern = re.compile(r"\b(?:should|may|could|can|might)(\s+not)?\b", re.IGNORECASE)
        match = pattern.search(text)
        if not match:
            return None

        def repl(m: re.Match[str]) -> str:
            is_negated = bool(m.group(1))
            return "shall not" if is_negated else "shall"

        new_text = pattern.sub(repl, text, count=1)
        if new_text == text:
            return None

        chunk = evidence_chunks[0] if evidence_chunks else {}
        evidence = {
            "kind": "srs_chunk",
            "chunk_id": chunk.get("chunk_id", "SRS-MODAL-NORM"),
            "text": chunk.get("text", text),
            "source": chunk.get("source", "lexical"),
            "grounding_mode": "lexical",
        }
        return {
            "text": new_text,
            "strategy": "modal_normalization",
            "source_evidence": evidence,
        }

    def _apply_vague_substitution(
        self,
        text: str,
        defects: list[dict[str, Any]],
        evidence_chunks: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        vague_patterns = [
            (re.compile(r"\bquickly\b", re.IGNORECASE), "quickly"),
            (re.compile(r"\bpromptly\b", re.IGNORECASE), "promptly"),
            (re.compile(r"\befficiently\b", re.IGNORECASE), "efficiently"),
            (re.compile(r"\bwithin a reasonable time\b", re.IGNORECASE), "within a reasonable time"),
            (re.compile(r"\bas fast as possible\b", re.IGNORECASE), "as fast as possible"),
        ]

        found_vague = None
        for pattern, label in vague_patterns:
            if pattern.search(text):
                found_vague = (pattern, label)
                break

        if not found_vague:
            return None

        pattern, label = found_vague

        measurable_pattern = re.compile(
            r"\b(?:within\s+\d+\s+(?:seconds?|minutes?|hours?|days?|ms)|in\s+less\s+than\s+\d+\s+\w+)\b",
            re.IGNORECASE,
        )

        matching_chunk = None
        measurable_replacement = None
        for chunk in evidence_chunks:
            chunk_text = chunk.get("text", "")
            m = measurable_pattern.search(chunk_text)
            if m:
                matching_chunk = chunk
                measurable_replacement = m.group(0)
                break

        if not matching_chunk or not measurable_replacement:
            return None

        new_text = pattern.sub(measurable_replacement, text, count=1)
        if new_text == text:
            return None

        evidence = {
            "kind": "srs_chunk",
            "chunk_id": matching_chunk.get("chunk_id", "SRS-MEASURABLE"),
            "text": matching_chunk.get("text", measurable_replacement),
            "source": matching_chunk.get("source", "lexical"),
            "grounding_mode": matching_chunk.get("grounding_mode", "lexical"),
        }
        return {
            "text": new_text,
            "strategy": "vague_qualifier_removal",
            "source_evidence": evidence,
        }

    def _apply_placeholder_substitution(
        self,
        text: str,
        clarification_answers: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        open_questions = clarification_questions_for(text)
        if not open_questions or not clarification_answers:
            return None

        answers_by_q = {
            item.get("question"): item.get("answer")
            for item in clarification_answers
            if isinstance(item, dict)
        }

        new_text = text
        applied_evidence: list[dict[str, Any]] = []

        for match in PLACEHOLDER_PATTERN.finditer(text):
            marker = match.group(0)
            if marker.startswith("["):
                question = f"What value or rule should replace {marker}?"
            else:
                question = f"What information should replace {marker}?"

            answer = answers_by_q.get(question)
            if not answer or not str(answer).strip():
                return None
            if clarification_questions_for(str(answer)):
                return None

            new_text = new_text.replace(marker, str(answer), 1)
            applied_evidence.append({
                "kind": "clarification_answer",
                "question": question,
                "answer": str(answer),
                "source": "user_supplied",
            })

        if new_text == text or not applied_evidence:
            return None

        return {
            "text": new_text,
            "strategy": "placeholder_substitution",
            "source_evidence": applied_evidence[0] if len(applied_evidence) == 1 else {
                "kind": "clarification_answers",
                "items": applied_evidence,
                "source": "user_supplied",
            },
        }


def check_eligibility(
    requirement: dict[str, Any],
    clarification_answers: list[dict[str, str]],
) -> tuple[bool, str | None, list[str]]:
    """Determine whether a requirement is eligible for candidate rewrite generation."""
    original_text = requirement.get("original_text", "")
    tier_label = _get_tier_classification(requirement.get("tier"))
    consistency = requirement.get("consistency", {})

    open_questions = clarification_questions_for(original_text)

    # Rule 1: Tier 2 requirements with unresolved clarification questions are blocked
    if tier_label == TIER_2:
        if open_questions:
            answers_by_q = {
                item.get("question"): item.get("answer")
                for item in clarification_answers
                if isinstance(item, dict)
            }
            unanswered = []
            for q in open_questions:
                ans = answers_by_q.get(q)
                if not ans or not str(ans).strip() or bool(clarification_questions_for(str(ans))):
                    unanswered.append(q)
            if unanswered:
                return False, "tier2_open_questions", unanswered

    # Rule 2: Tier 3 requirements with confirmed consistency conflicts are blocked
    if tier_label == TIER_3 and consistency.get("status") == "conflict":
        return False, "tier3_conflict", []

    return True, None, open_questions


def _score_candidate(
    candidate: dict[str, Any],
    original_defects: list[dict[str, Any]],
    original_text: str,
    original_tier: str | None,
) -> tuple[float, dict[str, Any]]:
    """Compute ranking score and score breakdown for a viable candidate."""
    validation = candidate.get("validation", {})
    checks = validation.get("checks", {})
    cand_text = candidate.get("text", "")

    orig_types = {d.get("type") for d in original_defects if d.get("type")}
    cand_findings = candidate.get("quality_findings", [])
    cand_types = {f.get("type") for f in cand_findings if f.get("type")}
    eliminated_count = len(orig_types - cand_types)
    defects_eliminated_score = 3.0 * eliminated_count

    grounding_pass_score = 2.0 if checks.get("grounding") == "pass" else 0.0

    cand_consistency = candidate.get("consistency", {})
    consistency_pass_score = 2.0 if cand_consistency.get("status") == "consistent" or checks.get("consistency") == "skipped" else 0.0

    bdd_pass_score = 2.0 if checks.get("bdd_readiness") == "pass" else 0.0

    cand_tier = _get_tier_classification(candidate.get("tier"))
    orig_tier_str = _get_tier_classification(original_tier)
    tier_weights = {TIER_1: 3, TIER_2: 2, TIER_3: 1}
    orig_w = tier_weights.get(orig_tier_str, 1)
    cand_w = tier_weights.get(cand_tier, 1)
    tier_improvement_score = 1.0 if cand_w > orig_w else 0.0

    delta_len = max(0, len(cand_text) - len(original_text))
    length_penalty_score = -0.1 * math.floor(delta_len / 10)

    total_score = (
        defects_eliminated_score
        + grounding_pass_score
        + consistency_pass_score
        + bdd_pass_score
        + tier_improvement_score
        + length_penalty_score
    )

    breakdown = {
        "defects_eliminated": defects_eliminated_score,
        "grounding_pass": grounding_pass_score,
        "consistency_pass": consistency_pass_score,
        "bdd_readiness_pass": bdd_pass_score,
        "tier_improvement": tier_improvement_score,
        "length_penalty": round(length_penalty_score, 2),
        "downstream": None,
    }

    return round(total_score, 2), breakdown


def _rank_candidates(
    candidates: list[dict[str, Any]],
    original_defects: list[dict[str, Any]],
    original_text: str,
    original_tier: str | None,
) -> list[dict[str, Any]]:
    """Rank viable candidates deterministically with stable tie-breaking."""
    if not candidates:
        return []

    scored = []
    for cand in candidates:
        score, breakdown = _score_candidate(cand, original_defects, original_text, original_tier)
        cand_copy = dict(cand)
        cand_copy["score"] = score
        cand_copy["score_breakdown"] = breakdown
        scored.append(cand_copy)

    def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        score = item["score"]
        evidence_count = len(item.get("grounding", {}).get("evidence", []))
        length = len(item.get("text", ""))
        cand_id = item.get("candidate_id", "")
        return (-score, -evidence_count, length, cand_id)

    scored.sort(key=sort_key)

    ranked: list[dict[str, Any]] = []
    current_rank = 1
    for i, item in enumerate(scored):
        if i > 0 and item["score"] < scored[i - 1]["score"]:
            current_rank = i + 1
        item["rank"] = current_rank
        ranked.append(item)

    return ranked


def generate_candidate_suggestions(
    artifact: dict[str, Any],
    srs_text: str,
    *,
    clarification_answers: list[dict[str, Any]] | None = None,
    backend: GeneratorBackend | None = None,
    grounding_mode: str = "lexical",
    workflow_blocked_ids: set[str] | None = None,
    workflow_rejected_ids: set[str] | None = None,
    workflow_records: dict[str, Any] | None = None,
    consistency_context: dict[str, Any] | None = None,
    requirement_ids: list[str] | None = None,
    grounding_context=None,
    workflow_context=None,
) -> dict[str, Any]:
    """Generate requirement rewrite candidate suggestions into a sidecar artifact."""
    from c1_requirement_quality.source_integrity import resolve_workflow_policy
    rag, _, _, _ = resolve_workflow_policy(workflow_context or grounding_context, artifact=artifact, source_text=srs_text)
    if rag and grounding_context is None:
        raise ValueError("Authoritative RAG evidence context required; lexical fallback prohibited")
    if grounding_mode != "lexical" and not (grounding_mode == "rag" and grounding_context is not None):
        raise ValueError("Candidate validation supports only lexical grounding; RAG is available for run and advisory verification")
    if grounding_context is not None:
        grounding_context.check_parent(artifact)
    if backend is None:
        backend = DeterministicSubstitutionBackend()

    answers_input = clarification_answers or []
    all_requirements = artifact.get("requirements", [])
    selected = None
    if requirement_ids is not None:
        if (not isinstance(requirement_ids, list) or not requirement_ids
                or any(not isinstance(rid, str) for rid in requirement_ids)
                or len(set(requirement_ids)) != len(requirement_ids)
                or not set(requirement_ids) <= {r["requirement_id"] for r in all_requirements}):
            raise ValueError("Select unique requirement IDs from the active artifact")
        selected = set(requirement_ids)
        if any("requirement_id" not in item for item in answers_input):
            raise ValueError("Selected generation requires requirement-scoped clarification answers")
    run_id = artifact.get("run_id", "RUN-UNKNOWN")
    source_document = artifact.get("source_document", {})

    output_requirements: list[dict[str, Any]] = []

    total_candidates_count = 0
    ranked_candidates_total = 0
    diagnostic_suggestions_total = 0
    fabricated_candidates_count = 0
    srs_grounding_failure_count = 0
    human_clarification_count = 0

    eligible_count = 0
    blocked_count = 0

    for req in all_requirements:
        req_id = req.get("requirement_id", "")
        if selected is not None and req_id not in selected:
            continue
        orig_text = req.get("original_text", "")
        orig_defects = req.get("defects", [])
        orig_tier_label = _get_tier_classification(req.get("tier"))

        req_answers: list[dict[str, str]] = []
        for ans_item in answers_input:
            if isinstance(ans_item, dict):
                if "requirement_id" in ans_item:
                    if ans_item["requirement_id"] == req_id:
                        req_answers.extend(ans_item.get("clarification_answers", []))
                elif "question" in ans_item and "answer" in ans_item:
                    req_answers.append(ans_item)

        is_eligible, blocked_reason, open_questions = check_eligibility(req, req_answers)
        if req_id in (workflow_blocked_ids or set()):
            is_eligible, blocked_reason = False, "workflow_escalation"

        if not is_eligible:
            blocked_count += 1
            output_requirements.append({
                "requirement_id": req_id,
                "original_text": orig_text,
                "original_defects": orig_defects,
                "original_tier": orig_tier_label,
                "blocked": True,
                "blocked_reason": blocked_reason,
                "open_questions": open_questions,
                "ranked_candidates": [],
                "diagnostic_suggestions": [],
                "rejected_candidates": [],
                "zero_candidates_reason": f"Requirement generation blocked: {blocked_reason}",
            })
            continue

        eligible_count += 1

        evidence_chunks = req.get("grounding", {}).get("evidence", [])
        if not evidence_chunks:
            # Also search srs_text for matching lines/chunks to provide context
            evidence_chunks = [{
                "chunk_id": f"SRS-{req_id}",
                "text": orig_text,
                "source": "lexical",
                "grounding_mode": "lexical",
            }]
            for line in srs_text.splitlines():
                line_str = line.strip()
                if line_str and line_str != orig_text and any(w in line_str for w in orig_text.split()):
                    evidence_chunks.append({
                        "chunk_id": "SRS-CONTEXT",
                        "text": line_str,
                        "source": "lexical",
                        "grounding_mode": "lexical",
                    })

        if selected is not None:
            # Broad evidence chunks may include other requirements. Transmit only
            # this selected source statement; peer checks still use the full local set.
            evidence_chunks = ([{"chunk_id": f"SRS-{req_id}", "text": orig_text,
                                 "source": "lexical", "grounding_mode": "lexical"}]
                               if orig_text in srs_text else [])
        proposals = backend.generate(
            orig_text,
            orig_defects,
            evidence_chunks,
            req_answers,
            max_candidates=3,
        )

        viable_candidates: list[dict[str, Any]] = []
        diagnostic_suggestions: list[dict[str, Any]] = []
        rejected_candidates: list[dict[str, Any]] = []

        orig_norm = re.sub(r"\s+", " ", orig_text).strip()
        orig_defect_types = {d.get("type") for d in orig_defects if d.get("type")}

        for prop in proposals:
            total_candidates_count += 1
            cand_text = prop.get("text", "")
            cand_norm = re.sub(r"\s+", " ", cand_text).strip()
            source_ev = prop.get("source_evidence", {})
            is_human_clarified = source_ev.get("source") == "user_supplied" or source_ev.get("kind") in {
                "clarification_answer",
                "clarification_answers",
            }

            if is_human_clarified:
                human_clarification_count += 1
                is_fabricated = False
            else:
                is_fabricated = False

            if cand_norm == orig_norm:
                rejected_candidates.append({
                    "text": cand_text,
                    "rejected_reason": "no_change",
                    "source_evidence": source_ev,
                })
                continue

            cand_id = stable_candidate_id(req_id, cand_text)
            if cand_id in (workflow_rejected_ids or set()):
                rejected_candidates.append({"candidate_id": cand_id, "text": cand_text,
                                            "rejected_reason": "persisted_human_rejection",
                                            "source_evidence": source_ev})
                continue

            # 1. Quality & Grounding Evaluation
            from c1_requirement_quality.validation_lifecycle import generation_record, clarification_resolution
            record = workflow_records.get(req_id) if workflow_records else generation_record(
                req_id, orig_text, req.get("clarification_questions", []), req_answers,
            )
            evaluation = _evaluate_candidate(cand_text, srs_text, orig_text, record,
                source_format="docx" if source_document.get("name", "").lower().endswith(".docx") else None,
                grounding_context=grounding_context, requirement_id=req_id, require_rag=rag or grounding_mode == "rag",
                workflow_context=workflow_context)
            cand_findings = evaluation.get("quality_findings", [])
            cand_defect_types = {f.get("type") for f in cand_findings if f.get("type")}

            new_types = cand_defect_types - orig_defect_types
            if new_types:
                rejected_candidates.append({
                    "candidate_id": cand_id,
                    "text": cand_text,
                    "rejected_reason": "quality_regression",
                    "new_defects": list(new_types),
                    "source_evidence": source_ev,
                })
                continue

            grounding_check = evaluation.get("grounding_check")
            if evaluation["grounding"].get("original_srs_status") != "supported":
                srs_grounding_failure_count += 1

            if grounding_check != "pass" or not evaluation["candidate_eligible"]:
                rejected_candidates.append({
                    "candidate_id": cand_id,
                    "text": cand_text,
                    "rejected_reason": "rag_or_meaning_ineligible" if grounding_context is not None else "unsupported_facts",
                    "evaluation": evaluation,
                    "source_evidence": source_ev,
                })
                continue

            # 2. Consistency Analysis against peer requirements
            consistency_res = _consistency_with_candidate(req_id, cand_text, all_requirements, workflow_records, consistency_context)
            consistency_status = consistency_res.get("status")

            # Hard Veto: Confirmed conflict
            if consistency_status == "conflict":
                rejected_candidates.append({
                    "candidate_id": cand_id,
                    "text": cand_text,
                    "rejected_reason": "consistency_conflict",
                    "conflicts": consistency_res.get("conflicts", []),
                    "source_evidence": source_ev,
                })
                continue

            # 3. Classify tier for candidate
            cand_tier = classify_tier(cand_findings, evaluation.get("grounding", {}), consistency_res,
                                     original_text=orig_text, candidate_text=cand_text)

            # 4. Candidate Validation & BDD-readiness gate
            val_result = _candidate_validation(
                evaluation,
                consistency_res,
                text=cand_text,
                tier=cand_tier["tier"],
                clarification_questions=clarification_resolution(record, orig_text, [])["unresolved_questions"],
            )

            candidate_payload = {
                "candidate_id": cand_id,
                "text": cand_text,
                "strategy": prop.get("strategy"),
                "source_evidence": source_ev,
                "is_human_clarified": is_human_clarified,
                "is_fabricated": is_fabricated,
                "quality_findings": cand_findings,
                "grounding": evaluation.get("grounding", {}),
                "consistency": consistency_res,
                "tier": cand_tier,
                "validation": val_result,
            }

            # 5. Handling of potential_conflict:
            # An actual peer potential conflict exists when there are peer requirements and a pair is potential_conflict.
            # Single-requirement artifacts have no peers (is_single_requirement_no_peers is True).
            is_single_req = is_single_requirement_no_peers(consistency_res)
            has_peer_potential_conflict = (
                not is_single_req
                and (
                    any(p.get("classification") == "potential_conflict" for p in consistency_res.get("pairs", []))
                    or (consistency_status == "potential_conflict" and bool(consistency_res.get("pairs")))
                )
            )

            if has_peer_potential_conflict:
                diagnostic_suggestions_total += 1
                candidate_payload["diagnostic_reason"] = "potential_conflict"
                diagnostic_suggestions.append(candidate_payload)
                continue

            viable_candidates.append(candidate_payload)

        # Rank viable candidates
        ranked = _rank_candidates(viable_candidates, orig_defects, orig_text, orig_tier_label)
        ranked_candidates_total += len(ranked)

        zero_reason = None
        if not ranked and not diagnostic_suggestions:
            if not proposals:
                zero_reason = "No candidate rewrite strategies produced alternatives for this requirement"
            else:
                zero_reason = "All generated candidate rewrites were excluded by quality, grounding, or consistency validation"

        output_requirements.append({
            "requirement_id": req_id,
            "original_text": orig_text,
            "original_defects": orig_defects,
            "original_tier": orig_tier_label,
            "blocked": False,
            "blocked_reason": None,
            "ranked_candidates": ranked,
            "diagnostic_suggestions": diagnostic_suggestions,
            "rejected_candidates": rejected_candidates,
            "zero_candidates_reason": zero_reason,
        })

    fabrication_rate = (
        round(fabricated_candidates_count / total_candidates_count, 4)
        if total_candidates_count > 0
        else 0.0
    )
    srs_grounding_failure_rate = (
        round(srs_grounding_failure_count / total_candidates_count, 4)
        if total_candidates_count > 0
        else 0.0
    )
    human_clarification_rate = (
        round(human_clarification_count / total_candidates_count, 4)
        if total_candidates_count > 0
        else 0.0
    )

    sidecar = {
        "contract": "c1.candidate-suggestions",
        "schema_version": "1.0.0",
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_document": source_document,
        "generator": {
            "backend": backend.__class__.__name__,
            "baseline_type": ("API LLM proposal generator"
                              if getattr(backend, "generation_kind", None) == "api_llm"
                              else "rule-based baseline generator"),
            "grounding_mode_requested": grounding_mode,
            "grounding_mode_used": "rag" if grounding_context is not None else "lexical",
            "grounding_mode_errors": [],
        },
        "metrics": {
            "total_requirements": len(all_requirements),
            "eligible_requirements": eligible_count,
            "blocked_requirements": blocked_count,
            "total_candidates_generated": total_candidates_count,
            "ranked_candidates_count": ranked_candidates_total,
            "diagnostic_suggestions_count": diagnostic_suggestions_total,
            "fabrication_rate": fabrication_rate,
            "srs_grounding_failure_rate": srs_grounding_failure_rate,
            "human_clarification_rate": human_clarification_rate,
        },
        "requirements": output_requirements,
    }

    return sidecar


def generate_candidates_run(
    input_path: Path,
    srs_path: Path,
    out_path: Path,
    *,
    clarification_answers_path: Path | None = None,
    grounding_mode: str = "lexical",
    backend: GeneratorBackend | None = None,
    requirement_ids: list[str] | None = None,
) -> None:
    """CLI handler for c1 generate-candidates subcommand."""
    if grounding_mode != "lexical":
        raise ValueError("Candidate validation supports only lexical grounding; RAG is available for run and advisory verification")
    if out_path.exists():
        raise FileExistsError(f"Candidate output already exists: {out_path}")
    for path, label in ((input_path, "validated requirements"), (srs_path, "SRS")):
        if not path.is_file():
            raise FileNotFoundError(f"{label} file not found: {path}")

    raw_input_bytes = input_path.read_bytes()
    artifact = json.loads(raw_input_bytes.decode("utf-8-sig"))

    from c1_requirement_quality.contract import validate_contract_artifact as _validate_contract_artifact

    _validate_contract_artifact(artifact)

    from c1_requirement_quality.source_integrity import verify_source, VerifiedWorkflowContext

    srs_text, _source_manifest = verify_source(input_path, srs_path)
    from c1_requirement_quality.source_integrity import require_refinement_grounding
    require_refinement_grounding(_source_manifest)
    from c1_requirement_quality.workflow_persistence import load_state, current_answer_actions
    from c1_requirement_quality.effective_consistency import context_from_state
    workflow_state, _ = load_state(input_path, srs_path)

    clarification_answers: list[dict[str, Any]] = []
    if clarification_answers_path is None:
        clarification_answers = current_answer_actions(workflow_state)
    if clarification_answers_path:
        if not clarification_answers_path.is_file():
            raise FileNotFoundError(f"clarification answers file not found: {clarification_answers_path}")
        raw_answers = json.loads(clarification_answers_path.read_text(encoding="utf-8-sig"))
        if isinstance(raw_answers, dict) and "requirements" in raw_answers:
            clarification_answers = raw_answers["requirements"]
        elif isinstance(raw_answers, dict) and "actions" in raw_answers:
            clarification_answers = raw_answers["actions"]
        elif isinstance(raw_answers, list):
            clarification_answers = raw_answers
        elif isinstance(raw_answers, dict):
            clarification_answers = [raw_answers]

    sidecar = generate_candidate_suggestions(
        artifact,
        srs_text,
        clarification_answers=clarification_answers,
        grounding_mode=grounding_mode,
        backend=backend,
        requirement_ids=requirement_ids,
        workflow_blocked_ids={rid for rid, record in workflow_state["requirements"].items() if record["escalation_active"]},
        workflow_rejected_ids={cid for record in workflow_state["requirements"].values()
                               for cid, candidate in record["candidates"].items() if candidate["status"] == "REJECTED"},
        workflow_records=workflow_state["requirements"] if clarification_answers_path is None else None,
        consistency_context=context_from_state(workflow_state) if clarification_answers_path is None else None,
        workflow_context=VerifiedWorkflowContext(input_path, srs_path),
    )

    import hashlib
    sidecar["input_sha256"] = hashlib.sha256(raw_input_bytes).hexdigest()
    sidecar["source_sha256"] = _source_manifest["sha256"]
    sidecar["workflow_sha256"] = _source_manifest.get("workflow_sha256")

    after_bytes = input_path.read_bytes()
    if after_bytes != raw_input_bytes:
        raise RuntimeError("Input validated_requirements.json was mutated during candidate generation!")

    if out_path.exists():
        raise FileExistsError(f"Candidate output already exists: {out_path}")
    # Reverify before publishing, and retain failed temporary output for inspection.
    verify_source(input_path, srs_path)
    load_state(input_path, srs_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    import os
    descriptor, name = tempfile.mkstemp(prefix=".c1-candidates-pending-", dir=out_path.parent)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(sidecar, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    # Hard-link publication is exclusive even if another writer races us.
    os.link(name, out_path)
    Path(name).unlink()  # only this invocation's successfully published hard link
    print(f"[c1] wrote candidate suggestions to {out_path}")
