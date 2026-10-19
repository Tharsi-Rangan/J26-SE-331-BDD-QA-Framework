"""Internal, cumulative human workflow ledger; frozen C1 contract stays unchanged."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from c1_requirement_quality.refinement import (
    clarification_questions_for, stable_candidate_id,
)
from c1_requirement_quality.source_integrity import sha256, verify_source
from c1_requirement_quality.validation_lifecycle import original_assessments, clarification_resolution, validation_signature

WORKFLOW_FILE = "workflow_snapshot.json"
MAX_SNAPSHOT_ANCESTORS = 1024
STATUSES = {"OPEN", "ANSWERED", "REOPENED", "CLOSED"}
BASE_FIELDS = {"requirement_id", "clarification_questions", "clarification_answers",
               "candidate_texts", "selected_candidate_id", "selected_candidate_text",
               "human_decision", "edited_text"}
EXTRA_FIELDS = {"actor_id", "human_timestamp", "workflow_action", "question_actions",
                "reconsider_candidate_ids", "resolution", "reason"}
WORKFLOW_ACTIONS = {"approve", "reject", "request_clarification", "escalate", "reopen", "resolve_escalation"}


def candidate_evidence_path(workspace: Path, relative: str) -> Path:
    """Restrict registry files to the session evidence tree; reject reparse points."""
    if (not isinstance(relative, str) or "\\" in relative or ":" in relative
            or not relative.startswith("candidate_evidence/")
            or any(part in {"", ".", ".."} for part in relative.split("/"))):
        raise ValueError("Unsafe candidate evidence path")
    root = workspace.resolve()
    path = root
    for part in relative.split("/"):
        path = path / part
        if path.is_symlink() or (path.exists() and getattr(path.lstat(), "st_file_attributes", 0)
                                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("Candidate evidence symlink/reparse escape")
    def comparable(value):
        # Windows realpath can retain its extended prefix when a directory is
        # created concurrently. Normalize only that spelling, not path traversal.
        spelling = str(value)
        if os.name == "nt":
            if spelling.startswith("\\\\?\\UNC\\"):
                spelling = "\\\\" + spelling[8:]
            elif spelling.startswith("\\\\?\\"):
                spelling = spelling[4:]
        return Path(spelling)
    if not comparable(path.resolve()).is_relative_to(comparable(root)):
        raise ValueError("Candidate evidence path escapes workspace")
    return path


def _candidate_snapshot_identity(manifest: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Identify an already verified snapshot, including its full workflow basis."""
    from c1_requirement_quality.rag.candidate_validation import _canonical
    return {"parent_artifact_sha256": manifest["artifact_sha256"],
            "snapshot_id": state["snapshot_id"], "workflow_sha256": manifest.get("workflow_sha256"),
            "workflow_basis_sha256": sha256(_canonical(state))}


def _read_candidate_reference(workspace: Path, event: dict[str, Any]) -> dict[str, Any]:
    """Read a reference using the digest from an already verified journal event."""
    raw = candidate_evidence_path(workspace, event["reference"]).read_bytes()
    if sha256(raw) != event["reference_sha256"]:
        raise ValueError("Candidate registry reference digest mismatch")
    reference = json.loads(raw)
    fields = {"registry_version", "parent_artifact_sha256", "snapshot_id", "evidence",
              "requirement_id", "candidate_text", "receipt_sha256", "top_k", "candidate_id",
              "binding", "models"}
    if (not isinstance(reference, dict) or set(reference) != fields
            or any(not isinstance(reference[key], str) for key in
                   ("parent_artifact_sha256", "snapshot_id", "evidence", "requirement_id",
                    "candidate_text", "receipt_sha256", "candidate_id"))
            or reference.get("registry_version") != 1
            or reference.get("parent_artifact_sha256") != event["artifact_sha256"]):
        raise ValueError("Candidate registry identity mismatch")
    identity = event["snapshot_identity"]
    if (reference.get("snapshot_id") != identity["snapshot_id"]
            or not isinstance(reference.get("binding"), dict)
            or any(reference["binding"].get(key) != value for key, value in identity.items())):
        raise ValueError("Candidate registry snapshot mismatch")
    return reference


