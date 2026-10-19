"""Saved-sidecar terminal review; existing C1 services own all decision policy."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable
from contextlib import contextmanager

from c1_requirement_quality.source_integrity import verify_source, _verify_snapshot
from c1_requirement_quality.workflow_persistence import load_state
from c1_requirement_quality.refinement import stable_candidate_id, _evaluate_candidate, _consistency_with_candidate, _candidate_validation
from c1_requirement_quality.tier_classifier import classify_tier
from c1_requirement_quality.validation_lifecycle import clarification_resolution
from c1_requirement_quality.clarification_proposals import _load_diagnostics, _context, validate_proposal


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _verified_journal(workspace: Path, anchor=None) -> list[dict[str, Any]]:
    """Read the hash chain once, optionally through an exact retained prefix."""
    events = []
    previous = None
    for index, path in enumerate(sorted((workspace / "events").glob("*.json")), 1):
        if anchor is not None and index > anchor["sequence"]:
            break
        event = json.loads(path.read_bytes())
        if not isinstance(event, dict):
            raise ValueError("Invalid demo journal event")
        signature = event.get("sha256")
        body = {key: value for key, value in event.items() if key != "sha256"}
        if (event.get("sequence") != index or event.get("previous") != previous
                or _hash(json.dumps(body, sort_keys=True).encode()) != signature):
            raise ValueError("Invalid demo journal chain")
        events.append(event)
        previous = signature
    if anchor is not None and (len(events) != anchor["sequence"] or previous != anchor["sha256"]):
        raise ValueError("Registry journal prefix anchor mismatch")
    return events


def _write(path: Path, value: Any) -> None:
    """Atomically publish a new journal/action file, never replace existing content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending-" + uuid.uuid4().hex)
    binary = isinstance(value, bytes)
    with pending.open("xb" if binary else "x", encoding=None if binary else "utf-8") as stream:
        if binary:
            stream.write(value)
        else:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(pending, path)
    pending.unlink()


