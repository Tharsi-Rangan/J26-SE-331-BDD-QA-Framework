"""Current-text validation with explicit, separately attributed clarification facts."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from c1_requirement_quality.grounding_analyser import analyse_grounding
from c1_requirement_quality.quality_analyser import analyse_requirement
from c1_requirement_quality.consistency_analyser import analyse_consistency, consistency_for_requirement
from c1_requirement_quality.tier_classifier import classify_tier

POLICY_VERSION = "c1-validation-1b3-v1"
PLACEHOLDER = re.compile(r"\[[^\]]+\]|\bTBD\b|\bTBC\b", re.I)
DURATION_ANSWER = re.compile(r"(?:(?:within|at least|at most|less than|no more than|up to)\s+)?\d+(?:\.\d+)?\s*(?:ms|milliseconds?|seconds?|minutes?|hours?|days?)\.?", re.I)


def original_assessments(artifact: dict[str, Any], source_text: str | None = None) -> dict[str, Any]:
    originals = [{"requirement_id": r["requirement_id"], "text": r["original_text"]} for r in artifact["requirements"]]
    analysis = analyse_consistency(originals) if source_text is not None else None
    result = {}
    for row in artifact["requirements"]:
        baseline = {k: copy.deepcopy(row.get(k)) for k in ("original_text", "defects", "tier", "grounding", "consistency", "validation")}
        baseline["basis"] = "original_snapshot_observation"
        if row["final_text"] != row["original_text"] and source_text is not None:
            findings = analyse_requirement(row["original_text"])
            grounding = analyse_grounding(row["original_text"], source_text)
            consistency = consistency_for_requirement(row["requirement_id"], analysis)
            baseline.update(defects=findings, grounding=grounding, consistency=consistency,
                            tier=classify_tier(findings, grounding, consistency)["tier"],
                            validation=None, basis="recomputed_original_baseline_not_historical_observation")
        result[row["requirement_id"]] = baseline
    return result


def normal(text: str) -> str:
    return " ".join(text.split())


def whole_obligation_question(text: str) -> bool:
    return bool(re.search(r"\b(?:what|which|how)\b.*\b(?:requirement|rewrite|statement|rule|obligation|behaviou?r)\b", text, re.I))


def valid_answer(question: dict[str, Any], answer: dict[str, Any], original: str) -> bool:
    value = answer.get("answer")
    if (not isinstance(value, str) or not value.strip() or PLACEHOLDER.search(value)
            or value.lower().strip(" .") in {"unknown", "unspecified", "n/a", "not sure", "irrelevant", "deferred", "waived"}):
        return False
    if answer.get("question_id") != question["question_id"] or answer.get("requirement_id") != question["requirement_id"]:
        return False
    prompt = question["text"].lower()
    generated = any(normal(question["text"]) == (
        f"What value or rule should replace {m.group(0)}?" if m.group(0).startswith("[") else f"What information should replace {m.group(0)}?"
    ) for m in PLACEHOLDER.finditer(original))
    whole_rule_prompt = not generated and whole_obligation_question(prompt)
    if prompt.startswith("who ") and (not re.search(r"[A-Za-z]", value) or re.search(r"\b(shall|must)\b", value, re.I)):
        return False
    if whole_rule_prompt and "replaces_span" not in answer and not re.search(r"\b(shall|must)\b", value, re.I):
        return False
    if re.search(r"\b(timeout|duration|latency|time)\b", prompt) and not prompt.startswith("who ") and not whole_rule_prompt:
        if not DURATION_ANSWER.fullmatch(value.strip()): return False
    if generated and re.search(r"\[(?:actor|role|user|entity)\]", prompt):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]*", value) or re.search(r"\b(shall|must|if|when)\b", value, re.I): return False
    if "replaces_span" in answer and (not answer["replaces_span"] or original.count(answer["replaces_span"]) != 1):
        return False
    return True


def clarification_resolution(record: dict[str, Any] | None, original: str,
                             fallback_questions: list[str]) -> dict[str, Any]:
    if record is None:
        return {"unresolved_questions": fallback_questions, "assessments": [], "active_answers": []}
    answers = {a["answer_id"]: a for a in record["answers"]}
    active = []; unresolved = []; assessments = []
    for question in record["questions"].values():
        status = question["status"]
        answer = answers.get(question["current_answer_id"])
        active_status = status == "ANSWERED" or status == "CLOSED" and question.get("closure_kind") == "ANSWERED"
        resolved = bool(active_status and answer and valid_answer(question, answer, original))
        if resolved:
            active.append({"question": copy.deepcopy(question), "answer": copy.deepcopy(answer)})
        else:
            unresolved.append(question["text"])
        assessments.append({"question_id": question["question_id"], "status": status,
                            "closure_kind": question.get("closure_kind"), "resolved": resolved,
                            "reason": "active_valid_answer" if resolved else "open_reopened_deferred_waived_or_invalid_answer"})
    return {"unresolved_questions": unresolved, "assessments": assessments, "active_answers": active}


def grounded_current(text: str, srs_text: str, original: str | None = None,
                     record: dict[str, Any] | None = None) -> dict[str, Any]:
    source = analyse_grounding(text, srs_text)
    result = copy.deepcopy(source)
    result.update(srs_evidence=copy.deepcopy(source["evidence"]), human_clarification_evidence=[],
                  original_srs_status=source["status"])
    if source["status"] == "supported" or original is None or record is None or source.get("conflicts"):
        return result
    resolution = clarification_resolution(record, original, [])
    active = resolution["active_answers"]
    scaffold = original
    used = []
    for item in active:
        q = item["question"]; answer = item["answer"]
        span = answer.get("replaces_span")
        if span is None:
            for marker in PLACEHOLDER.finditer(original):
                token = marker.group(0)
                expected = f"What value or rule should replace {token}?" if token.startswith("[") else f"What information should replace {token}?"
                if normal(q["text"]) == expected:
                    span = token
                    break
        if span is not None and span in scaffold:
            scaffold = scaffold.replace(span, answer["answer"])
            used.append(item)
    original_support = analyse_grounding(original, srs_text)
    method = None
    if (used and normal(scaffold) == normal(text) and not PLACEHOLDER.search(scaffold)
            and original_support["status"] == "supported"):
        method = "exact_srs_scaffold_replacement"
        result["srs_evidence"] = copy.deepcopy(original_support["evidence"])
    else:
        # A full human statement supports exactly that statement, not related
        # snippets or a different actor/number/condition/obligation.
        used = [item for item in active
                if normal(item["answer"]["answer"]) == normal(text)
                and whole_obligation_question(item["question"]["text"])
                and re.search(r"\b(shall|must)\b", text, re.I)]
        if used: method = "explicit_whole_human_obligation"
    if method is None: return result
    human = []
    for item in used:
        answer = item["answer"]
        human.append({"kind": "human_clarification", "answer_id": answer["answer_id"],
                      "question_id": answer["question_id"], "requirement_id": answer["requirement_id"],
                      "text": answer["answer"], "event_id": answer["event_id"],
                      "snapshot_id": answer["snapshot_id"], "actor_id": answer["actor_id"],
                      "provenance": copy.deepcopy(answer["provenance"]), "method": method})
    result.update(status="supported", unsupported_claims=[], human_clarification_evidence=human,
                  support_method=method)
    result["evidence"] = result["srs_evidence"] + [
        {"chunk_id": "HUMAN-" + item["answer_id"], "text": item["text"],
         "section": "Explicit human clarification (not original SRS)"} for item in human
    ]
    return result


def generation_record(rid: str, original: str, questions: list[str], supplied: list[dict[str, Any]]) -> dict[str, Any]:
    """Ephemeral explicit generation inputs; never claim persisted human events."""
    record = {"questions": {}, "answers": []}
    prompts = list(questions)
    for marker in PLACEHOLDER.finditer(original):
        token = marker.group(0)
        prompts.append(f"What value or rule should replace {token}?" if token.startswith("[") else f"What information should replace {token}?")
    for prompt in dict.fromkeys(prompts):
        qid = "QUESTION-" + hashlib.sha256(f"{rid}\0{normal(prompt)}".encode("utf-8")).hexdigest()
        record["questions"][qid] = {"question_id": qid, "requirement_id": rid, "text": prompt,
                                     "status": "OPEN", "current_answer_id": None}
        matching = [a for a in supplied if normal(a.get("question", "")) == normal(prompt)]
        if matching and len({a.get("answer") for a in matching}) == 1:
            raw = matching[-1]; aid = "GENERATION-ONLY-" + hashlib.sha256(f"{qid}\0{raw['answer']}".encode("utf-8")).hexdigest()
            answer = {"answer_id": aid, "question_id": qid, "requirement_id": rid, "answer": raw["answer"],
                      "actor_id": raw.get("actor_id", "unknown"), "event_id": "unpersisted_generation_input",
                      "snapshot_id": "unpersisted_generation_input", "provenance": {"kind": "human_provided", "source": "generation_only_action_json"}}
            if "replaces_span" in raw: answer["replaces_span"] = raw["replaces_span"]
            record["answers"].append(answer)
            record["questions"][qid].update(status="ANSWERED", current_answer_id=aid)
    return record


def validation_signature(text: str, row: dict[str, Any], source: str,
                         peers: list[dict[str, Any]], record: dict[str, Any] | None) -> str:
    payload = {"policy": POLICY_VERSION, "text": text, "human_decision": row.get("human_decision"),
               "selected_candidate_id": row.get("selected_candidate_id"),
               "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
               "peers": peers, "questions": record.get("questions", {}) if record else row.get("clarification_questions", []),
               "answers": record.get("answers", []) if record else [],
               "escalation_active": record.get("escalation_active", False) if record else False,
               "clarification_requested": record.get("clarification_requested", False) if record else False}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
