"""Versioned human pair-review records. Never consumed by readiness gates."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from c1_requirement_quality.consistency_analyser import analyse_consistency
from c1_requirement_quality.pair_applicability import _pair_id

POLICY_VERSION = "human-consistency-audit-v1"
DECISIONS = {"not_applicable", "consistent_within_scope", "conflict_confirmed", "unresolved"}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode("utf-8")).hexdigest()


def pair_views(artifact: dict[str, Any], manifest: dict[str, Any], state: dict[str, Any],
               history: list[dict[str, Any]], *, policy: str = POLICY_VERSION) -> list[dict[str, Any]]:
    """Derive validity without modifying historical events or deterministic results."""
    rows = {r["requirement_id"]: r for r in artifact["requirements"]}
    original = analyse_consistency([{"requirement_id": rid, "text": r["original_text"]} for rid, r in rows.items()])
    current = analyse_consistency([{"requirement_id": rid, "text": r["final_text"]} for rid, r in rows.items()])
    original_pairs = {_pair_id(p["requirement_ids"]): p for p in original["pairs"]}
    result = []
    for outcome in current["pairs"]:
        ids = sorted(outcome["requirement_ids"])
        pid = _pair_id(ids)
        inputs = {}
        evidence = {}
        for rid in ids:
            row = rows[rid]
            record = state["requirements"][rid]
            # Include all current question/answer state, conservatively including
            # invalid answers. Reopening or replacing an answer invalidates review.
            inputs[rid] = {"original_text_sha256": digest(row["original_text"]),
                "current_text_sha256": digest(row["final_text"]), "source": row["source"],
                "clarifications": {"questions": record["questions"], "answers": record["answers"]}}
            evidence[f"SRS:{rid}:original"] = {"kind": "original_source", "requirement_id": rid,
                "text": row["original_text"], "source": row["source"]}
            for question in record["questions"].values():
                if question["status"] not in {"ANSWERED", "CLOSED"}:
                    continue
                if question["status"] == "CLOSED" and question.get("closure_kind") != "ANSWERED":
                    continue
                for answer in record["answers"]:
                    if answer["answer_id"] == question["current_answer_id"]:
                        evidence[f"ANSWER:{rid}:{answer['answer_id']}"] = {
                            "kind": "human_clarification_not_original_source", "question": question, "answer": answer}
        binding_inputs = {"policy_version": policy, "source_identity": {
            k: manifest[k] for k in ("document_id", "sha256", "normalized_sha256")},
            "requirements": inputs, "evidence_sha256": digest(evidence)}
        binding = digest(binding_inputs)
        previous = [copy.deepcopy(e) for e in history if e["pair_id"] == pid]
        latest = previous[-1] if previous else None
        stale = latest is not None and (latest["binding"] != binding or bool(latest.get("invalidations")))
        result.append({"pair_id": pid, "requirement_ids": ids,
            "requirements": [copy.deepcopy(rows[rid]) for rid in ids],
            "original_deterministic": copy.deepcopy(original_pairs[pid]),
            "current_deterministic": copy.deepcopy(outcome), "binding": binding,
            "binding_inputs": binding_inputs, "evidence": evidence, "history": previous,
            "decision": latest["decision"] if latest and not stale else "unresolved",
            "invalidation": "Text, source, evidence, clarification or policy binding changed" if stale else None,
            "decision_effect": "none"})
    return result


def make_review(view: dict[str, Any], *, decision: str, evidence_refs: list[str],
                scope: str, conditions: str, rationale: str, reviewer: str,
                confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("Explicit human confirmation is required")
    if decision not in DECISIONS:
        raise ValueError("Unknown consistency review decision")
    for name, value in {"scope": scope, "conditions": conditions,
                        "rationale": rationale, "reviewer": reviewer}.items():
        if not isinstance(value, str) or not value.strip() or len(value) > 6000:
            raise ValueError(f"Nonempty {name} of at most 6000 characters is required")
    if (not isinstance(evidence_refs, list) or not evidence_refs
            or any(not isinstance(ref, str) or ref not in view["evidence"] for ref in evidence_refs)
            or len(set(evidence_refs)) != len(evidence_refs)):
        raise ValueError("Unique verified evidence references are required")
    if any(f"SRS:{rid}:original" not in evidence_refs for rid in view["requirement_ids"]):
        raise ValueError("Evidence for both requirements is required")
    if (decision in {"not_applicable", "consistent_within_scope"}
            and any(view[k]["classification"] == "conflict"
                    for k in ("original_deterministic", "current_deterministic"))):
        raise ValueError("A confirmed deterministic conflict cannot be dismissed")
    record = {"schema_version": 1, "policy_version": view["binding_inputs"]["policy_version"], "decision_effect": "none",
        "pair_id": view["pair_id"], "requirement_ids": view["requirement_ids"],
        "binding": view["binding"], "binding_inputs": view["binding_inputs"],
        "evidence_refs": evidence_refs, "evidence": {ref: view["evidence"][ref] for ref in evidence_refs},
        "original_deterministic": view["original_deterministic"],
        "current_deterministic": view["current_deterministic"],
        "scope": scope, "conditions": conditions, "rationale": rationale, "reviewer": reviewer,
        "decision": decision, "recorded_at": datetime.now(timezone.utc).isoformat(),
        "supersedes": view["history"][-1]["review_id"] if view["history"] else None,
        "prior_invalidation": view["invalidation"]}
    record["review_id"] = "REVIEW-" + digest(record)
    return copy.deepcopy(record)


def validate_record(record: dict[str, Any]) -> None:
    """Reject unsupported journal records before replaying their audit history."""
    payload = {k: v for k, v in record.items() if k != "review_id"}
    if (record.get("schema_version") != 1 or record.get("decision_effect") != "none"
            or record.get("review_id") != "REVIEW-" + digest(payload)
            or record.get("decision") not in DECISIONS
            or record.get("pair_id") != _pair_id(record["requirement_ids"])
            or record.get("binding") != digest(record["binding_inputs"])):
        raise ValueError("Invalid consistency review event")
    # Reuse creation validation; never interpret a recomputed checksum as authorship.
    reconstructed = make_review({"pair_id": record["pair_id"], "requirement_ids": record["requirement_ids"],
        "binding": record["binding"], "binding_inputs": record["binding_inputs"],
        "evidence": record["evidence"], "original_deterministic": record["original_deterministic"],
        "current_deterministic": record["current_deterministic"], "history": [], "invalidation": None},
        decision=record["decision"], evidence_refs=record["evidence_refs"], scope=record["scope"],
        conditions=record["conditions"], rationale=record["rationale"], reviewer=record["reviewer"], confirmed=True)
    if reconstructed["policy_version"] != record["policy_version"]:
        raise ValueError("Review policy and binding disagree")