def restore_candidate_receipts(workspace: Path, context, *, analyser_factory=None):
    """Use journal-retained digests, never a receipt read from evidence itself.

    Reload the session journal ourselves, rather than accepting caller events.
    Local storage is the trust anchor; not authentication against wholesale rewriting.
    """
    from c1_requirement_quality.source_integrity import resolve_workflow_policy
    from c1_requirement_quality.rag.candidate_validation import (
        CandidateGroundingContext, load_candidate_validation,
    )
    from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser
    from c1_requirement_quality.demo_workflow import DemoSession
    _, _, manifest, state = resolve_workflow_policy(context)
    session = DemoSession(workspace, analyser_factory=analyser_factory)
    if (session.current.resolve() != context.input_path.resolve()
            or session.source.resolve() != context.source.resolve()):
        raise ValueError("Candidate registry workflow context mismatch")
    current_identity = _candidate_snapshot_identity(manifest, state)
    factory = analyser_factory or RAGGroundingAnalyser
    receipts = {}
    top_k = None
    for event in session.events:
        if event["kind"] != "candidate_evidence_registered":
            continue
        reference = _read_candidate_reference(workspace, event)
        # Replay verified this identity against the actual snapshot active at
        # registration, not just against a caller-provided snapshot identifier.
        identity = event["snapshot_identity"]
        # Equal artifact bytes need not mean equal clarification/workflow state.
        # Verified historical references remain audit data, never current evidence.
        if identity != current_identity:
            continue
        evidence = candidate_evidence_path(workspace, reference["evidence"])
        record = load_candidate_validation(evidence, context.input_path, context.source,
            reference["requirement_id"], reference["candidate_text"],
            expected_sha256=reference["receipt_sha256"], top_k=reference["top_k"],
            analyser_factory=factory)
        if (record["binding"] != reference.get("binding")
                or record["models"] != reference.get("models")
                or record["binding"]["candidate_id"] != reference.get("candidate_id")):
            raise ValueError("Candidate registry evidence binding mismatch")
        cid = reference["candidate_id"]
        if cid in receipts:
            raise ValueError("Duplicate candidate registry reference")
        if top_k is not None and top_k != reference["top_k"]:
            raise ValueError("Inconsistent candidate registry retrieval policy")
        top_k = reference["top_k"]
        receipts[cid] = (evidence, reference["receipt_sha256"])
    return CandidateGroundingContext(context.input_path, context.source, receipts,
                                    top_k or 5, factory)


PARENT_EVIDENCE_PURPOSE = "historical-parent-bound-transition-evidence"


def refinement_operation_binding(operation: dict[str, Any]) -> dict[str, Any]:
    """Project an independently journal-verified pending event into child metadata.

    This projection alone is not provenance or permission to publish/adopt.
    """
    return {"version": 1, "operation_id": operation["operation_id"],
            "pending_sha256": operation["sha256"],
            **{key: copy.deepcopy(operation[key]) for key in (
                "parent_identity", "actions_sha256", "actions_parsed_sha256", "registry_anchor",
                "evidence_candidate_ids", "evidence_links_sha256", "child_snapshot_id")}}