@contextmanager
def _session_lock(workspace: Path):
    """OS releases this lock even after a hard crash; no stale PID-file replay."""
    with (workspace / ".demo.lock").open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Another terminal owns this demo session; no changes made") from None
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class DemoSession:
    """Append-only review intents alongside independently sealed C1 snapshots."""

    @classmethod
    def create(cls, workspace: Path, *, artifact: Path | None = None, source: Path | None = None,
               run_id: str | None = None, registry: Path | None = None,
               project_code: str = "EX", document_id: str | None = None, progress=None, stage_progress=None,
               mandatory_ml: bool = False, classifier: Any | None = None,
               mandatory_rag: bool = False) -> DemoSession:
        from c1_requirement_quality import cli
        workspace = workspace.resolve()
        if (mandatory_ml or mandatory_rag) and artifact is not None:
            raise ValueError("Mandatory initial ML analysis requires a new source analysis")
        if workspace.exists():
            raise FileExistsError("New demo workspace must not exist; use --resume for an existing session")
        if artifact is not None:
            artifact = artifact.resolve()
            manifest = json.loads((artifact.parent / "internal/source_manifest.json").read_text(encoding="utf-8"))
            source = source.resolve() if source else artifact.parent / "internal" / manifest["archived_source"]
            _, manifest, data, _ = _verify_snapshot(artifact, source)
            cli._validate_contract_artifact(data)
            initial_hash = manifest["artifact_sha256"]
        else:
            if source is None or registry is None or run_id is None:
                raise ValueError("New analysis requires --srs, --registry and --run-id")
            source = source.resolve()
            if not source.is_file():
                raise FileNotFoundError(source)
            artifact = workspace / "initial/c1/validated_requirements.json"
            initial_hash = None
        if artifact.drive.lower() != workspace.drive.lower():
            raise ValueError("Session and run family must be on the same drive for relative workflow ancestry")
        source_hash = _hash(source.read_bytes())
        original_source = source
        if initial_hash is None:
            source = artifact.parent / "internal/source" / source.name
        workspace.mkdir(parents=True)
        _write(workspace / "session.json", {"version": 1, "base_artifact": str(artifact),
            "base_sha256": initial_hash, "source": str(source), "source_sha256": source_hash,
            "expected_run_id": run_id if initial_hash is None else None,
            "mandatory_ml": mandatory_ml, "mandatory_rag": mandatory_rag})
        if initial_hash is None:
            try:
                cli.run(original_source, workspace / "initial", run_id, project_code,
                        registry_path=registry, grounding_mode="rag" if mandatory_rag else "lexical",
                        document_id=document_id, progress=progress, stage_progress=stage_progress,
                        mandatory_rag=mandatory_rag)
            except Exception as error:
                if mandatory_rag and "Mandatory RAG grounding incomplete" in str(error):
                    _write(workspace / "rag_failure.json", {"status": "incomplete", "error": str(error)})
                raise
        if mandatory_ml:
            if stage_progress:
                stage_progress("review", "pending", "Waiting for mandatory ML classification")
                stage_progress("ml", "running", "Verifying and running local DistilBERT; experimental scores only")
            try:
                from c1_requirement_quality.ml.ml_diagnostics import defect_diagnostics_run
                sidecar = workspace / "sidecars/initial-defect-predictions.json"
                defect_diagnostics_run(artifact, sidecar, classifier=classifier)
                _, manifest, data, _ = _verify_snapshot(artifact, source)
                _, digest = _load_diagnostics(sidecar, data, manifest["artifact_sha256"], "distilbert")
                _write(workspace / "ml_analysis.json", {
                    "status": "completed", "input_sha256": manifest["artifact_sha256"],
                    "sidecar_sha256": digest,
                })
            except Exception as error:
                detail = f"{type(error).__name__}: {error}"
                _write(workspace / "ml_failure.json", {"status": "incomplete", "error": detail})
                if stage_progress: stage_progress("ml", "failed", detail)
                raise ValueError(f"Mandatory ML classification incomplete: {detail}") from error
            if stage_progress:
                stage_progress("ml", "completed", "Five-label scores saved; no threshold or decision effect")
                stage_progress("review", "running", "Verifying session and saved predictions")
        return cls(workspace)

    def __init__(self, workspace: Path, *, _registry_anchor=None, analyser_factory=None):
        self.workspace = workspace.resolve()
        self._registry_anchor = _registry_anchor
        from c1_requirement_quality.rag.publication import _factory
        self._analyser_factory = analyser_factory or _factory.get()
        if _registry_anchor is not None:
            if (not isinstance(_registry_anchor, dict) or set(_registry_anchor) != {"sequence", "sha256"}
                    or type(_registry_anchor["sequence"]) is not int or _registry_anchor["sequence"] < 0
                    or (_registry_anchor["sequence"] == 0 and _registry_anchor["sha256"] is not None)
                    or (_registry_anchor["sequence"] > 0 and
                        (not isinstance(_registry_anchor["sha256"], str) or len(_registry_anchor["sha256"]) != 64))):
                raise ValueError("Invalid registry journal prefix anchor")
        self.meta = json.loads((self.workspace / "session.json").read_text(encoding="utf-8"))
        if self.meta.get("version") != 1:
            raise ValueError("Unsupported demo session version")
        self.source = Path(self.meta["source"])
        self.current = Path(self.meta["base_artifact"])
        if not self.current.is_file():
            failure = self.workspace / "rag_failure.json"
            if self.meta.get("mandatory_rag") and failure.is_file():
                raise ValueError(json.loads(failure.read_text(encoding="utf-8"))["error"] + "; no inference replayed")
            raise ValueError("Initial analysis was not published; no operation was replayed. Preserve this workspace and start a fresh one.")
        if self.meta["base_sha256"] and _hash(self.current.read_bytes()) != self.meta["base_sha256"]:
            raise ValueError("Session base artifact changed")
        if _hash(self.source.read_bytes()) != self.meta["source_sha256"]:
            raise ValueError("Session SRS changed")
        self.events = []
        self.pending = None
        self.prepared = None
        self._review_state = None
        self._approval_intents = []
        for event in _verified_journal(self.workspace, _registry_anchor):
            if event["kind"] == "pending":
                if self.pending is not None or event["parent"] != str(self.current):
                    raise ValueError("Invalid pending operation ordering")
                self.pending = event
                self.prepared = None
            elif event["kind"] == "prepared":
                if (self.pending is None or self.pending.get("operation_version") != 2
                        or self.prepared is not None or event["operation_id"] != self.pending["operation_id"]
                        or event["pending_sha256"] != self.pending["sha256"]):
                    raise ValueError("Invalid prepared operation binding")
                self.prepared = event
            elif event["kind"] in {"completed", "cancelled"}:
                if self.pending is None or event["operation_id"] != self.pending["operation_id"]:
                    raise ValueError("Orphan demo operation receipt")
                if event["kind"] == "completed":
                    self._check_child(self.pending)
                    if self.pending.get("operation_version") == 2 and (
                            event.get("prepared_sha256") != self.prepared["sha256"]
                            or event["artifact_sha256"] != self.prepared["commitment"]["artifact_sha256"]):
                        raise ValueError("Completed operation commitment mismatch")
                    self.current = Path(self.pending["out"]) / "c1/validated_requirements.json"
                    self._review_state = None
                    if _hash(self.current.read_bytes()) != event["artifact_sha256"]:
                        raise ValueError("Published snapshot no longer matches receipt")
                self.pending = None
                self.prepared = None
            elif event["kind"] == "consistency_review":
                from c1_requirement_quality.consistency_review import validate_record
                validate_record(event["record"])
                previous_reviews = [e["record"] for e in self.events if e["kind"] == "consistency_review"
                                    and e["record"]["pair_id"] == event["record"]["pair_id"]]
                expected = previous_reviews[-1]["review_id"] if previous_reviews else None
                if (event["record"]["supersedes"] != expected
                        or event["artifact_sha256"] != _hash(self.current.read_bytes())):
                    raise ValueError("Review supersession or artifact binding mismatch")
            elif event["kind"] == "candidate_evidence_registered":
                from c1_requirement_quality.workflow_persistence import candidate_evidence_path, _candidate_snapshot_identity
                from c1_requirement_quality.source_integrity import VerifiedWorkflowContext, resolve_workflow_policy
                reference = candidate_evidence_path(self.workspace, event["reference"])
                if (event["artifact_sha256"] != _hash(self.current.read_bytes())
                        or _hash(reference.read_bytes()) != event["reference_sha256"]):
                    raise ValueError("Candidate registry journal binding mismatch")
                _, _, manifest, state = resolve_workflow_policy(VerifiedWorkflowContext(self.current, self.source))
                if event.get("snapshot_identity") != _candidate_snapshot_identity(manifest, state):
                    raise ValueError("Candidate registry verified snapshot identity mismatch")
            elif event["kind"] in {"refinement_review", "approval_intent"}:
                if self.pending is not None:
                    raise ValueError("Review cannot overlap a pending publication")
                self._replay_refinement_review(event)
            elif event["kind"] != "review":
                raise ValueError("Unknown demo journal event")
            self.events.append(event)
        self.read()

    def review_read(self):
        """Display-only draft overlay. Never a published or approvable C1 artifact."""
        data, text, manifest, state = self.read()
        if not manifest.get("rag_policy"):
            return data, text, manifest, state
        if self._review_state is None and state.get("rag_publication"):
            return data, text, manifest, state
        state = copy.deepcopy(self._review_state or state)
        data = copy.deepcopy(data)
        for row in data["requirements"]:
            record = state["requirements"][row["requirement_id"]]
            row["candidates"] = [{"candidate_id": cid, "text": c["text"]}
                                 for cid, c in record["candidates"].items()]
            row["selected_candidate_id"] = record["selected_candidate_id"]
            row["human_decision"] = "pending"
            row["bdd_ready"] = False
        return data, text, manifest, state

    def _review_basis(self, state):
        from c1_requirement_quality.rag.candidate_validation import _canonical, verification_policy
        _, _, manifest, parent = self.read()
        from c1_requirement_quality.workflow_persistence import _candidate_snapshot_identity
        return {"parent": _candidate_snapshot_identity(manifest, parent),
                "source_manifest_sha256": _hash(_canonical(manifest)),
                "draft_sha256": _hash(_canonical(state)),
                "verification_policy": verification_policy()}

    def _review_evaluation(self, rid, state):
        """Recheck receipt against sealed P; draft answers never become SRS evidence."""
        from c1_requirement_quality.workflow_persistence import (
            _candidate_snapshot_identity, _read_candidate_reference, candidate_evidence_path,
        )
        from c1_requirement_quality.rag.candidate_validation import CandidateGroundingContext
        from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser
        from c1_requirement_quality.source_integrity import VerifiedWorkflowContext
        from c1_requirement_quality.effective_consistency import context_from_state
        data, text, manifest, parent = self.read()
        row = next(r for r in data["requirements"] if r["requirement_id"] == rid)
        record = state["requirements"][rid]
        cid = record["selected_candidate_id"]
        candidate = record["candidates"].get(cid)
        if candidate is None or candidate["status"] == "REJECTED":
            raise ValueError("Select a non-rejected candidate before approval intent")
        refs = []
        for event in self.events:
            if (event["kind"] == "candidate_evidence_registered"
                    and event["snapshot_identity"] == _candidate_snapshot_identity(manifest, parent)):
                reference = _read_candidate_reference(self.workspace, event)
                if reference["candidate_id"] == cid:
                    refs.append((event, reference))
        if len(refs) != 1:
            raise ValueError("Exactly one journal-registered candidate receipt required")
        event, reference = refs[0]
        if reference["requirement_id"] != rid or reference["candidate_text"] != candidate["text"]:
            raise ValueError("Candidate registry selection mismatch")
        context = CandidateGroundingContext(self.current, self.source,
            {cid: (candidate_evidence_path(self.workspace, reference["evidence"]), reference["receipt_sha256"])},
            reference["top_k"], self._analyser_factory or RAGGroundingAnalyser)
        evaluation = _evaluate_candidate(candidate["text"], text, row["original_text"],
            parent["requirements"][rid], grounding_context=context, requirement_id=rid,
            workflow_context=VerifiedWorkflowContext(self.current, self.source))
        if (evaluation["grounding"].get("validation_binding") != reference["binding"]
                or evaluation["grounding"].get("models") != reference["models"]):
            raise ValueError("Candidate receipt and registered reference binding mismatch")
        peers = copy.deepcopy(data["requirements"])
        for peer in peers:
            draft = state["requirements"][peer["requirement_id"]]
            selected = draft["candidates"].get(draft["selected_candidate_id"])
            if selected is not None:
                peer["final_text"] = selected["text"]
        consistency = _consistency_with_candidate(rid, candidate["text"], peers,
            state["requirements"], context_from_state(state))
        unresolved = clarification_resolution(record, row["original_text"], [])["unresolved_questions"]
        tier = classify_tier(evaluation["quality_findings"], evaluation["grounding"], consistency,
            original_text=row["original_text"], candidate_text=candidate["text"],
            unresolved_clarification=bool(unresolved), human_reviewed=True)
        validation = _candidate_validation(evaluation, consistency, text=candidate["text"], tier=tier["tier"],
            clarification_questions=unresolved, escalation_active=record["escalation_active"])
        return {"candidate_id": cid, "candidate_text_sha256": _hash(candidate["text"].encode()),
                "original_sha256": _hash(row["original_text"].encode()),
                "registry_event_sha256": event["sha256"], "reference_sha256": event["reference_sha256"],
                "receipt_sha256": reference["receipt_sha256"], "binding": reference["binding"],
                "evaluation": evaluation, "consistency": consistency, "tier": tier, "validation": validation}

    def _replay_refinement_review(self, event):
        from c1_requirement_quality.workflow_persistence import _question, _answer, _event
        from c1_requirement_quality.bdd_readiness import is_single_requirement_no_peers
        _, _, manifest, parent = self.read()
        if not manifest.get("rag_policy"):
            raise ValueError("Initial-RAG review requires verified RAG provenance")
        if type(event.get("review_version")) is not int or event["review_version"] != 1:
            raise ValueError("Unsupported refinement review version")
        state = copy.deepcopy(self._review_state or parent)
        if event.get("basis") != self._review_basis(state):
            raise ValueError("Stale refinement review basis")
        actor = event.get("reviewer")
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("Explicit reviewer required")
        action = event["action"]
        allowed = {"requirement_id", "selected_candidate_text", "selected_candidate_id", "candidate_texts",
                   "clarification_questions", "clarification_answers", "question_actions", "workflow_action", "human_decision"}
        if not isinstance(action, dict) or set(action) - allowed:
            raise ValueError("Unsupported initial-RAG review action")
        rid = action.get("requirement_id")
        if rid not in state["requirements"]:
            raise ValueError("Unknown review requirement")
        record = state["requirements"][rid]
        decision = action.get("human_decision")
        work = action.get("workflow_action")
        if decision not in {None, "approved", "rejected"} or work not in {None, "request_clarification", "reopen"}:
            raise ValueError("Initial-RAG approval/publication integration is pending; unsupported action")
        if event["kind"] == "approval_intent":
            if set(action) != {"requirement_id", "human_decision", "selected_candidate_id"}:
                raise ValueError("Approval intent requires a separate exact selection decision")
            if decision != "approved" or action["selected_candidate_id"] != record["selected_candidate_id"]:
                raise ValueError("Approval intent selection mismatch")
            checked = self._review_evaluation(rid, state)
            if checked != event.get("eligibility"):
                raise ValueError("Approval intent eligibility mismatch")
            if (not checked["evaluation"]["candidate_eligible"]
                    or any(v != "pass" for k, v in checked["validation"]["checks"].items() if k != "consistency")
                    or (checked["consistency"]["check"] != "pass"
                        and not is_single_requirement_no_peers(checked["consistency"]))
                    or record["clarification_requested"] or record["escalation_active"]
                    or checked["tier"]["tier"] != "TIER_1_AUTO_REFINE"):
                raise ValueError("Candidate is not eligible for approval intent")
            if any(i["basis"] == event["basis"] and i["action"] == action for i in self._approval_intents):
                raise ValueError("Repeated approval intent")
            if event.get("publication_authorized") is not False or event.get("bdd_ready_authorized") is not False:
                raise ValueError("Approval intent cannot authorize publication or readiness")
            self._approval_intents.append(copy.deepcopy(event))
            return
        if decision == "approved":
            raise ValueError("Approval requires independently verified approval intent")
        texts = action.get("candidate_texts", [])
        if not isinstance(texts, list) or len(texts) > 3:
            raise ValueError("At most three supplied candidates per action")
        texts = list(texts)
        if "selected_candidate_text" in action:
            texts.append(action["selected_candidate_text"])
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Candidate text must be nonempty")
            cid = stable_candidate_id(rid, text)
            record["candidates"].setdefault(cid, {"text": text, "status": "PROPOSED"})
        selected = action.get("selected_candidate_id", record["selected_candidate_id"])
        if "selected_candidate_text" in action:
            derived = stable_candidate_id(rid, action["selected_candidate_text"])
            if "selected_candidate_id" in action and selected != derived:
                raise ValueError("Candidate ID and text disagree")
            selected = derived
        if selected is not None and selected not in record["candidates"]:
            raise ValueError("Unknown selected candidate")
        if (selected is not None and record["candidates"][selected]["status"] == "REJECTED"
                and ("selected_candidate_id" in action or "selected_candidate_text" in action)):
            raise ValueError("Rejected candidate cannot be selected")
        record["selected_candidate_id"] = selected
        questions = action.get("clarification_questions", [])
        answers = action.get("clarification_answers", [])
        operations = action.get("question_actions", [])
        if any(not isinstance(v, list) for v in (questions, answers, operations)):
            raise ValueError("Clarification collections must be lists")
        # Stable IDs and timestamps derive from the independently retained event,
        # so replay produces exactly the same clarification basis.
        for question in questions:
            _question(state, rid, question, "human_question", actor)
        for answer in answers:
            if not isinstance(answer, dict) or set(answer) - {"question_id", "question", "answer", "replaces_span"}:
                raise ValueError("Invalid human clarification fields")
            _answer(state, rid, answer, actor, origin="initial_rag_review_journal")
        if work == "reopen" and not operations:
            operations = [{"question_id": qid, "status": "REOPENED"} for qid in record["questions"]]
        for operation in operations:
            if (not isinstance(operation, dict) or set(operation) != {"question_id", "status"}
                    or operation["status"] != "REOPENED" or operation["question_id"] not in record["questions"]):
                raise ValueError("Only explicit question reopening is supported")
            question = record["questions"][operation["question_id"]]
            question.update(status="REOPENED", current_answer_id=None)
        if work in {"reopen", "request_clarification"}:
            record["clarification_requested"] = True
        elif answers:
            original = next(r["original_text"] for r in self.read()[0]["requirements"] if r["requirement_id"] == rid)
            record["clarification_requested"] = bool(clarification_resolution(record, original, [])["unresolved_questions"])
        if decision == "rejected":
            if selected is None:
                raise ValueError("Select a candidate to reject")
            record["candidates"][selected]["status"] = "REJECTED"
        _event(state, rid, "refinement_review", actor, action)
        # Replace generated audit IDs with journal-derived identities before hashing.
        replacements = {}
        new_events = state["events"][len((self._review_state or parent)["events"]):]
        for index, item in enumerate(new_events):
            replacements[item["event_id"]] = f"REVIEW-{event['sequence']}-{index}"
            item["recorded_at"] = event["recorded_at"]
        for index, answer in enumerate(record["answers"]):
            if answer["event_id"] in replacements:
                replacements[answer["answer_id"]] = f"REVIEW-ANSWER-{event['sequence']}-{index}"
        def stable(value):
            if isinstance(value, dict):
                return {k: stable(v) for k, v in value.items()}
            if isinstance(value, list):
                return [stable(v) for v in value]
            return replacements.get(value, value) if isinstance(value, str) else value
        state = stable(state)
        self._review_state = state

    def review_action(self, action, reviewer, confirmed):
        """Record a draft or approval intent; never call refinement publication."""
        from datetime import datetime, timezone
        if confirmed is not True or not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("Explicit reviewer and confirmation required")
        if not isinstance(action, dict):
            raise ValueError("Review action must be an object")
        if self._registry_anchor is not None:
            raise ValueError("Registry journal prefix is read-only")
        current = DemoSession(self.workspace, analyser_factory=self._analyser_factory)
        if current.pending is not None:
            raise ValueError("Resolve pending publication first")
        state = current._review_state or current.read()[3]
        kind = "approval_intent" if action.get("human_decision") == "approved" else "refinement_review"
        action = copy.deepcopy(action)
        if action.get("requirement_id") not in state["requirements"]:
            raise ValueError("Unknown review requirement")
        if kind == "approval_intent":
            rid = action["requirement_id"]
            action.setdefault("selected_candidate_id", state["requirements"][rid]["selected_candidate_id"])
        values = {"review_version": 1, "action": action, "reviewer": reviewer.strip(), "basis": current._review_basis(state),
                  "recorded_at": datetime.now(timezone.utc).isoformat()}
        if kind == "approval_intent":
            values.update(eligibility=current._review_evaluation(action["requirement_id"], state),
                          publication_authorized=False, bdd_ready_authorized=False)
        event = {"kind": kind, "sequence": len(current.events) + 1, **values}
        current._replay_refinement_review(event)
        if current._review_basis(state) != values["basis"]:
            raise ValueError("Review provenance changed before journal publication")
        current._append(kind, **values)
        self.__init__(self.workspace, analyser_factory=self._analyser_factory)

    def approval_intents(self):
        """Reverify durable provenance and expose stale intents as historical only."""
        current = DemoSession(self.workspace, analyser_factory=self._analyser_factory)
        basis = current._review_basis(current._review_state or current.read()[3])
        return [{**copy.deepcopy(event), "active": event["basis"] == basis}
                for event in current._approval_intents]

    def generate_review_candidates(self, requirement_ids=None, *, backend=None):
        """Use existing offline generator and ranking after trusted receipt registration."""
        from c1_requirement_quality.rewrite_generator import generate_candidate_suggestions, DeterministicSubstitutionBackend
        from c1_requirement_quality.source_integrity import VerifiedWorkflowContext
        data, text, manifest, state = self.read()
        if not manifest.get("rag_policy"):
            raise ValueError("Initial-RAG review generation requires verified provenance")
        context = self.candidate_grounding_context()
        session = self
        generator = backend or DeterministicSubstitutionBackend(structural_only_alternative=True)
        class RegisteredBackend:
            def __init__(self):
                self.index = 0
            def generate(self, *args, **kwargs):
                proposals = generator.generate(*args, **kwargs)[:3]
                rid = generation_ids[self.index]
                self.index += 1
                for proposal in proposals:
                    cid = stable_candidate_id(rid, proposal["text"])
                    if cid not in context.receipts:
                        session.validate_candidate_evidence(rid, proposal["text"])
                        context.receipts.update(session.candidate_grounding_context().receipts)
                return proposals
        draft = self.review_read()[3]
        from c1_requirement_quality.workflow_persistence import current_answer_actions
        from c1_requirement_quality.effective_consistency import context_from_state
        from c1_requirement_quality.rewrite_generator import check_eligibility
        answers = current_answer_actions(draft)
        blocked = {rid for rid, record in draft["requirements"].items()
                   if record["escalation_active"] or record["clarification_requested"]}
        for row in data["requirements"]:
            record = draft["requirements"][row["requirement_id"]]
            if clarification_resolution(record, row["original_text"], [])["unresolved_questions"]:
                blocked.add(row["requirement_id"])
        # Match the existing generator's actual backend call order, including
        # skipped requirements and duplicate original text under distinct IDs.
        generation_ids = [row["requirement_id"] for row in data["requirements"]
                          if (requirement_ids is None or row["requirement_id"] in requirement_ids)
                          and row["requirement_id"] not in blocked
                          and check_eligibility(row, next(a["clarification_answers"] for a in answers
                                                        if a["requirement_id"] == row["requirement_id"]))[0]]
        result = generate_candidate_suggestions(data, text, backend=RegisteredBackend(),
            clarification_answers=answers, workflow_records=state["requirements"],
            consistency_context=context_from_state(state), requirement_ids=requirement_ids,
            workflow_blocked_ids=blocked,
            workflow_rejected_ids={cid for record in draft["requirements"].values()
                                   for cid, c in record["candidates"].items() if c["status"] == "REJECTED"},
            grounding_context=context, workflow_context=VerifiedWorkflowContext(self.current, self.source))
        for item in result["requirements"]:
            texts = [c["text"] for c in item["ranked_candidates"][:3]]
            if texts:
                self.review_action({"requirement_id": item["requirement_id"], "candidate_texts": texts},
                                   "system:deterministic-generator", True)
        return result

    def initial_ml_predictions(self):
        """Validate saved initial-text scores; never replay inference on resume."""
        base = Path(self.meta["base_artifact"])
        if not (self.workspace / "ml_analysis.json").is_file():
            failure_path = self.workspace / "ml_failure.json"
            detail = (json.loads(failure_path.read_text(encoding="utf-8")).get("error")
                      if failure_path.is_file() else "No completion receipt was published")
            raise ValueError(f"Mandatory ML classification incomplete: {detail}")
        receipt = json.loads((self.workspace / "ml_analysis.json").read_text(encoding="utf-8"))
        raw = base.read_bytes()
        if receipt.get("status") != "completed" or receipt.get("input_sha256") != _hash(raw):
            raise ValueError("Mandatory ML classification incomplete or input binding changed")
        data, digest = _load_diagnostics(self.workspace / "sidecars/initial-defect-predictions.json",
            json.loads(raw.decode("utf-8")), _hash(raw), "distilbert")
        if receipt.get("sidecar_sha256") != digest or data.get("threshold") is not None:
            raise ValueError("Mandatory ML predictions changed or have an unexpected threshold")
        return data

    def _append(self, kind: str, **values: Any) -> None:
        if self._registry_anchor is not None:
            raise ValueError("Registry journal prefix is read-only")
        event = {"sequence": len(self.events) + 1, "previous": self.events[-1]["sha256"] if self.events else None,
                 "kind": kind, **values}
        event["sha256"] = _hash(json.dumps(event, sort_keys=True).encode())
        _write(self.workspace / "events" / f"{event['sequence']:06}.json", event)
        self.events.append(event)

    def read(self):
        from c1_requirement_quality.contract import validate_contract_artifact as _validate_contract_artifact
        if _hash(self.source.read_bytes()) != self.meta["source_sha256"]:
            raise ValueError("Session SRS changed")
        from c1_requirement_quality.rag.publication import publication_models
        with publication_models(self._analyser_factory):
            text, manifest, data, state = _verify_snapshot(self.current, self.source)
        _validate_contract_artifact(data)
        if self.meta.get("mandatory_rag") and manifest.get("rag_policy") != "c1-initial-rag-v1":
            raise ValueError("Mandatory RAG grounding receipt missing")
        if self.meta.get("expected_run_id") and data["run_id"] != self.meta["expected_run_id"]:
            raise ValueError("Initial run identity mismatch")
        if self.meta.get("mandatory_ml"):
            try:
                self.initial_ml_predictions()
            except (OSError, ValueError, KeyError) as error:
                raise ValueError(f"Mandatory ML classification incomplete or invalid; no inference replayed: {error}") from error
        return data, text, manifest, state

    def _check_child(self, operation):
        from c1_requirement_quality.rag.publication import publication_models
        with publication_models(self._analyser_factory):
            return self._check_child_verified(operation)

    def _check_child_verified(self, operation):
        matches = [event for event in _verified_journal(self.workspace, self._registry_anchor)
                   if event["kind"] == "pending" and event.get("operation_id") == operation.get("operation_id")]
        if len(matches) != 1 or matches[0] != operation:
            raise ValueError("Recovery operation disagrees with the durable journal")
        operation = matches[0]
        actions = Path(operation["actions"])
        parent = Path(operation["parent"])
        child = Path(operation["out"]) / "c1/validated_requirements.json"
        actions_raw = actions.read_bytes()
        parent_raw = parent.read_bytes()
        if _hash(actions_raw) != operation["actions_sha256"] or _hash(parent_raw) != operation["parent_sha256"]:
            raise ValueError("Pending action or parent changed; recovery refused")
        from c1_requirement_quality.source_integrity import VerifiedWorkflowContext, resolve_workflow_policy, require_refinement_grounding
        from c1_requirement_quality.workflow_persistence import _candidate_snapshot_identity, refinement_operation_binding
        from c1_requirement_quality.rag.candidate_validation import _canonical
        _, _, parent_manifest, parent_state = resolve_workflow_policy(VerifiedWorkflowContext(parent, self.source))
        if _hash(parent_raw) != parent_manifest["artifact_sha256"]:
            raise ValueError("Recovery parent artifact digest mismatch")
        from c1_requirement_quality.contract import validate_contract_artifact as _validate_contract_artifact
        child_raw = child.read_bytes()
        _, _, manifest, state = resolve_workflow_policy(VerifiedWorkflowContext(child, self.source))
        if _hash(child_raw) != manifest["artifact_sha256"]:
            raise ValueError("Recovery child artifact digest mismatch")
        artifact = json.loads(child_raw)
        _validate_contract_artifact(artifact)
        if not state.get("parent") or (child.parent / state["parent"]["artifact_path"]).resolve() != parent.resolve():
            raise ValueError("Recovery child has unexpected ancestry")
        if operation.get("operation_version") == 2:
            if operation["registry_anchor"] != {"sequence": operation["sequence"] - 1,
                                                "sha256": operation["previous"]}:
                raise ValueError("Recovery registry cutoff must precede its pending operation")
            if self.prepared is None:
                raise ValueError("Operation-bound recovery requires a prepared child receipt")
            # Reopen only through the independently retained prepared event. It
            # precedes this child's completed event, so replay strictly descends.
            prefix = DemoSession(self.workspace, _registry_anchor={
                "sequence": self.prepared["sequence"], "sha256": self.prepared["sha256"]},
                analyser_factory=self._analyser_factory)
            if prefix.pending != operation or prefix.prepared != self.prepared:
                raise ValueError("Recovery operation is not independently journal-bound")
            if operation.get("approval_intent_sha256s"):
                from c1_requirement_quality.rag.publication import authorize_operation
                authorize_operation(operation, self.source, analyser_factory=self._analyser_factory)
            else:
                require_refinement_grounding(parent_manifest)
            commitment = prefix.prepared["commitment"]
            expected = {"version": 1, "snapshot_id": state["snapshot_id"],
                "artifact_sha256": _hash(child_raw), "workflow_sha256": manifest["workflow_sha256"],
                "manifest_sha256": _hash(_canonical(manifest)),
                "diagnostics_sha256": _hash((child.parent / "refinement_diagnostics.json").read_bytes())}
            if (commitment != expected or state["snapshot_id"] != operation["child_snapshot_id"]
                    or _candidate_snapshot_identity(parent_manifest, parent_state) != operation["parent_identity"]
                    or _hash(_canonical(json.loads(actions_raw))) != operation["actions_parsed_sha256"]
                    or state.get("operation_binding") != refinement_operation_binding(operation)
                    or _hash(_canonical(state.get("parent_evidence_links"))) != operation["evidence_links_sha256"]):
                raise ValueError("Operation-bound child commitment mismatch")
            if operation["evidence_candidate_ids"]:
                from c1_requirement_quality.workflow_persistence import verify_child_evidence_links
                verify_child_evidence_links(child, self.source, registry_workspace=self.workspace,
                    registry_anchor=operation["registry_anchor"], analyser_factory=self._analyser_factory)
            elif "parent_evidence_links" in state or (child.parent / "candidate_evidence").exists():
                raise ValueError("Unexpected child evidence selection")
        elif "operation_binding" in state:
            raise ValueError("Operation-bound child cannot use legacy recovery")
        return state

    def recover(self, adopt: bool) -> None:
        if self._registry_anchor is not None:
            raise ValueError("Registry journal prefix is read-only")
        requested = self.pending
        fresh = DemoSession(self.workspace, analyser_factory=self._analyser_factory)
        if requested is None:
            self.__dict__.update(fresh.__dict__)
            return
        matches = [event for event in fresh.events if event["kind"] == "pending"
                   and event.get("operation_id") == requested.get("operation_id")]
        if len(matches) != 1 or matches[0] != requested:
            raise ValueError("Recovery operation disagrees with the durable journal")
        terminal = [event for event in fresh.events if event["kind"] in {"completed", "cancelled"}
                    and event["operation_id"] == requested["operation_id"]]
        if terminal:
            self.__dict__.update(fresh.__dict__)
            if (terminal[-1]["kind"] == "completed") != adopt:
                raise ValueError("Operation already has a conflicting durable terminal outcome")
            return
        if fresh.pending != requested:
            raise ValueError("Recovery operation disagrees with the durable journal")
        if self.prepared is not None and self.prepared != fresh.prepared:
            raise ValueError("Recovery operation is not independently journal-bound")
        self.__dict__.update(fresh.__dict__)
        operation = fresh.pending
        if adopt:
            state = self._check_child(operation)
            child = Path(operation["out"]) / "c1/validated_requirements.json"
            from c1_requirement_quality.source_integrity import require_refinement_grounding
            if not operation.get("approval_intent_sha256s"):
                require_refinement_grounding(verify_source(Path(operation["parent"]), self.source)[1])
            if operation.get("operation_version") != 2 and (
                    "parent_evidence_links" in state or (child.parent / "candidate_evidence").exists()):
                raise ValueError("Evidence-linked recovery requires operation-bound staging; adoption blocked")
            values = ({"artifact_sha256": self.prepared["commitment"]["artifact_sha256"],
                       "prepared_sha256": self.prepared["sha256"]} if operation.get("operation_version") == 2
                      else {"artifact_sha256": _hash(child.read_bytes())})
            self._append("completed", operation_id=operation["operation_id"], **values)
            self.current = child
            self._review_state = None
        else:
            self._append("cancelled", operation_id=operation["operation_id"], note="Human declined replay/adoption; files retained")
        self.pending = None
        self.prepared = None

    def apply(self, action: dict[str, Any] | list[dict[str, Any]], reviewer: str, confirmed: bool,
              *, consistency_reviews: list[dict[str, Any]] | None = None,
              evidence_candidate_ids: list[str] | None = None, analyser_factory=None,
              _approval_intent_sha256s=None) -> None:
        from c1_requirement_quality.cli import refine_run
        if not confirmed or not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("Explicit confirmation and reviewer identity are required")
        if self.pending is not None:
            raise ValueError("Resolve pending operation before another action")
        _, _, manifest, state = self.read()
        from c1_requirement_quality.source_integrity import require_refinement_grounding
        if not _approval_intent_sha256s:
            require_refinement_grounding(manifest)
        else:
            from c1_requirement_quality.rag.publication import active_intents
            fresh = DemoSession(self.workspace, analyser_factory=analyser_factory or self._analyser_factory)
            available = {e["sha256"]: e for e in active_intents(fresh)}
            if (manifest.get("rag_policy") != "c1-initial-rag-v1" or consistency_reviews is not None
                    or len(set(_approval_intent_sha256s)) != len(_approval_intent_sha256s)
                    or not set(_approval_intent_sha256s) <= available.keys()):
                raise ValueError("Missing or stale publication approval intents")
            intended = [available[key] for key in _approval_intent_sha256s]
            supplied = action if isinstance(action, list) else [action]
            if (supplied != [e["action"] for e in intended]
                    or evidence_candidate_ids != [e["eligibility"]["candidate_id"] for e in intended]):
                raise ValueError("Publication action differs from approved intent")
        if self._registry_anchor is not None:
            raise ValueError("Registry journal prefix is read-only")
        if analyser_factory is not None:
            self._analyser_factory = analyser_factory
        from c1_requirement_quality.rag.candidate_validation import _canonical
        from c1_requirement_quality.source_integrity import VerifiedWorkflowContext
        from c1_requirement_quality.workflow_persistence import build_parent_evidence_links, _candidate_snapshot_identity
        anchor = {"sequence": len(self.events), "sha256": self.events[-1]["sha256"] if self.events else None}
        ids = copy.deepcopy(evidence_candidate_ids) if evidence_candidate_ids is not None else []
        links = (build_parent_evidence_links(VerifiedWorkflowContext(self.current, self.source), self.workspace,
            ids, analyser_factory=self._analyser_factory, registry_anchor=anchor) if ids else None)
        token = uuid.uuid4().hex
        actions = self.workspace / "actions" / f"{token}.json"
        actions_list = action if isinstance(action, list) else [action]
        payload = {"requirements": [{**copy.deepcopy(item), "actor_id":
            intended[index]["reviewer"] if _approval_intent_sha256s else reviewer.strip()}
            for index, item in enumerate(actions_list)]}
        if consistency_reviews is not None:
            payload["consistency_reviews"] = copy.deepcopy(consistency_reviews)
        actions_raw = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
        _write(actions, actions_raw)
        out = self.workspace / "snapshots" / token
        self._append("pending", operation_version=2, operation_id=token, workspace=str(self.workspace),
            parent=str(self.current), parent_sha256=manifest["artifact_sha256"],
            parent_identity=_candidate_snapshot_identity(manifest, state), actions=str(actions),
            actions_sha256=_hash(actions_raw), actions_parsed_sha256=_hash(_canonical(payload)), out=str(out),
            registry_anchor=anchor, evidence_candidate_ids=ids, evidence_links_sha256=_hash(_canonical(links)),
            child_snapshot_id="SNAPSHOT-" + token,
            **({"approval_intent_sha256s": copy.deepcopy(_approval_intent_sha256s)} if _approval_intent_sha256s else {}))
        self.pending = self.events[-1]
        self.prepared = None
        def prepared(commitment):
            self._append("prepared", operation_id=token, pending_sha256=self.pending["sha256"],
                         commitment=commitment)
            self.prepared = self.events[-1]
            return self.prepared
        from c1_requirement_quality.rag.publication import publication_models
        with publication_models(self._analyser_factory):
            refine_run(self.current, self.source, actions, out,
                evidence_registry=self.workspace if ids else None, evidence_candidate_ids=ids if ids else None,
                analyser_factory=self._analyser_factory, _operation=self.pending, _prepared=prepared)
        self.recover(True)

    def publish_approved(self, reviewer: str, confirmed: bool, *, requirement_ids=None):
        """Publish only active, journal-verified M1 approvals; no inference."""
        from c1_requirement_quality.rag.publication import active_intents
        if confirmed is not True:
            raise ValueError("Explicit publication confirmation required")
        fresh = DemoSession(self.workspace, analyser_factory=self._analyser_factory)
        intents = active_intents(fresh)
        if requirement_ids is not None:
            if (not isinstance(requirement_ids, list) or not requirement_ids
                    or len(set(requirement_ids)) != len(requirement_ids)):
                raise ValueError("Unique publication requirement IDs required")
            intents = [e for e in intents if e["action"]["requirement_id"] in requirement_ids]
            if {e["action"]["requirement_id"] for e in intents} != set(requirement_ids):
                raise ValueError("Selected requirement has no current approved intent")
        if not intents:
            raise ValueError("No current approved intents to publish")
        self.__dict__.update(fresh.__dict__)
        self.apply([e["action"] for e in intents], reviewer, confirmed,
            evidence_candidate_ids=[e["eligibility"]["candidate_id"] for e in intents],
            _approval_intent_sha256s=[e["sha256"] for e in intents])

    def review_receipt(self, sidecar: Path, accepted: bool, item: str) -> None:
        self._append("review", artifact_sha256=_hash(self.current.read_bytes()), sidecar=str(sidecar.resolve()),
                     sidecar_sha256=_hash(sidecar.read_bytes()), accepted=accepted, item=item)

    def validate_candidate_evidence(self, requirement_id: str, candidate_text: str, *, analyser_factory=None):
        """Trusted registration: only this fresh producer's receipt may be retained.

        No caller-supplied evidence path or digest is accepted. Exclusive slot and
        journal publication fail closed on contention; unjournalled files are not
        restored and are retained for inspection after an interrupted operation.
        """
        from c1_requirement_quality.rag.candidate_validation import (
            validate_candidate_run, load_candidate_validation, _canonical,
        )
        from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser
        from c1_requirement_quality.workflow_persistence import candidate_evidence_path, _candidate_snapshot_identity
        from c1_requirement_quality.source_integrity import VerifiedWorkflowContext, resolve_workflow_policy
        if self._registry_anchor is not None:
            raise ValueError("Registry journal prefix is read-only")
        factory = analyser_factory or self._analyser_factory or RAGGroundingAnalyser
        # Refresh journal ordering before reserving a slot; concurrent append still
        # uses exclusive publication and cannot overwrite another registration.
        current = DemoSession(self.workspace, analyser_factory=factory)
        if current.pending is not None:
            raise ValueError("Resolve pending operation before registering evidence")
        policy = VerifiedWorkflowContext(current.current, current.source)
        _, _, manifest, state = resolve_workflow_policy(policy)
        identity = _candidate_snapshot_identity(manifest, state)
        cid = stable_candidate_id(requirement_id, candidate_text)
        # One full digest keeps Windows paths compact without truncating identity.
        slot_id = _hash(_canonical({"snapshot_identity": identity, "candidate_id": cid}))
        relative = f"candidate_evidence/{slot_id}"
        slot = candidate_evidence_path(self.workspace, relative)
        slot.mkdir(parents=True, exist_ok=False)
        evidence = candidate_evidence_path(self.workspace, relative + "/evidence.json")
        digest = validate_candidate_run(current.current, current.source, requirement_id,
            candidate_text, evidence, analyser_factory=factory)
        record = load_candidate_validation(evidence, current.current, current.source,
            requirement_id, candidate_text, expected_sha256=digest, analyser_factory=factory)
        binding = record["binding"]
        if any(binding.get(key) != value for key, value in identity.items()):
            raise ValueError("Candidate registry snapshot changed during registration")
        reference = {"registry_version": 1, "requirement_id": requirement_id,
            "candidate_id": cid, "candidate_text": candidate_text,
            "parent_artifact_sha256": binding["parent_artifact_sha256"],
            "snapshot_id": binding["snapshot_id"], "binding": binding,
            "models": record["models"], "top_k": 5,
            "evidence": relative + "/evidence.json", "receipt_sha256": digest}
        target = candidate_evidence_path(self.workspace, relative + "/reference.json")
        # Anchor only the bytes derived from the independently verified record.
        # A subsequent filesystem edit can never redefine the retained receipt.
        trusted_bytes = _canonical(reference) + b"\n"
        trusted_digest = _hash(trusted_bytes)
        _write(target, trusted_bytes)
        current._append("candidate_evidence_registered", artifact_sha256=manifest["artifact_sha256"],
            snapshot_identity=identity, reference=relative + "/reference.json", reference_sha256=trusted_digest)
        self.__init__(self.workspace, analyser_factory=factory)
        return digest

    def candidate_grounding_context(self, *, analyser_factory=None):
        """Restore verified candidate receipts without running model inference."""
        from c1_requirement_quality.source_integrity import VerifiedWorkflowContext
        from c1_requirement_quality.workflow_persistence import restore_candidate_receipts
        return restore_candidate_receipts(self.workspace,
            VerifiedWorkflowContext(self.current, self.source), analyser_factory=analyser_factory or self._analyser_factory)

    def consistency_pairs(self, *, gate_policy: bool = False):
        from c1_requirement_quality.consistency_review import pair_views
        data, _, manifest, state = self.read()
        history = []
        # Reconstruct sticky invalidation from immutable, verified snapshots.
        # Reverting wording cannot silently resurrect an older human review.
        for event in self.events:
            if event["kind"] == "consistency_review":
                history.append(copy.deepcopy(event["record"]))
            elif event["kind"] == "completed" and history:
                operation = next(e for e in self.events if e["kind"] == "pending"
                                 and e["operation_id"] == event["operation_id"])
                artifact = Path(operation["out"]) / "c1/validated_requirements.json"
                _, snapshot_manifest, snapshot, snapshot_state = _verify_snapshot(artifact, self.source)
                views = {v["pair_id"]: v for v in pair_views(snapshot, snapshot_manifest, snapshot_state, [])}
                for record in history:
                    view = views.get(record["pair_id"])
                    if view is None or view["binding"] != record["binding"]:
                        record.setdefault("invalidations", []).append({"snapshot_sha256": event["artifact_sha256"],
                            "reason": "Requirement, evidence, source or clarification binding changed"})
        legacy = pair_views(data, manifest, state, history)
        from c1_requirement_quality.effective_consistency import context_from_state, views
        context = context_from_state(state)
        if gate_policy or context["history"]:
            current = views(data["requirements"], state["requirements"], context)
            for pair, old in zip(current, legacy, strict=True):
                pair["legacy_audit_history"] = old["history"]
            return current
        return legacy

    def adopt_consistency(self, requirement_ids: list[str], **review: Any) -> None:
        reviewer = review.get("reviewer")
        self.apply([], reviewer, review.get("confirmed") is True,
                   consistency_reviews=[{"requirement_ids": requirement_ids, **review}])

    def record_consistency(self, requirement_ids: list[str], **review: Any) -> None:
        from c1_requirement_quality.consistency_review import make_review
        if self.pending is not None:
            raise ValueError("Resolve pending operation before recording a review")
        if (len(requirement_ids) != 2 or len(set(requirement_ids)) != 2):
            raise ValueError("Two distinct requirement IDs are required")
        views = [v for v in self.consistency_pairs() if v["requirement_ids"] == sorted(requirement_ids)]
        if len(views) != 1:
            raise ValueError("Unknown requirement pair")
        record = make_review(views[0], **review)
        self._append("consistency_review", artifact_sha256=_hash(self.current.read_bytes()), record=record)

    def diagnostics(self, path: Path):
        data, _, _, _ = self.read()
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        model = raw.get("model", {}).get("identifier")
        kind = "distilbert" if model == "distilbert-requirement-defects" else "minilm" if model == "sentence-transformers/all-MiniLM-L6-v2" else None
        if kind is None:
            raise ValueError("Unknown diagnostic model")
        result, _ = _load_diagnostics(path, data, _hash(self.current.read_bytes()), kind)
        return result

    def proposals(self, path: Path, *, grounding_context=None):
        data, text, manifest, state = self.read()
        from c1_requirement_quality.source_integrity import VerifiedWorkflowContext
        policy_context = VerifiedWorkflowContext(self.current, self.source)
        if manifest.get("rag_policy") or grounding_context is not None:
            from c1_requirement_quality.rag.candidate_validation import context_for_snapshot
            grounding_context = context_for_snapshot(self.current, self.source,
                grounding_context if grounding_context is not None else self.candidate_grounding_context())
        report = json.loads(path.read_text(encoding="utf-8-sig"))
        if (report.get("input_sha256") != _hash(self.current.read_bytes()) or report.get("source_sha256") != manifest["sha256"]
                or report.get("document_id") != manifest["document_id"] or report.get("decision_effect") != "none"):
            raise ValueError("Stale or unbound proposal sidecar")
        rows = {r["requirement_id"]: r for r in data["requirements"]}
        result = []
        seen = set()
        for entry in report["proposals"]:
            p = entry["proposal"]
            rid = p["requirement_id"]
            if rid not in rows or rid in seen:
                raise ValueError("Unknown or duplicate proposal ID")
            seen.add(rid)
            context = _context(rows[rid], text, state, {}, 20000)
            # Advisory references are never evidence. Only known per-requirement
            # namespaces with recorded diagnostic hashes are allowed here.
            for kind, prefix in [("distilbert", "ML"), ("minilm", "SIM")]:
                digest = report.get("diagnostic_sha256", {}).get(kind)
                if isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
                    context["advisory_context"].append({"ref": f"{prefix}:{rid}"})
            value = {k: v for k, v in p.items() if k != "validation"}
            checked = validate_proposal(value, context, text, list(rows.values()), state["requirements"][rid],
                                        "docx" if self.source.suffix.lower() == ".docx" else None,
                                        grounding_context=grounding_context, workflow_context=policy_context)
            result.append(checked)
        return result

    def candidates(self, path: Path, *, grounding_context=None):
        data, text, manifest, state = self.read()
        from c1_requirement_quality.source_integrity import VerifiedWorkflowContext
        policy_context = VerifiedWorkflowContext(self.current, self.source)
        if manifest.get("rag_policy") or grounding_context is not None:
            from c1_requirement_quality.rag.candidate_validation import context_for_snapshot
            grounding_context = context_for_snapshot(self.current, self.source,
                grounding_context if grounding_context is not None else self.candidate_grounding_context())
        report = json.loads(path.read_text(encoding="utf-8-sig"))
        if (report.get("input_sha256") != _hash(self.current.read_bytes())
                or report.get("source_sha256") != manifest["sha256"]
                or report.get("workflow_sha256") != manifest.get("workflow_sha256")
                or report.get("source_document") != data["source_document"]):
            raise ValueError("Stale/unbound candidate sidecar; generate a fresh bound sidecar")
        rows = {r["requirement_id"]: r for r in data["requirements"]}
        result = []
        seen = set()
        for row in report["requirements"]:
            rid = row["requirement_id"]
            if rid not in rows or rid in seen or row["original_text"] != rows[rid]["original_text"]:
                raise ValueError("Candidate ID/text mismatch")
            seen.add(rid)
            for candidate in row["ranked_candidates"] + row["diagnostic_suggestions"]:
                if candidate["candidate_id"] != stable_candidate_id(rid, candidate["text"]):
                    raise ValueError("Candidate identity mismatch")
                evidence = candidate.get("source_evidence", {})
                kind = evidence.get("kind")
                if kind == "srs_chunk":
                    if not evidence.get("text") or evidence["text"] not in text:
                        raise ValueError("Candidate source quotation is not in verified SRS")
                elif kind in {"clarification_answer", "clarification_answers"}:
                    active = clarification_resolution(state["requirements"][rid], rows[rid]["original_text"], [])["active_answers"]
                    allowed = {(a["question"]["text"], a["answer"]["answer"]) for a in active}
                    references = evidence.get("items", []) if kind == "clarification_answers" else [evidence]
                    if not references or any((e.get("question"), e.get("answer")) not in allowed for e in references):
                        raise ValueError("Candidate references inactive or unknown human evidence")
                elif kind != "untrusted_cloud_proposal":
                    raise ValueError("Unknown candidate evidence provenance")
                checked = copy.deepcopy(candidate)
                evaluation = _evaluate_candidate(candidate["text"], text, rows[rid]["original_text"], state["requirements"][rid],
                    source_format="docx" if self.source.suffix.lower() == ".docx" else None,
                    grounding_context=grounding_context, requirement_id=rid, workflow_context=policy_context)
                from c1_requirement_quality.effective_consistency import context_from_state
                consistency = _consistency_with_candidate(rid, candidate["text"], list(rows.values()), state["requirements"], context_from_state(state))
                tier = classify_tier(evaluation["quality_findings"], evaluation["grounding"], consistency,
                                     original_text=rows[rid]["original_text"], candidate_text=candidate["text"])
                unresolved = clarification_resolution(state["requirements"][rid], rows[rid]["original_text"], [])["unresolved_questions"]
                checked["review_validation"] = {"evaluation": evaluation, "consistency": consistency, "tier": tier,
                    "validation": _candidate_validation(evaluation, consistency, text=candidate["text"], tier=tier["tier"],
                        clarification_questions=unresolved, escalation_active=state["requirements"][rid]["escalation_active"])}
                result.append((rid, checked))
        return result


