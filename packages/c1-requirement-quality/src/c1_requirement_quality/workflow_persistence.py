"""Internal, cumulative human workflow ledger; frozen C1 contract stays unchanged."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from c1_requirement_quality.refinement import (
    clarification_questions_for, process_refinement_actions, stable_candidate_id,
)
from c1_requirement_quality.source_integrity import sha256, verify_source
from c1_requirement_quality.validation_lifecycle import original_assessments, clarification_resolution, validation_signature

WORKFLOW_FILE = "workflow_snapshot.json"
STATUSES = {"OPEN", "ANSWERED", "REOPENED", "CLOSED"}
BASE_FIELDS = {"requirement_id", "clarification_questions", "clarification_answers",
               "candidate_texts", "selected_candidate_id", "selected_candidate_text",
               "human_decision", "edited_text"}
EXTRA_FIELDS = {"actor_id", "human_timestamp", "workflow_action", "question_actions",
                "reconsider_candidate_ids", "resolution", "reason"}
WORKFLOW_ACTIONS = {"approve", "reject", "request_clarification", "escalate", "reopen", "resolve_escalation"}


def question_id(requirement_id: str, text: str) -> str:
    canonical = " ".join(text.split())
    return "QUESTION-" + hashlib.sha256(f"{requirement_id}\0{canonical}".encode("utf-8")).hexdigest()


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _actor(action: dict[str, Any]) -> str:
    return _text(action["actor_id"], "actor_id") if "actor_id" in action else "unknown"


def _event(state: dict[str, Any], rid: str, kind: str, actor: str, payload: dict[str, Any],
           human_timestamp: str | None = None) -> dict[str, Any]:
    event = {"event_id": "EVENT-" + uuid.uuid4().hex, "snapshot_id": state["snapshot_id"],
             "requirement_id": rid, "kind": kind, "actor_id": actor,
             "recorded_at": datetime.now(timezone.utc).isoformat(),
             "timestamp_basis": "system_recorded_at", "payload": copy.deepcopy(payload)}
    if human_timestamp is not None:
        event["human_timestamp"] = _text(human_timestamp, "human_timestamp")
    state["events"].append(event)
    return event


def _question(state: dict[str, Any], rid: str, text: str, origin: str, actor: str) -> dict[str, Any]:
    text = _text(text, "question text")
    qid = question_id(rid, text)
    questions = state["requirements"][rid]["questions"]
    if qid not in questions:
        event = _event(state, rid, "question_created", actor, {"question_id": qid, "text": text, "origin": origin})
        questions[qid] = {"question_id": qid, "requirement_id": rid, "text": text,
                          "historical_texts": [text], "origins": [origin], "status": "OPEN",
                          "created_event_id": event["event_id"], "current_answer_id": None}
    else:
        q = questions[qid]
        if text not in q["historical_texts"] or origin not in q["origins"]:
            _event(state, rid, "question_observed", actor, {"question_id": qid, "text": text, "origin": origin})
            if text not in q["historical_texts"]: q["historical_texts"].append(text)
            if origin not in q["origins"]: q["origins"].append(origin)
    return questions[qid]


def _answer(state: dict[str, Any], rid: str, item: dict[str, Any], actor: str,
            human_timestamp: str | None = None, origin: str = "action_json") -> None:
    if not isinstance(item, dict) or set(item) - {"question", "question_id", "requirement_id", "answer", "actor_id", "human_timestamp", "provenance", "replaces_span"}:
        raise ValueError("Invalid clarification answer fields")
    if item.get("requirement_id", rid) != rid:
        raise ValueError("Answer belongs to another requirement")
    questions = state["requirements"][rid]["questions"]
    qid = item.get("question_id")
    if "question" in item:
        derived = question_id(rid, _text(item["question"], "answer question"))
        if qid is not None and qid != derived:
            raise ValueError("Answer question ID and text disagree")
        qid = derived
    if qid not in questions:
        raise ValueError("Answer must reference a recorded question for this requirement")
    text = _text(item.get("answer"), "answer")
    provenance = item.get("provenance")
    if provenance is not None and not isinstance(provenance, (str, dict)):
        raise ValueError("Answer provenance must be a string or object")
    payload = {"question_id": qid, "answer": text,
               "provenance": {"kind": "human_provided", "source": origin, "supplied": provenance}}
    if "replaces_span" in item:
        payload["replaces_span"] = _text(item["replaces_span"], "replaces_span")
    event = _event(state, rid, "answer_recorded", _actor(item) if "actor_id" in item else actor,
                   payload, item.get("human_timestamp", human_timestamp))
    answer = {"answer_id": "ANSWER-" + uuid.uuid4().hex, "requirement_id": rid,
              "question_id": qid, "answer": text, "actor_id": event["actor_id"],
              "provenance": payload["provenance"], "snapshot_id": state["snapshot_id"],
              "event_id": event["event_id"], "resolution_state": "ANSWERED"}
    if "human_timestamp" in event: answer["human_timestamp"] = event["human_timestamp"]
    if "replaces_span" in payload: answer["replaces_span"] = payload["replaces_span"]
    state["requirements"][rid]["answers"].append(answer)
    questions[qid]["current_answer_id"] = answer["answer_id"]
    questions[qid]["status"] = "ANSWERED"
    questions[qid].pop("closure_kind", None)


def initial_state(artifact: dict[str, Any], manifest: dict[str, Any], *, snapshot_id: str | None = None,
                  source_text: str | None = None) -> dict[str, Any]:
    state = {"workflow_version": 1, "snapshot_id": snapshot_id or "SNAPSHOT-" + uuid.uuid4().hex,
             "parent": None, "round": 0,
             "source_identity": {k: manifest[k] for k in ("document_id", "sha256", "normalized_sha256")},
             "requirements": {}, "events": []}
    baselines = original_assessments(artifact, source_text)
    for row in artifact["requirements"]:
        rid = row["requirement_id"]
        state["requirements"][rid] = {"questions": {}, "answers": [], "candidates": {},
                                      "human_decision": row.get("human_decision", "pending"),
                                      "selected_candidate_id": row.get("selected_candidate_id"),
                                      "clarification_requested": False,
                                      "original_assessment": baselines[rid],
                                      "original_snapshot_id": state["snapshot_id"],
                                      "escalation_active": row["tier"] == "TIER_3_ESCALATE"}
        for text in clarification_questions_for(row["original_text"]):
            _question(state, rid, text, "system_placeholder", "system")
        for text in row.get("clarification_questions", []):
            _question(state, rid, text, "existing_contract", "unknown")
        _sync_candidates(state, row)
        if row.get("human_decision", "pending") != "pending":
            _event(state, rid, "decision_imported", "unknown", {"human_decision": row["human_decision"], "source": "existing_contract"})
        _workflow_status(state, row)
    return state


def _sync_candidates(state: dict[str, Any], row: dict[str, Any]) -> None:
    record = state["requirements"][row["requirement_id"]]
    for candidate in row.get("candidates", []):
        cid = candidate["candidate_id"]
        if cid not in record["candidates"]:
            record["candidates"][cid] = {"text": candidate["text"], "status": "PROPOSED"}
    selected = row.get("selected_candidate_id")
    if selected is not None and selected in record["candidates"]:
        status = {"rejected": "REJECTED", "approved": "APPROVED", "edited": "APPROVED"}.get(row["human_decision"])
        if status: record["candidates"][selected]["status"] = status
    record["human_decision"] = row["human_decision"]
    record["selected_candidate_id"] = selected


def _workflow_status(state: dict[str, Any], row: dict[str, Any]) -> None:
    record = state["requirements"][row["requirement_id"]]
    record["unanswered_question_ids"] = [q["question_id"] for q in record["questions"].values() if q["status"] in {"OPEN", "REOPENED"}]
    resolved = clarification_resolution(record, row["original_text"], [])
    record["validation_unresolved_question_ids"] = [q["question_id"] for q in resolved["assessments"] if not q["resolved"]]
    if row["tier"] == "TIER_3_ESCALATE": record["escalation_active"] = True
    if record["escalation_active"]:
        status = "AWAITING_ESCALATION"
    elif row["human_decision"] == "rejected":
        status = "REJECTED"
    elif record["validation_unresolved_question_ids"] or record.get("clarification_requested") or row["tier"] == "TIER_2_CLARIFY":
        status = "AWAITING_CLARIFICATION"
    elif row.get("bdd_ready"):
        status = "VALIDATED"
    else:
        status = "REVIEW_PENDING"
    record["workflow_status"] = status


def write_state(c1_dir: Path, state: dict[str, Any]) -> None:
    state = copy.deepcopy(state)
    state["artifact_sha256"] = sha256((c1_dir / "validated_requirements.json").read_bytes())
    source_text = json.loads((c1_dir / "internal/normalized_ingestion.json").read_text(encoding="utf-8"))["raw_text"]
    _validate_state(state, json.loads((c1_dir / "validated_requirements.json").read_text(encoding="utf-8")),
                    state["source_identity"], source_text)
    path = c1_dir / "internal" / WORKFLOW_FILE
    with path.open("x", encoding="utf-8") as stream:
        json.dump(state, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    path.chmod(0o444)


def _validate_state(state: dict[str, Any], artifact: dict[str, Any], manifest: dict[str, Any],
                    source_text: str | None = None) -> None:
    if (state.get("workflow_version") != 1 or not isinstance(state.get("snapshot_id"), str)
            or not isinstance(state.get("round"), int) or state["round"] < 0
            or state.get("source_identity") != {k: manifest[k] for k in ("document_id", "sha256", "normalized_sha256")}
            or set(state.get("requirements", {})) != {r["requirement_id"] for r in artifact["requirements"]}):
        raise ValueError("Workflow snapshot identity or requirement membership mismatch")
    events = {event["event_id"]: event for event in state["events"]}
    if len(events) != len(state["events"]): raise ValueError("Duplicate workflow event IDs")
    from c1_requirement_quality.effective_consistency import validate_adopted
    reviews = {}
    for event in state["events"]:
        if event["kind"] == "consistency_review_adopted":
            review = event["payload"]
            validate_adopted(review)
            prior = reviews.get(review["pair_id"])
            if review["supersedes"] != (prior["review_id"] if prior else None):
                raise ValueError("Consistency review supersession mismatch")
            if not set(review["requirement_ids"]) <= set(state["requirements"]):
                raise ValueError("Consistency review references unknown requirements")
            reviews[review["pair_id"]] = review
    for row in artifact["requirements"]:
        rid = row["requirement_id"]; record = state["requirements"][rid]
        if record["human_decision"] != row["human_decision"] or record["selected_candidate_id"] != row.get("selected_candidate_id"):
            raise ValueError("Workflow decision disagrees with contract snapshot")
        if {cid: item["text"] for cid, item in record["candidates"].items()} != {c["candidate_id"]: c["text"] for c in row.get("candidates", [])}:
            raise ValueError("Workflow candidates disagree with contract snapshot")
        answers = {answer["answer_id"]: answer for answer in record["answers"]}
        if len(answers) != len(record["answers"]): raise ValueError("Duplicate answer IDs")
        for qid, q in record["questions"].items():
            if (qid != question_id(rid, q["text"]) or q["requirement_id"] != rid or q["status"] not in STATUSES
                    or q["created_event_id"] not in events or q["current_answer_id"] is not None and q["current_answer_id"] not in answers):
                raise ValueError("Invalid workflow question or answer reference")
            current = q["current_answer_id"]
            if (current is not None and answers[current]["question_id"] != qid
                    or q["status"] == "ANSWERED" and current is None
                    or q["status"] in {"OPEN", "REOPENED"} and current is not None):
                raise ValueError("Question current answer or resolution state mismatch")
        for answer in answers.values():
            if answer["requirement_id"] != rid or answer["question_id"] not in record["questions"] or answer["event_id"] not in events:
                raise ValueError("Invalid answer event or requirement reference")
            event = events[answer["event_id"]]
            if (event["kind"] != "answer_recorded" or event["requirement_id"] != rid
                    or event["snapshot_id"] != answer["snapshot_id"]
                    or event["payload"]["question_id"] != answer["question_id"]
                    or event["payload"]["answer"] != answer["answer"]):
                raise ValueError("Answer content disagrees with its event")
        expected = [q["question_id"] for q in record["questions"].values() if q["status"] in {"OPEN", "REOPENED"}]
        if record["unanswered_question_ids"] != expected: raise ValueError("Unanswered question index mismatch")
        current_validation = record.get("current_validation")
        if current_validation is not None and source_text is not None:
            peers = [{"requirement_id": r["requirement_id"], "text": r["final_text"]} for r in artifact["requirements"]]
            if (current_validation["signature"] != validation_signature(row["final_text"], row, source_text, peers, record)
                    or current_validation["checks"] != row["validation"] or current_validation["final_text"] != row["final_text"]
                    or current_validation["tier"]["tier"] != row["tier"] or current_validation["bdd_ready"] != row["bdd_ready"]):
                raise ValueError("Current validation signature or artifact mismatch")


def load_state(input_path: Path, source: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify the complete parent chain, hashes, identity and cumulative history."""
    current = input_path.resolve(); seen_paths: set[Path] = set(); seen_ids: set[str] = set()
    child: dict[str, Any] | None = None; result = None; first_manifest = None
    while True:
        if current in seen_paths: raise ValueError("Snapshot lineage cycle")
        seen_paths.add(current)
        original_source_text, manifest = verify_source(current, source)
        artifact = json.loads(current.read_text(encoding="utf-8-sig"))
        path = current.parent / "internal" / WORKFLOW_FILE
        expected_hash = manifest.get("workflow_sha256")
        if expected_hash is None:
            if path.exists(): raise ValueError("Unsealed workflow snapshot")
            # Phase 1B.1 snapshot adoption is prospective, without modifying it.
            sid = "SNAPSHOT-LEGACY-" + sha256(current.read_bytes())
            state = initial_state(artifact, manifest, snapshot_id=sid, source_text=original_source_text)
            diagnostics = current.parent / "refinement_diagnostics.json"
            if diagnostics.exists():
                data = json.loads(diagnostics.read_text(encoding="utf-8"))
                for diagnostic in data:
                    rid = diagnostic["requirement_id"]
                    if rid not in state["requirements"]: raise ValueError("Legacy diagnostics requirement mismatch")
                    for answer in diagnostic.get("clarification_answers", []):
                        if "question" in answer: _question(state, rid, answer["question"], "legacy_diagnostics_unsealed", "unknown")
                        _answer(state, rid, answer, "unknown", origin="legacy_diagnostics_unsealed")
                state["legacy_diagnostics_sha256"] = sha256(diagnostics.read_bytes())
                for row in artifact["requirements"]: _workflow_status(state, row)
        else:
            raw = path.read_bytes()
            if sha256(raw) != expected_hash: raise ValueError("Workflow snapshot hash mismatch")
            state = json.loads(raw.decode("utf-8"))
            if state.get("artifact_sha256") != manifest["artifact_sha256"]: raise ValueError("Workflow artifact binding mismatch")
            _validate_state(state, artifact, manifest, original_source_text)
        if state["snapshot_id"] in seen_ids: raise ValueError("Repeated snapshot identity in lineage")
        seen_ids.add(state["snapshot_id"])
        if child is not None:
            reference = child["parent"]
            if (reference["snapshot_id"] != state["snapshot_id"] or reference["artifact_sha256"] != manifest["artifact_sha256"]
                    or reference["workflow_sha256"] != expected_hash or child["round"] != state["round"] + 1
                    or reference.get("legacy_diagnostics_sha256") != state.get("legacy_diagnostics_sha256")
                    or child["source_identity"] != state["source_identity"]):
                raise ValueError("Parent snapshot reference mismatch")
            if expected_hash is not None:
                if child["events"][:len(state["events"])] != state["events"]:
                    raise ValueError("Cumulative event history does not preserve its parent")
                for rid, record in state["requirements"].items():
                    if child["requirements"][rid]["answers"][:len(record["answers"])] != record["answers"]:
                        raise ValueError("Cumulative answer history does not preserve its parent")
                    new_record = child["requirements"][rid]
                    if "original_assessment" in record and new_record.get("original_assessment") != record["original_assessment"]:
                        raise ValueError("Original assessment changed across snapshots")
                    for qid, question in record["questions"].items():
                        successor = new_record["questions"].get(qid)
                        if (successor is None or successor["text"] != question["text"]
                                or successor["historical_texts"][:len(question["historical_texts"])] != question["historical_texts"]):
                            raise ValueError("Cumulative question history does not preserve its parent")
                    for cid, candidate in record["candidates"].items():
                        successor = new_record["candidates"].get(cid)
                        if successor is None or successor["text"] != candidate["text"]:
                            raise ValueError("Candidate history does not preserve its parent")
                        if candidate["status"] == "REJECTED" and successor["status"] != "REJECTED":
                            if not any(e["kind"] == "candidate_reconsidered" and e["requirement_id"] == rid
                                       and e["payload"]["candidate_id"] == cid for e in child["events"][len(state["events"]):]):
                                raise ValueError("Rejected candidate changed without a reconsideration event")
        if result is None: result, first_manifest = state, manifest
        parent = state.get("parent")
        if parent is None:
            if state["round"] != 0: raise ValueError("Non-root snapshot has no parent")
            break
        location = parent.get("artifact_path")
        if not isinstance(location, str) or Path(location).is_absolute() or "\\" in location:
            raise ValueError("Parent artifact path must be relative with forward slashes")
        child, current = state, (current.parent / location).resolve()
        if not current.is_file(): raise ValueError("Parent snapshot artifact is missing")
    if any(event["snapshot_id"] not in seen_ids or event["requirement_id"] not in result["requirements"] for event in result["events"]):
        raise ValueError("Event references an unknown snapshot or requirement")
    # Adopt earlier 1B.2 ledgers prospectively using their verified root artifact.
    baselines = original_assessments(artifact, original_source_text)
    for rid, record in result["requirements"].items():
        if "original_assessment" not in record:
            record["original_assessment"] = copy.deepcopy(state["requirements"][rid].get("original_assessment", baselines[rid]))
            record["original_snapshot_id"] = state["snapshot_id"]
        if record["original_snapshot_id"] != state["snapshot_id"]:
            raise ValueError("Original assessment snapshot reference does not match verified root")
    return result, first_manifest