def build_parent_evidence_links(parent_context, registry_workspace: Path, candidate_ids: list[str], *,
                                analyser_factory=None, registry_anchor=None) -> dict[str, Any]:
    """Build metadata only, from independently anchored parent registrations.

    No files are copied or published. Archive paths preserve the original relative
    tree under the future child's C1 directory. The registry remains a required
    independent trust anchor in this foundation; child metadata cannot self-authenticate.
    """
    from c1_requirement_quality.source_integrity import resolve_workflow_policy
    from c1_requirement_quality.demo_workflow import DemoSession
    from c1_requirement_quality.rag.candidate_validation import load_candidate_validation
    from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser
    _, _, manifest, state = resolve_workflow_policy(parent_context)
    if (not isinstance(candidate_ids, list) or not candidate_ids
            or any(not isinstance(cid, str) for cid in candidate_ids)
            or len(set(candidate_ids)) != len(candidate_ids)):
        raise ValueError("Nonempty unique candidate IDs required")
    identity = _candidate_snapshot_identity(manifest, state)
    # Replay verifies each registration against the snapshot actually active at
    # that event, including historical parents after the session has advanced.
    session = DemoSession(registry_workspace, _registry_anchor=registry_anchor,
                          analyser_factory=analyser_factory)
    registered = {}
    for event in session.events:
        if event["kind"] != "candidate_evidence_registered":
            continue
        reference = _read_candidate_reference(registry_workspace, event)
        if event["snapshot_identity"] != identity:
            continue
        cid = reference["candidate_id"]
        if cid in registered:
            raise ValueError("Duplicate parent evidence registration")
        registered[cid] = (event, reference)
    factory = analyser_factory or RAGGroundingAnalyser
    links = []
    for cid in candidate_ids:
        if cid not in registered:
            raise ValueError("Parent evidence has no trusted registration")
        event, reference = registered[cid]
        evidence = candidate_evidence_path(registry_workspace, reference["evidence"])
        record = load_candidate_validation(evidence, parent_context.input_path, parent_context.source,
            reference["requirement_id"], reference["candidate_text"],
            expected_sha256=reference["receipt_sha256"], top_k=reference["top_k"], analyser_factory=factory)
        if (record["binding"] != reference["binding"] or record["models"] != reference["models"]
                or record["binding"]["candidate_id"] != cid):
            raise ValueError("Parent evidence registration binding mismatch")
        links.append({"binding": copy.deepcopy(record["binding"]), "candidate_text": record["candidate_text"],
            "models": copy.deepcopy(record["models"]), "receipt_sha256": reference["receipt_sha256"],
            "reference_sha256": event["reference_sha256"], "reference_path": event["reference"],
            "evidence_path": reference["evidence"]})
    return {"version": 1, "purpose": PARENT_EVIDENCE_PURPOSE, "links": links}