def guided_demo(workspace: Path, *, resume: bool = False, artifact: Path | None = None,
                source: Path | None = None, run_id: str | None = None, registry: Path | None = None,
                project_code: str = "EX", document_id: str | None = None,
                ask: Callable[[str], str] | None = None, tell: Callable[[str], None] = print) -> None:
    from c1_requirement_quality.rewrite_generator import generate_candidates_run
    ask = input if ask is None else ask
    session = DemoSession(workspace) if resume else DemoSession.create(workspace, artifact=artifact, source=source,
                  run_id=run_id, registry=registry, project_code=project_code, document_id=document_id)
    with _session_lock(workspace):
        tell("Saved-sidecar mode: no cloud requests or local model inference. Type pause to stop.")
        while True:
            try:
                if session.pending:
                    tell("Pending operation retained. Published outputs may be adopted; nothing is replayed.")
                    choice = ask("recover published output / cancel operation / pause [recover/cancel/pause]: ").strip()
                    if choice == "pause": break
                    if choice not in {"recover", "cancel"}: continue
                    session.recover(choice == "recover")
                data, _, _, state = session.read()
                tell(f"Authoritative snapshot: {session.current}")
                command = ask("issues / pairs / review-pair / resolve-pair / diagnostics / proposals / candidates / answer / select / edit / decision / generate / pause: ").strip().lower()
                if command == "pause": break
                if command in {"pairs", "review-pair", "resolve-pair"}:
                    pairs = session.consistency_pairs(gate_policy=command == "resolve-pair")
                    if command == "pairs":
                        from c1_requirement_quality.effective_consistency import assess, context_from_state
                        context = context_from_state(state)
                        summaries = [assess(r["requirement_id"], data["requirements"], state["requirements"], context)
                                     for r in data["requirements"]]
                        blocked = {tuple(p["requirement_ids"]) for summary in summaries
                            for p in summary.get("effective_review", {}).get("pairs", []) if p["resolution"] in {"unresolved", "conflict"}}
                        if not context["history"]:
                            blocked = {tuple(p["requirement_ids"]) for p in pairs if p["current_deterministic"]["classification"] != "consistent"}
                        tell(f"{len(blocked)} requirement comparisons remain blocking. Similarity never resolves them.")
                        for pair in pairs:
                            tell(" / ".join(pair["requirement_ids"]) + " | deterministic: "
                                 + pair["current_deterministic"]["classification"] + " | human: "
                                 + pair["decision"] + " | " + (pair["invalidation"] or "audit only"))
                        continue
                    ids = [ask("Requirement ID A: ").strip(), ask("Requirement ID B: ").strip()]
                    matching = [p for p in pairs if p["requirement_ids"] == sorted(ids)]
                    if len(matching) != 1: raise ValueError("Unknown requirement pair")
                    pair = matching[0]
                    for row in pair["requirements"]:
                        tell(f"{row['requirement_id']}: {row['original_text']}")
                        if row["final_text"] != row["original_text"]: tell("Current: " + row["final_text"])
                    for key in ("original_deterministic", "current_deterministic"):
                        finding = pair[key]
                        tell(f"{key.replace('_', ' ')}: {finding['classification']} — {finding['explanation']}")
                    for ref, evidence in pair["evidence"].items():
                        tell(ref + ": " + (evidence.get("text") or "Recorded human clarification; not original source evidence"))
                    for old in pair.get("legacy_audit_history", []) + pair["history"]:
                        tell(f"History: {old['decision']} | {old.get('coverage', 'audit only')} | {old['reviewer']} | {old['rationale']}")
                    if pair["invalidation"]: tell("Previous review is stale and requires reaffirmation.")
                    path = ask("Optional matching saved MiniLM JSON path, or Enter: ").strip()
                    if path:
                        diagnostic = session.diagnostics(Path(path))
                        if "pairs" not in diagnostic: raise ValueError("MiniLM similarity diagnostics required")
                        for item in diagnostic["pairs"]:
                            if sorted(item["requirement_ids"]) == sorted(ids):
                                tell("Advisory similarity only: " + json.dumps(item))
                    decision = ask("Decision [not_applicable/consistent_within_scope/conflict_confirmed/unresolved], or Enter to cancel: ").strip()
                    if not decision: continue
                    refs = [s.strip() for s in ask("Evidence references (comma separated; include both SRS references): ").split(",")]
                    scope = ask("Reviewed scope: ")
                    conditions = ask("Reviewed conditions (explicitly describe any absence): ")
                    rationale = ask("Rationale: ")
                    reviewer = ask("Reviewer ID: ")
                    if command == "resolve-pair":
                        coverage = ask("Coverage [complete/partial] — complete confirms the entire pair obligation was reviewed: ").strip()
                        if ask("Adopt under the reviewed consistency policy in a new verified snapshot? Type yes: ") == "yes":
                            session.adopt_consistency(ids, decision=decision, evidence_refs=refs, scope=scope,
                                conditions=conditions, rationale=rationale, reviewer=reviewer, confirmed=True, coverage=coverage)
                            from c1_requirement_quality.effective_consistency import assess, context_from_state
                            latest, _, _, latest_state = session.read()
                            for rid in ids:
                                summary = assess(rid, latest["requirements"], latest_state["requirements"], context_from_state(latest_state))
                                if rid == ids[0]:
                                    reviewed_pair = next((p for p in summary.get("effective_review", {}).get("pairs", [])
                                                          if sorted(p["requirement_ids"]) == sorted(ids)), None)
                                    if reviewed_pair:
                                        tell("This pair: " + ("blocker remains — " if reviewed_pair["resolution"] in {"unresolved", "conflict"}
                                                               else "consistency blocker cleared — ") + reviewed_pair["resolution"])
                                tell(rid + ": " + summary.get("effective_review", {}).get("explanation", "Deterministic assessment"))
                                row = next(r for r in latest["requirements"] if r["requirement_id"] == rid)
                                tell(f"Tier: {row['tier']} | Human decision: {row['human_decision']} | BDD ready: {row['bdd_ready']}")
                                tell("Remaining validation gates: " + ", ".join(k for k, v in row["validation"].get("checks", {}).items() if v != "pass"))
                        continue
                    if ask("Record audit-only review? Type yes: ") == "yes":
                        session.record_consistency(ids, decision=decision, evidence_refs=refs, scope=scope,
                            conditions=conditions, rationale=rationale, reviewer=reviewer, confirmed=True)
                        tell("Review recorded. Readiness, deterministic findings and approvals are unchanged.")
                    continue
                if command == "issues":
                    for row in data["requirements"]:
                        rid = row["requirement_id"]
                        unresolved = clarification_resolution(state["requirements"][rid], row["original_text"], [])["unresolved_questions"]
                        tell(f"\n{rid}: {row['original_text']}")
                        tell(f"Final: {row['final_text']}")
                        tell(f"Tier: {row['tier']} | Grounding: {row['grounding']['status']} | Human: {row['human_decision']} | BDD ready: {row['bdd_ready']}")
                        tell("Quality findings: " + json.dumps(row["defects"], ensure_ascii=False))
                        tell("Consistency: " + json.dumps(row["consistency"], ensure_ascii=False))
                        tell("Validation/blockers: " + json.dumps(row["validation"], ensure_ascii=False))
                        tell("Source/evidence: " + json.dumps({"source": row["source"], "evidence": row["grounding"].get("evidence", [])}, ensure_ascii=False))
                        tell("Unresolved questions: " + json.dumps(unresolved, ensure_ascii=False))
                        tell("Registered candidates: " + json.dumps(row.get("candidates", []), ensure_ascii=False))
                    tell("potential_conflict may represent unassessed comparisons; unknown is not consistent.")
                    continue
                if command == "diagnostics":
                    path = Path(ask("Saved diagnostic JSON path: "))
                    diagnostic = session.diagnostics(path)
                    tell(f"Experimental advisory model: {diagnostic['model']['identifier']} | threshold: {diagnostic.get('threshold')}")
                    if "pairs" in diagnostic:
                        tell(f"{len(diagnostic['pairs'])} pairs; showing the 15 highest scores (not consistency/applicability decisions)")
                        for pair in sorted(diagnostic["pairs"], key=lambda p: -p["similarity"])[:15]:
                            tell(json.dumps(pair, ensure_ascii=False))
                    else:
                        for row in diagnostic["requirements"]:
                            tell(json.dumps({"id": row["requirement_id"], "selected_labels": row.get("predicted_defects", []),
                                "scores": row["scores"], "truncated": row.get("truncated")}, ensure_ascii=False))
                    tell("Scores are not calibrated confidence. No decisions changed.")
                    continue
                if command in {"proposals", "candidates"}:
                    path = Path(ask("Saved sidecar JSON path: "))
                    items = session.proposals(path) if command == "proposals" else session.candidates(path)
                    for index, item in enumerate(items, 1): tell(f"{index}: {json.dumps(item, ensure_ascii=False, indent=2)}")
                    selection = ask("Item number, all, or 0 to leave pending: ").strip()
                    if selection == "0": continue
                    if selection == "all":
                        selected = items
                    else:
                        index = int(selection)
                        if not 1 <= index <= len(items): raise ValueError("Invalid item number")
                        selected = [items[index - 1]]
                    actions = {}
                    receipts = []
                    if command == "proposals":
                        for item in selected:
                            rid = item["requirement_id"]
                            for q in item["clarification_questions"]:
                                tell(q["question"] + " Reason: " + q["reason"])
                                choice = ask("Accept question / reject / leave pending [accept/reject/pending]: ").strip()
                                if choice == "reject": session.review_receipt(path, False, q["question"])
                                elif choice == "accept":
                                    actions.setdefault(rid, {"requirement_id": rid, "clarification_questions": []})["clarification_questions"].append(q["question"])
                                    receipts.append(q["question"])
                        tell("Optional rewrites remain untrusted; use edit for explicit human-authored submission.")
                    else:
                        for rid, candidate in selected:
                            choice = ask("Register candidate / reject / leave pending [register/reject/pending]: ").strip()
                            if choice == "register":
                                if actions.get(rid, {}).get("human_decision") == "rejected":
                                    raise ValueError("Register and reject alternatives for the same requirement in separate reviews")
                                actions.setdefault(rid, {"requirement_id": rid, "candidate_texts": []})["candidate_texts"].append(candidate["text"])
                            elif choice == "reject":
                                if rid in actions: raise ValueError("Review a rejected candidate separately from another candidate for the same requirement")
                                actions[rid] = {"requirement_id": rid, "candidate_texts": [candidate["text"]],
                                    "selected_candidate_text": candidate["text"], "human_decision": "rejected"}
                    if actions:
                        reviewer = ask("Your reviewer ID: ")
                        if ask("Publish reviewed actions through refine? Type yes: ") == "yes":
                            session.apply(list(actions.values()), reviewer, True)
                            for receipt in receipts: session.review_receipt(path, True, receipt)
                            tell("Reviewed items registered; no rewrite automatically approved. Other old sidecars are now stale.")
                    continue
                if command == "generate":
                    if ask("Run existing deterministic candidate generator only? Type yes: ") == "yes":
                        path = workspace / "sidecars" / ("candidates-" + uuid.uuid4().hex + ".json")
                        generate_candidates_run(session.current, session.source, path)
                        tell(f"Saved candidates: {path}")
                    continue
                if command not in {"answer", "select", "edit", "decision"}:
                    tell("Unknown command; no changes made.")
                    continue
                rid = ask("Requirement ID: ").strip()
                if rid not in {r["requirement_id"] for r in data["requirements"]}: raise ValueError("Unknown requirement ID")
                action = {"requirement_id": rid}
                if command == "answer":
                    record = state["requirements"][rid]
                    questions = list(record["questions"].values())
                    for i, q in enumerate(questions, 1): tell(f"{i}: {q['text']} ({q['status']})")
                    i = int(ask("Question number: "))
                    if not 1 <= i <= len(questions): raise ValueError("Invalid question number")
                    answer = {"question_id": questions[i - 1]["question_id"], "answer": ask("Your answer: ")}
                    span = ask("Exact original span replaced, or Enter if none: ")
                    if span: answer["replaces_span"] = span
                    action["clarification_answers"] = [answer]
                    tell("Recording an answer does not guarantee grounding. Exact scaffold/span binding or a suitable whole-obligation answer may be required.")
                elif command == "select":
                    action["selected_candidate_id"] = ask("Existing candidate ID: ").strip()
                elif command == "edit":
                    action["selected_candidate_text"] = ask("Candidate text (registered/selected pending; no implied approval): ")
                else:
                    decision = ask("Explicit decision [approved/edited/rejected/pending/not_required]: ").strip()
                    if decision not in {"approved", "edited", "rejected", "pending", "not_required"}: raise ValueError("Invalid decision")
                    action["human_decision"] = decision
                    if decision == "edited": action["edited_text"] = ask("Explicitly accepted edited text: ")
                reviewer = ask("Your reviewer ID: ")
                if ask("Publish this action through refine? Type yes: ") == "yes":
                    session.apply(action, reviewer, True)
                    tell("Published and revalidated. Approval never overrides independent checks; inspect issues for blockers.")
            except (EOFError, KeyboardInterrupt):
                tell("Paused. Published snapshots and pending operation records retained; no replay on resume.")
                break
            except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
                tell(f"Action stopped: {error}")
