"""Approved human-review aggregation; raw deterministic results remain intact."""
from __future__ import annotations

import copy
from typing import Any

from c1_requirement_quality.consistency_analyser import analyse_consistency, consistency_for_requirement
from c1_requirement_quality.consistency_review import pair_views, make_review, digest

POLICY = "human-consistency-gates-v2"
NOTICE = "reviewed coverage complete — no applicable interactions established"


def context_from_state(state: dict[str, Any]) -> dict[str, Any]:
    history = [copy.deepcopy(e["payload"]) for e in state.get("events", [])
               if e["kind"] == "consistency_review_adopted"]
    invalid = {e["payload"]["review_id"] for e in state.get("events", [])
               if e["kind"] == "consistency_review_invalidated"}
    for record in history:
        if record["review_id"] in invalid:
            record["invalidations"] = ["Invalidated in verified workflow history"]
    return {"source_identity": state["source_identity"], "history": history}


def views(rows, records, context):
    from c1_requirement_quality.validation_lifecycle import clarification_resolution
    result = pair_views({"requirements": rows}, context["source_identity"],
                        {"requirements": records}, context["history"], policy=POLICY)
    allowed = set()
    for row in rows:
        rid = row["requirement_id"]
        for entry in clarification_resolution(records[rid], row["original_text"], [])["active_answers"]:
            allowed.add(f"ANSWER:{rid}:{entry['answer']['answer_id']}")
    for pair in result:
        pair["evidence"] = {ref: evidence for ref, evidence in pair["evidence"].items()
                            if not ref.startswith("ANSWER:") or ref in allowed}
    return result


def create_review(view, request):
    """Require fresh, explicit coverage confirmation; v1 records never qualify."""
    allowed = {"decision", "evidence_refs", "scope", "conditions", "rationale", "reviewer", "confirmed", "coverage"}
    if set(request) != allowed or request["coverage"] not in {"complete", "partial"} or request["confirmed"] is not True:
        raise ValueError("Review requires explicit confirmation and complete/partial coverage")
    value = make_review(view, **{k: v for k, v in request.items() if k != "coverage"})
    value.update(schema_version=2, policy_version=POLICY, coverage=request["coverage"],
                 explicitly_confirmed=True, decision_effect="adopted_workflow_only")
    value.pop("review_id")
    value["review_id"] = "REVIEW-" + digest(value)
    return value


def validate_adopted(record):
    payload = {k: v for k, v in record.items() if k != "review_id"}
    if (record.get("schema_version") != 2 or record.get("policy_version") != POLICY
            or record.get("decision_effect") != "adopted_workflow_only"
            or record.get("explicitly_confirmed") is not True
            or record.get("coverage") not in {"complete", "partial"}
            or record.get("binding_inputs", {}).get("policy_version") != POLICY
            or record.get("review_id") != "REVIEW-" + digest(payload)
            or record.get("binding") != digest(record["binding_inputs"])):
        raise ValueError("Invalid adopted consistency review")
    # Reuse evidence, rationale and deterministic-conflict validation.
    make_review({"pair_id": record["pair_id"], "requirement_ids": record["requirement_ids"],
        "binding": record["binding"], "binding_inputs": record["binding_inputs"],
        "evidence": record["evidence"], "original_deterministic": record["original_deterministic"],
        "current_deterministic": record["current_deterministic"], "history": [], "invalidation": None},
        **{k: record[k] for k in ("decision", "evidence_refs", "scope", "conditions", "rationale", "reviewer")}, confirmed=True)


def assess_all(rows, records=None, context=None):
    """One operation-local analysis, rebuilt for every text/review snapshot."""
    analysis = analyse_consistency([{"requirement_id": r["requirement_id"], "text": r["final_text"]} for r in rows])
    review_views = views(rows, records, context) if context and records and context.get("history") else []
    return {r["requirement_id"]: assess(r["requirement_id"], rows, records, context,
                                      _analysis=analysis, _views=review_views) for r in rows}


def assess(rid, rows, records=None, context=None, *, _analysis=None, _views=None):
    analysis = _analysis if _analysis is not None else analyse_consistency(
        [{"requirement_id": r["requirement_id"], "text": r["final_text"]} for r in rows])
    result = consistency_for_requirement(rid, analysis)
    if (not context or not records or not context.get("history")
            or not any(rid in h["requirement_ids"] for h in context["history"])):
        return result
    pair_results = []
    review_views = _views if _views is not None else views(rows, records, context)
    for view in review_views:
        if rid not in view["requirement_ids"]:
            continue
        latest = view["history"][-1] if view["history"] else None
        # Human conflict is sticky even when stale or superseded. Resolution is
        # a separate future adjudication operation, never an applicability click.
        open_conflict = any(h["decision"] == "conflict_confirmed" for h in view["history"])
        if view["current_deterministic"]["classification"] == "conflict" or open_conflict:
            resolution = "conflict"
        elif (latest and not view["invalidation"] and latest.get("coverage") == "complete"
              and latest.get("policy_version") == POLICY
              and latest.get("schema_version") == 2 and latest.get("explicitly_confirmed") is True
              and latest.get("decision_effect") == "adopted_workflow_only"
              and latest["decision"] in {"not_applicable", "consistent_within_scope"}):
            resolution = latest["decision"]
        elif view["current_deterministic"]["classification"] == "consistent":
            resolution = "deterministic_consistent"
        else:
            resolution = "unresolved"
        pair_results.append({"pair_id": view["pair_id"], "requirement_ids": view["requirement_ids"],
            "resolution": resolution, "review_id": latest["review_id"] if latest else None,
            "stale": bool(view["invalidation"])})
    conflicts = [p for p in pair_results if p["resolution"] == "conflict"]
    unresolved = [p for p in pair_results if p["resolution"] == "unresolved"]
    complete = bool(pair_results) and not conflicts and not unresolved
    all_na = complete and all(p["resolution"] == "not_applicable" for p in pair_results)
    result.update(status="conflict" if conflicts else "consistent" if complete else "potential_conflict",
        check="fail" if conflicts else "pass" if complete else "skipped",
        effective_review={"policy_version": POLICY, "coverage_complete": complete,
            "unresolved_count": len(unresolved), "conflict_count": len(conflicts),
            "all_not_applicable": all_na, "explanation": NOTICE if all_na else
                "Comparison obligations resolved under reviewed policy" if complete else "Comparison obligations remain blocking",
            "pairs": pair_results})
    if conflicts:
        result["conflicts"] = [{"with_requirement_id": next(i for i in p["requirement_ids"] if i != rid),
            "explanation": "Confirmed deterministic or open human-reviewed conflict requires explicit resolution."} for p in conflicts]
    result["review_basis"] = digest({"policy": POLICY, "pairs": pair_results,
        "bindings": [v["binding"] for v in review_views if rid in v["requirement_ids"]]})
    return result