def current_answer_actions(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Reuse recorded active answers, never reopened/superseded answers or SRS facts."""
    result = []
    for rid, record in state["requirements"].items():
        answers = {a["answer_id"]: a for a in record["answers"]}
        current = [{"question": q["text"], "answer": answers[q["current_answer_id"]]["answer"]}
                   for q in record["questions"].values() if q["current_answer_id"] is not None]
        result.append({"requirement_id": rid, "clarification_answers": current})
    return result


def refine_with_history(artifact: dict[str, Any], actions: dict[str, Any], source_text: str,
                        parent: dict[str, Any], parent_path: Path, final_c1_dir: Path,
                        manifest: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if (set(actions) - {"requirements", "consistency_reviews"} or "requirements" not in actions
            or not isinstance(actions["requirements"], list)):
        raise ValueError("Actions require requirements and optional consistency_reviews lists")
    from c1_requirement_quality.effective_consistency import context_from_state, views, create_review, assess_all
    state = copy.deepcopy(parent)
    state.update(snapshot_id="SNAPSHOT-" + uuid.uuid4().hex, round=parent["round"] + 1,
                 parent={"snapshot_id": parent["snapshot_id"],
                         "artifact_path": os.path.relpath(parent_path.resolve(), final_c1_dir.resolve()).replace("\\", "/"),
                         "artifact_sha256": manifest["artifact_sha256"], "workflow_sha256": manifest.get("workflow_sha256"),
                         "legacy_diagnostics_sha256": parent.get("legacy_diagnostics_sha256")})
    rows = {r["requirement_id"]: r for r in artifact["requirements"]}
    supplied = {}
    prepared = []
    requests = actions.get("consistency_reviews", [])
    if not isinstance(requests, list): raise ValueError("consistency_reviews must be a list")
    if requests and actions["requirements"]:
        raise ValueError("Record consistency reviews separately from requirement edits or approvals")
    seen_pairs = set()
    for request in requests:
        if not isinstance(request, dict): raise ValueError("Invalid consistency review request")
        ids = request.get("requirement_ids")
        if (not isinstance(ids, list) or len(ids) != 2 or any(not isinstance(i, str) for i in ids)
                or len(set(ids)) != 2): raise ValueError("Two distinct requirement IDs required")
        matching = [v for v in views(list(rows.values()), state["requirements"], context_from_state(state))
                    if v["requirement_ids"] == sorted(ids)]
        if len(matching) != 1 or matching[0]["pair_id"] in seen_pairs: raise ValueError("Unknown or repeated pair")
        seen_pairs.add(matching[0]["pair_id"])
        review = create_review(matching[0], {k: v for k, v in request.items() if k != "requirement_ids"})
        _event(state, ids[0], "consistency_review_adopted", review["reviewer"], review)
    for action in actions["requirements"]:
        if not isinstance(action, dict) or set(action) - BASE_FIELDS - EXTRA_FIELDS:
            raise ValueError("Unsupported workflow action fields")
        rid = action.get("requirement_id")
        if rid not in rows or rid in supplied: raise ValueError("Unknown or duplicate requirement action")
        supplied[rid] = action
    for rid, row in rows.items():
        action = supplied.get(rid, {"requirement_id": rid})
        actor = _actor(action); timestamp = action.get("human_timestamp")
        if timestamp is not None: _text(timestamp, "human_timestamp")
        record = state["requirements"][rid]
        work_action = action.get("workflow_action")
        if work_action is not None and work_action not in WORKFLOW_ACTIONS: raise ValueError("Invalid workflow_action")
        for text in clarification_questions_for(row["original_text"]): _question(state, rid, text, "system_placeholder", "system")
        custom = action.get("clarification_questions", [])
        if not isinstance(custom, list): raise ValueError("clarification_questions must be a list")
        for text in custom: _question(state, rid, text, "human_question", actor)
        answers = action.get("clarification_answers", [])
        if not isinstance(answers, list): raise ValueError("clarification_answers must be a list")
        for item in answers: _answer(state, rid, item, actor, timestamp)
        operations = action.get("question_actions", [])
        if not isinstance(operations, list): raise ValueError("question_actions must be a list")
        reopening = work_action == "reopen"
        if reopening and not operations:
            operations = [{"question_id": qid, "status": "REOPENED"} for qid in record["questions"]]
        for operation in operations:
            if not isinstance(operation, dict) or set(operation) - {"question_id", "status", "reason", "closure_kind"}: raise ValueError("Invalid question action")
            qid = operation.get("question_id"); status = operation.get("status")
            if qid not in record["questions"] or status not in {"REOPENED", "CLOSED"}: raise ValueError("Question action needs a known question and REOPENED/CLOSED status")
            _event(state, rid, "question_status_changed", actor, operation, timestamp)
            record["questions"][qid]["status"] = status
            if status == "CLOSED":
                kind = operation.get("closure_kind", "DEFERRED")
                if kind not in {"ANSWERED", "DEFERRED", "WAIVED"}: raise ValueError("Invalid closure_kind")
                record["questions"][qid]["closure_kind"] = kind
            if status == "REOPENED":
                record["questions"][qid]["current_answer_id"] = None
                reopening = True
        reconsider = action.get("reconsider_candidate_ids", [])
        if not isinstance(reconsider, list): raise ValueError("reconsider_candidate_ids must be a list")
        for cid in reconsider:
            if cid not in record["candidates"]: raise ValueError("Unknown candidate to reconsider")
            _event(state, rid, "candidate_reconsidered", actor, {"candidate_id": cid}, timestamp)
            record["candidates"][cid]["status"] = "PROPOSED"
        translated = {key: copy.deepcopy(value) for key, value in action.items() if key in BASE_FIELDS}
        if answers and row["human_decision"] in {"approved", "edited", "not_required"} and "human_decision" not in action:
            translated["human_decision"] = "pending"
        if row.get("selected_candidate_id") in reconsider and "human_decision" not in action:
            translated["human_decision"] = "pending"
        aliases = {"approve": "approved", "reject": "rejected"}
        if work_action in aliases:
            if "human_decision" in action and action["human_decision"] != aliases[work_action]: raise ValueError("Conflicting human decision and workflow action")
            translated["human_decision"] = aliases[work_action]
        if work_action in {"request_clarification", "escalate", "reopen"} or reopening:
            if translated.get("human_decision") in {"approved", "edited", "not_required"}: raise ValueError("Cannot approve while reopening or requesting human review")
            # A simultaneous explicit rejection is retained; neither review nor
            # reopening can erase it or imply approval.
            translated["human_decision"] = action.get("human_decision", "pending")
        if work_action == "escalate": record["escalation_active"] = True
        if work_action == "request_clarification":
            record["clarification_requested"] = True
        elif (answers or operations) and record["questions"] and all(
            q["status"] in {"ANSWERED", "CLOSED"} for q in record["questions"].values()
        ):
            record["clarification_requested"] = False
        if work_action == "resolve_escalation":
            _text(action.get("resolution"), "explicit escalation resolution")
            if not record["escalation_active"]: raise ValueError("No active escalation to resolve")
            record["escalation_active"] = False
        effective = translated.get("human_decision", row["human_decision"])
        if (("human_decision" in action or work_action in aliases)
                and effective in {"approved", "edited", "not_required"}
                and all(q["status"] in {"ANSWERED", "CLOSED"} for q in record["questions"].values())):
            record["clarification_requested"] = False
        if record["escalation_active"] and effective in {"approved", "edited", "not_required"} and (
            "human_decision" in action or work_action in aliases
        ):
            raise ValueError("Explicit escalation resolution is required before accepting a requirement")
        selected = translated.get("selected_candidate_id", row.get("selected_candidate_id"))
        if "selected_candidate_text" in translated: selected = stable_candidate_id(rid, translated["selected_candidate_text"])
        if translated.get("human_decision") == "edited" and "edited_text" in translated: selected = stable_candidate_id(rid, translated["edited_text"])
        if selected in record["candidates"] and record["candidates"][selected]["status"] == "REJECTED":
            if ("selected_candidate_id" in action or "selected_candidate_text" in action or effective in {"approved", "edited"}):
                raise ValueError("Rejected candidate requires explicit reconsider_candidate_ids")
        translated["clarification_questions"] = [q["text"] for q in record["questions"].values()]
        current_answers = {a["answer_id"]: a for a in record["answers"]}
        translated["clarification_answers"] = [{"question": q["text"], "answer": current_answers[q["current_answer_id"]]["answer"]}
                                               for q in record["questions"].values() if q["current_answer_id"] is not None]
        prepared.append(translated)
        if rid in supplied:
            _event(state, rid, "human_action", actor, action, timestamp)
        if work_action is not None:
            _event(state, rid, work_action, actor, {"resolution": action.get("resolution"), "reason": action.get("reason")}, timestamp)
        if "human_decision" in action or work_action in aliases:
            _event(state, rid, "human_decision", actor, {"human_decision": translated["human_decision"], "candidate_id": selected}, timestamp)
    review_context = context_from_state(state)
    # Invalidate changed/stale bindings once, retaining immutable historical events.
    invalidated = {e["payload"]["review_id"] for e in state["events"] if e["kind"] == "consistency_review_invalidated"}
    current_views = {v["pair_id"]: v for v in views(list(rows.values()), state["requirements"], review_context)}
    for review in review_context["history"]:
        view = current_views.get(review["pair_id"])
        if review["review_id"] not in invalidated and (not view or review["binding"] != view["binding"]):
            _event(state, review["requirement_ids"][0], "consistency_review_invalidated", "system",
                   {"review_id": review["review_id"], "reason": "Review binding changed"})
    review_context = context_from_state(state)
    assessments = assess_all(list(rows.values()), state["requirements"], review_context)
    for action in prepared:
        rid = action["requirement_id"]
        basis = assessments[rid].get("review_basis")
        previous_basis = parent["requirements"][rid].get("consistency_review_basis")
        if basis != previous_basis and (basis is not None or previous_basis is not None):
            if rows[rid]["human_decision"] in {"approved", "edited", "not_required"}:
                action["human_decision"] = "pending"
                _event(state, rid, "approval_invalidated", "system", {"reason": "Consistency review basis changed"})
        if basis is not None: state["requirements"][rid]["consistency_review_basis"] = basis
    refined, diagnostics = process_refinement_actions(artifact, {"requirements": prepared}, source_text,
        workflow_records=state["requirements"], consistency_context=review_context)
    # Re-evaluate after accepted edits change the final peer set. Reset stale
    # approvals before publication, including approvals on the other endpoint.
    for _ in range(len(rows) + 2):
        changed = False
        current_context = context_from_state(state)
        final_views = {v["pair_id"]: v for v in views(refined["requirements"], state["requirements"], current_context)}
        invalidated = {e["payload"]["review_id"] for e in state["events"] if e["kind"] == "consistency_review_invalidated"}
        for review in current_context["history"]:
            view = final_views.get(review["pair_id"])
            if review["review_id"] not in invalidated and (not view or review["binding"] != view["binding"]):
                _event(state, review["requirement_ids"][0], "consistency_review_invalidated", "system",
                       {"review_id": review["review_id"], "reason": "Final peer text or evidence changed"})
                changed = True
        current_context = context_from_state(state)
        reset = []
        assessments = assess_all(refined["requirements"], state["requirements"], current_context)
        for row in refined["requirements"]:
            rid = row["requirement_id"]
            basis = assessments[rid].get("review_basis")
            previous_basis = state["requirements"][rid].get("consistency_review_basis")
            if basis != previous_basis and row["human_decision"] in {"approved", "edited", "not_required"}:
                reset.append({"requirement_id": rid, "human_decision": "pending"})
                _event(state, rid, "approval_invalidated", "system", {"reason": "Final consistency review basis changed"})
            if basis is not None: state["requirements"][rid]["consistency_review_basis"] = basis
        if not changed and not reset: break
        refined, diagnostics = process_refinement_actions(refined, {"requirements": reset}, source_text,
            workflow_records=state["requirements"], consistency_context=current_context)
    else:
        raise ValueError("Consistency approval invalidation did not converge; snapshot not published")
    for row in refined["requirements"]:
        rid = row["requirement_id"]
        _sync_candidates(state, row)
        _workflow_status(state, row)
        diagnostic = next(d for d in diagnostics if d["requirement_id"] == rid)
        diagnostic["workflow_status"] = state["requirements"][rid]["workflow_status"]
        diagnostic["unanswered_question_ids"] = state["requirements"][rid]["unanswered_question_ids"]
        diagnostic["answer_history"] = copy.deepcopy(state["requirements"][rid]["answers"])
        diagnostic["original_assessment"] = copy.deepcopy(state["requirements"][rid]["original_assessment"])
        diagnostic["validation_signature"] = validation_signature(
            row["final_text"], row, source_text,
            [{"requirement_id": r["requirement_id"], "text": r["final_text"]} for r in refined["requirements"]],
            state["requirements"][rid],
        )
        state["requirements"][rid]["current_validation"] = {
            "signature": diagnostic["validation_signature"], "final_text": row["final_text"],
            "tier": copy.deepcopy(diagnostic["tier"]), "checks": copy.deepcopy(row["validation"]),
            "grounding_categories": copy.deepcopy(diagnostic["grounding_categories"]),
            "clarification_resolution": copy.deepcopy(diagnostic["clarification_resolution"]),
            "candidate_assessments": copy.deepcopy(diagnostic["candidates"]), "bdd_ready": row["bdd_ready"],
        }
        if state["requirements"][rid]["escalation_active"] and row["bdd_ready"]:
            raise ValueError("Active escalation cannot produce a ready requirement")
    return refined, diagnostics, state