def _write_evidence_archive(c1_dir: Path, relative: str, raw: bytes) -> None:
    """Create one archive file relative to pinned, non-reparse directory handles.

    Path checks are only preflight. Actual creation never resolves the full
    destination again. Unsupported handle operations fail before file creation.
    """
    candidate_evidence_path(c1_dir, relative)
    absolute = Path(os.path.abspath(c1_dir))
    parts = relative.split("/")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt

        class UnicodeString(ctypes.Structure):
            _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                        ("Buffer", wintypes.LPWSTR)]

        class ObjectAttributes(ctypes.Structure):
            _fields_ = [("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                        ("ObjectName", ctypes.POINTER(UnicodeString)), ("Attributes", wintypes.ULONG),
                        ("SecurityDescriptor", ctypes.c_void_p), ("SecurityQualityOfService", ctypes.c_void_p)]

        class IoStatus(ctypes.Structure):
            _fields_ = [("StatusOrPointer", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

        class AttributeTag(ctypes.Structure):
            _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]

        native = ctypes.WinDLL("ntdll", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        native.NtCreateFile.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.ULONG,
            ctypes.POINTER(ObjectAttributes), ctypes.POINTER(IoStatus), ctypes.c_void_p,
            wintypes.ULONG, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
        native.NtCreateFile.restype = wintypes.LONG
        native.RtlNtStatusToDosError.argtypes = [wintypes.LONG]
        native.RtlNtStatusToDosError.restype = wintypes.ULONG
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
        kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        kernel.GetDriveTypeW.restype = wintypes.UINT
        anchor = absolute.anchor
        if anchor.startswith("\\\\") or kernel.GetDriveTypeW(anchor) not in {2, 3, 6}:
            raise OSError("Evidence archiving requires a local Windows filesystem")
        handles = []

        def open_relative(name, parent, *, directory, create, pin=False):
            buffer = ctypes.create_unicode_buffer(name)
            length = len(name.encode("utf-16-le"))
            if length > 65532:
                raise ValueError("Archive path component is too long")
            string = UnicodeString(length, length + 2, ctypes.cast(buffer, wintypes.LPWSTR))
            # OBJ_DONT_REPARSE | OBJ_CASE_INSENSITIVE. The archive root and
            # descendants request list access so write/delete share denial is
            # enforced (attribute-only handles do not prevent Windows renames).
            attributes = ObjectAttributes(ctypes.sizeof(ObjectAttributes), parent,
                ctypes.pointer(string), 0x1040, None, None)
            handle, status_block = wintypes.HANDLE(), IoStatus()
            options = 0x200000 | (0x1 if directory else 0x60)
            access = (0x81 if pin else 0x80) if directory else 0x100002
            status = native.NtCreateFile(ctypes.byref(handle), access,
                ctypes.byref(attributes), ctypes.byref(status_block), None,
                0x10 if directory else 0x80, 1 if directory else 0,
                (3 if create else 1) if directory else 2, options, None, 0)
            if status < 0:
                error = ctypes.WinError(native.RtlNtStatusToDosError(status))
                error.filename = name
                raise error
            if directory:
                info = AttributeTag()
                if not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                    error = ctypes.WinError(ctypes.get_last_error())
                    kernel.CloseHandle(handle)
                    raise error
                if info.FileAttributes & 0x400:
                    kernel.CloseHandle(handle)
                    raise ValueError("Candidate evidence symlink/reparse escape")
                handles.append(handle)
            return handle

        try:
            parent = open_relative("\\??\\" + anchor, None, directory=True, create=False,
                                   pin=len(absolute.parts) == 1)
            for index, part in enumerate(absolute.parts[1:], 1):
                parent = open_relative(part, parent, directory=True, create=False,
                                       pin=index == len(absolute.parts) - 1)
            for part in parts[:-1]:
                parent = open_relative(part, parent, directory=True, create=True, pin=True)
            handle = open_relative(parts[-1], parent, directory=False, create=True)
            try:
                descriptor = msvcrt.open_osfhandle(handle.value, os.O_WRONLY | os.O_BINARY)
            except BaseException:
                kernel.CloseHandle(handle)
                raise
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            for handle in reversed(handles):
                kernel.CloseHandle(handle)
    else:
        if (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
                or os.open not in os.supports_dir_fd or os.mkdir not in os.supports_dir_fd):
            raise OSError("Secure handle-relative evidence creation is unavailable")
        handles = []
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            parent = os.open(absolute.anchor, flags)
            handles.append(parent)
            for part in absolute.parts[1:]:
                parent = os.open(part, flags, dir_fd=parent)
                handles.append(parent)
            for part in parts[:-1]:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                parent = os.open(part, flags, dir_fd=parent)
                handles.append(parent)
            descriptor = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            for descriptor in reversed(handles):
                os.close(descriptor)


def archive_parent_evidence_links(parent_context, registry_workspace: Path, c1_dir: Path,
                                  candidate_ids: list[str], *, analyser_factory=None,
                                  registry_anchor=None) -> dict[str, Any]:
    """Copy verified original bytes exclusively into an unpublished child bundle.

    Return metadata for sealing in the workflow snapshot. Partial files remain
    untrusted staging data on failure; neither repair nor publication occurs.
    """
    if (not c1_dir.is_dir() or c1_dir.is_symlink()
            or getattr(c1_dir.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise ValueError("Evidence archive requires an owned staging directory")
    if any((c1_dir / "internal" / name).exists() for name in
           ("source_manifest.json", WORKFLOW_FILE)):
        raise ValueError("Evidence archive must precede workflow sealing")
    links = build_parent_evidence_links(parent_context, registry_workspace, candidate_ids,
                                        analyser_factory=analyser_factory, registry_anchor=registry_anchor)
    copies = {}
    for link in links["links"]:
        for key, digest in (("reference_path", "reference_sha256"), ("evidence_path", "receipt_sha256")):
            relative = link[key]
            destination = candidate_evidence_path(c1_dir, relative)
            if destination in copies:
                raise ValueError("Duplicate evidence archive destination")
            if destination.exists():
                raise FileExistsError(destination)
            raw = candidate_evidence_path(registry_workspace, relative).read_bytes()
            if sha256(raw) != link[digest]:
                raise ValueError("Evidence changed before archiving")
            copies[destination] = raw
    for destination, raw in copies.items():
        relative = destination.relative_to(c1_dir).as_posix()
        candidate_evidence_path(c1_dir, relative)
        _write_evidence_archive(c1_dir, relative, raw)
    if build_parent_evidence_links(parent_context, registry_workspace, candidate_ids,
                                   analyser_factory=analyser_factory, registry_anchor=registry_anchor) != links:
        raise ValueError("Parent evidence changed during archiving")
    return links


def verify_child_evidence_links(child_path: Path, source: Path, *, registry_workspace: Path,
                                analyser_factory=None, registry_anchor=None) -> dict[str, Any]:
    """Read sealed child metadata and verify P -> E -> C, never child approval.

    Evidence is loaded against the immediate ORIGINAL parent, not the child.
    The originating verified session journal is required; caller-supplied digests
    or links are not accepted as a replacement. No inference or writes occur.
    """
    from c1_requirement_quality.source_integrity import VerifiedWorkflowContext, resolve_workflow_policy
    from c1_requirement_quality.rag.candidate_validation import load_candidate_validation
    from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser
    child_context = VerifiedWorkflowContext(child_path, source)
    _, _, manifest, state = resolve_workflow_policy(child_context)
    parent = state.get("parent")
    if not parent:
        raise ValueError("Child evidence requires a verified immediate parent")
    parent_path = (child_path.parent / parent["artifact_path"]).resolve()
    parent_context = VerifiedWorkflowContext(parent_path, source)
    # load_state above verified the full ancestry and parent reference hashes.
    _, _, parent_manifest, _ = resolve_workflow_policy(parent_context)
    if parent_manifest["artifact_sha256"] != parent["artifact_sha256"]:
        raise ValueError("Parent artifact digest mismatch")
    envelope = state.get("parent_evidence_links")
    if (not isinstance(envelope, dict) or set(envelope) != {"version", "purpose", "links"}
            or type(envelope["version"]) is not int or envelope["version"] != 1
            or envelope["purpose"] != PARENT_EVIDENCE_PURPOSE
            or not isinstance(envelope["links"], list) or not envelope["links"]):
        raise ValueError("Invalid historical parent evidence-link envelope")
    fields = {"binding", "candidate_text", "models", "receipt_sha256", "reference_sha256",
              "reference_path", "evidence_path"}
    ids, archive_paths = [], set()
    for link in envelope["links"]:
        if (not isinstance(link, dict) or set(link) != fields or not isinstance(link["binding"], dict)
                or not isinstance(link["candidate_text"], str)):
            raise ValueError("Malformed parent evidence link")
        binding = link["binding"]
        cid, rid = binding.get("candidate_id"), binding.get("requirement_id")
        if not isinstance(cid, str) or not isinstance(rid, str) or cid != stable_candidate_id(rid, link["candidate_text"]):
            raise ValueError("Parent evidence candidate identity mismatch")
        if cid in ids:
            raise ValueError("Duplicate or ambiguous parent evidence link")
        ids.append(cid)
        for key in ("reference_path", "evidence_path"):
            path = candidate_evidence_path(child_path.parent, link[key])
            resolved = path.resolve()
            if resolved in archive_paths:
                raise ValueError("Duplicate or ambiguous evidence archive path")
            archive_paths.add(resolved)
    expected = build_parent_evidence_links(parent_context, registry_workspace, ids,
                                           analyser_factory=analyser_factory, registry_anchor=registry_anchor)
    if envelope != expected:
        raise ValueError("Child links differ from trusted parent evidence")
    # Compare only content parsed from these exact, hash-verified bytes. A later
    # context check cannot detect a temporary substitution restored before it.
    child_raw = child_path.read_bytes()
    if sha256(child_raw) != manifest["artifact_sha256"]:
        raise ValueError("Child artifact digest mismatch")
    child = json.loads(child_raw)
    parent_raw = parent_path.read_bytes()
    if sha256(parent_raw) != parent["artifact_sha256"]:
        raise ValueError("Parent artifact digest mismatch")
    original = json.loads(parent_raw)
    factory = analyser_factory or RAGGroundingAnalyser
    results = []
    for link in envelope["links"]:
        binding = link["binding"]
        rid, cid = binding["requirement_id"], binding["candidate_id"]
        rows = [row for row in child["requirements"] if row["requirement_id"] == rid]
        parents = [row for row in original["requirements"] if row["requirement_id"] == rid]
        if (len(rows) != 1 or len(parents) != 1 or rows[0]["original_text"] != parents[0]["original_text"]
                or [c["text"] for c in rows[0].get("candidates", []) if c["candidate_id"] == cid] != [link["candidate_text"]]):
            raise ValueError("Child requirement or candidate identity mismatch")
        reference = candidate_evidence_path(child_path.parent, link["reference_path"])
        if sha256(reference.read_bytes()) != link["reference_sha256"]:
            raise ValueError("Archived reference receipt mismatch")
        evidence = candidate_evidence_path(child_path.parent, link["evidence_path"])
        record = load_candidate_validation(evidence, parent_path, source, rid, link["candidate_text"],
            expected_sha256=link["receipt_sha256"], top_k=binding["retrieval"]["top_k"], analyser_factory=factory)
        if record["binding"] != binding or record["models"] != link["models"]:
            raise ValueError("Archived parent evidence binding mismatch")
        results.append({"requirement_id": rid, "candidate_id": cid, "origin_snapshot_id": binding["snapshot_id"],
                        "verdict_on_parent": record["verdict"], "completion_status": record["completion_status"]})
    _, _, current_manifest, current_state = resolve_workflow_policy(child_context)
    if current_manifest != manifest or current_state != state:
        raise ValueError("Child evidence context changed during verification")
    return {"version": 1, "purpose": PARENT_EVIDENCE_PURPOSE, "child_snapshot_id": state["snapshot_id"],
            "child_independently_validated": False, "approval_authorized": False,
            "publication_authorized": False, "bdd_ready_authorized": False, "links": results}


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


def _ancestry_identity(manifest, state):
    from c1_requirement_quality.rag.candidate_validation import _canonical
    return {"snapshot_id": state["snapshot_id"],
            "artifact_sha256": manifest["artifact_sha256"],
            "workflow_sha256": manifest["workflow_sha256"],
            "manifest_sha256": sha256(_canonical(manifest)),
            "source_identity": {k: manifest[k] for k in
                                ("document_id", "sha256", "normalized_sha256")},
            "rag_provenance_sha256": manifest["rag_provenance_sha256"],
            "rag_diagnostics_sha256": manifest["rag_diagnostics_sha256"]}


def _initial_rag_transition(manifest, state):
    from c1_requirement_quality.rag.candidate_validation import verification_policy
    identity = _ancestry_identity(manifest, state)
    prior = state.get("initial_rag_ancestry")
    return {"version": 1, "purpose": "historical-initial-rag-ancestry",
            "parent": identity, "root": copy.deepcopy(prior["root"] if prior else identity),
            "verification_policy": verification_policy()}


def _reject_ancestry_reparse(path):
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0)
                                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("Unsafe initial RAG ancestor symlink/reparse path")


def build_initial_rag_ancestry(parent_context):
    """Describe a verified parent for staging; this never authorizes publication.

    Only identities are carried forward. Original diagnostics and candidate
    archives stay at their original snapshots and retain their original scope.
    """
    from c1_requirement_quality.source_integrity import resolve_workflow_policy
    rag, _, manifest, state = resolve_workflow_policy(parent_context)
    if not rag:
        return None
    if manifest.get("workflow_sha256") is None:
        raise ValueError("Sealed initial RAG workflow required")
    return _initial_rag_transition(manifest, state)


def verify_initial_rag_ancestry(input_path: Path, source: Path):
    """Audit the complete sealed lineage without constructing a DemoSession."""
    state, manifest = load_state(input_path, source)
    if manifest.get("rag_policy") != "c1-initial-rag-v1":
        raise ValueError("Initial RAG ancestry required")
    ancestry = state.get("initial_rag_ancestry")
    return {"version": 1, "purpose": "historical-initial-rag-ancestry",
            "snapshot_id": state["snapshot_id"], "generations": state["round"],
            "root": copy.deepcopy(ancestry["root"] if ancestry else _ancestry_identity(manifest, state)),
            "candidate_evidence_verified": False,
            "child_independently_validated": False, "approval_authorized": False,
            "publication_authorized": False, "bdd_ready_authorized": False}


def load_state(input_path: Path, source: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify the complete parent chain, hashes, identity and cumulative history."""
    current = input_path.resolve(); seen_paths: set[Path] = set(); seen_ids: set[str] = set()
    from c1_requirement_quality.source_integrity import _verify_source_local
    from c1_requirement_quality.rag.candidate_validation import _canonical
    child: dict[str, Any] | None = None; result = None; first_manifest = None
    child_manifest = None
    while True:
        if current in seen_paths: raise ValueError("Snapshot lineage cycle")
        if len(seen_paths) >= MAX_SNAPSHOT_ANCESTORS:
            raise ValueError(f"Snapshot ancestry exceeds verification limit ({MAX_SNAPSHOT_ANCESTORS})")
        seen_paths.add(current)
        original_source_text, manifest, artifact = _verify_source_local(current, source)
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
        descendant = "rag_ancestry_version" in manifest
        if descendant or (first_manifest and "rag_ancestry_version" in first_manifest):
            for checked in (input_path if result is None else current,
                            path, current.parent / "internal/source_manifest.json",
                            current.parent / "internal" / manifest["archived_source"],
                            current.parent / "internal/normalized_ingestion.json",
                            current.parent / "internal/rag_provenance.json",
                            current.parent / "rag_diagnostics.json"):
                _reject_ancestry_reparse(checked)
        if descendant != ("initial_rag_ancestry" in state):
            raise ValueError("Initial RAG ancestry manifest/workflow mismatch")
        if descendant and (state.get("parent") is None or any(
                r.get("bdd_ready") or r.get("human_decision") in {"approved", "edited"}
                for r in artifact["requirements"])):
            raise ValueError("Initial RAG descendant authorization remains blocked")
        if manifest.get("rag_policy") and not descendant and state.get("parent") is not None:
            raise ValueError("Initial RAG descendant ancestry missing")
        if child is not None:
            reference = child["parent"]
            if (reference["snapshot_id"] != state["snapshot_id"] or reference["artifact_sha256"] != manifest["artifact_sha256"]
                    or reference["workflow_sha256"] != expected_hash or child["round"] != state["round"] + 1
                    or reference.get("legacy_diagnostics_sha256") != state.get("legacy_diagnostics_sha256")
                    or child["source_identity"] != state["source_identity"]):
                raise ValueError("Parent snapshot reference mismatch")
            if manifest.get("rag_policy") or child_manifest.get("rag_policy"):
                if (manifest.get("rag_policy") != "c1-initial-rag-v1"
                        or child_manifest.get("rag_policy") != manifest["rag_policy"]
                        or child_manifest.get("rag_ancestry_version") != 1
                        or _canonical(child.get("initial_rag_ancestry")) != _canonical(_initial_rag_transition(manifest, state))
                        or any(child_manifest.get(k) != manifest.get(k) for k in
                               ("rag_provenance_sha256", "rag_diagnostics_sha256"))):
                    raise ValueError("Initial RAG ancestry transition mismatch")
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
        if descendant and (":" in location or location.startswith("/")):
            raise ValueError("Unsafe initial RAG ancestor path")
        next_path = current.parent / location
        if descendant:
            # Resolve only after rejecting links/reparse points, including at
            # ancestor directories; relative '..' remains needed for siblings.
            _reject_ancestry_reparse(next_path)
        child, child_manifest, current = state, manifest, next_path.resolve()
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
                        manifest: dict[str, Any], *, snapshot_id: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    from c1_requirement_quality.source_integrity import require_refinement_grounding, VerifiedWorkflowContext, resolve_workflow_policy
    source = parent_path.parent / "internal" / manifest["archived_source"]
    policy_context = VerifiedWorkflowContext(parent_path, source)
    _, _, verified_manifest, verified_parent = resolve_workflow_policy(policy_context, artifact=artifact, source_text=source_text)
    if verified_manifest != manifest or manifest.get("workflow_sha256") is not None and verified_parent != parent:
        raise ValueError("Unverified workflow parent or manifest")
    # Unsealed legacy adoption constructs fresh event IDs. Adopt only history
    # reconstructed from verified source/diagnostics, never the caller's copy.
    parent = verified_parent
    require_refinement_grounding(verified_manifest)
    from c1_requirement_quality.refinement import _process_refinement_actions
    if (set(actions) - {"requirements", "consistency_reviews"} or "requirements" not in actions
            or not isinstance(actions["requirements"], list)):
        raise ValueError("Actions require requirements and optional consistency_reviews lists")
    from c1_requirement_quality.effective_consistency import context_from_state, views, create_review, assess_all
    state = copy.deepcopy(parent)
    # These links describe one immediate-parent transition. Its audit history
    # remains in the immutable parent, never as current links on a grandchild.
    state.pop("parent_evidence_links", None)
    state.pop("operation_binding", None)
    state.update(snapshot_id=snapshot_id or "SNAPSHOT-" + uuid.uuid4().hex, round=parent["round"] + 1,
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
    refined, diagnostics = _process_refinement_actions(artifact, {"requirements": prepared}, source_text,
        workflow_records=state["requirements"], consistency_context=review_context, workflow_context=policy_context)
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
        refined, diagnostics = _process_refinement_actions(refined, {"requirements": reset}, source_text,
            workflow_records=state["requirements"], consistency_context=current_context, workflow_context=policy_context)
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
