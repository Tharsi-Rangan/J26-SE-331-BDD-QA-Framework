"""Internal pair-applicability review snapshots; never consumed by decision gates."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from c1_requirement_quality.consistency_analyser import analyse_consistency
from c1_requirement_quality.source_integrity import verify_source
from c1_requirement_quality.ingest.models import NIRRequirement

STATES = {"relevant", "not_applicable", "unknown"}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _pair_id(ids: list[str]) -> str:
    return "PAIR-" + _digest(sorted(ids))


def load_review(path: Path) -> dict[str, Any]:
    """Validate an internal snapshot; checksums detect accidental alteration, not authorship."""
    value = json.loads(path.read_text(encoding="utf-8"))
    payload = {k: v for k, v in value.items() if k != "snapshot_sha256"}
    if value.get("version") != 1 or value.get("snapshot_sha256") != _digest(payload):
        raise ValueError("Invalid applicability snapshot or checksum")
    if value.get("decision_effect") != "none":
        raise ValueError("Applicability snapshots must have no decision effect")
    events = value.get("events")
    if not isinstance(events, list):
        raise ValueError("Invalid review history")
    for index, event in enumerate(events, 1):
        if (event.get("sequence") != index or event.get("applicability") not in STATES
                or not isinstance(event.get("reviewer"), str) or not event["reviewer"].strip()
                or not isinstance(event.get("rationale"), str) or not event["rationale"].strip()
                or not isinstance(event.get("binding"), str)):
            raise ValueError("Invalid review event")
    pairs = value.get("pairs", [])
    ids = [row.get("pair_id") for row in pairs]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate review pairs")
    for row in pairs:
        if row.get("applicability") not in STATES or row.get("pair_id") != _pair_id(row["requirement_ids"]):
            raise ValueError("Invalid pair record")
        if row["original_outcome"]["classification"] == "conflict" and row["applicability"] == "not_applicable":
            raise ValueError("Confirmed contradictions cannot be dismissed")
    return value


def build_review(artifact: dict[str, Any], document_id: str, *,
                 previous: dict[str, Any] | None = None,
                 decisions: list[dict[str, Any]] | None = None,
                 section_contexts: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """Recompute exhaustive original-text outcomes and bind human events to exact inputs."""
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("Document identity is required")
    if previous is not None and previous.get("document_id") != document_id:
        raise ValueError("Previous review belongs to a different document")
    rows = artifact["requirements"]
    analysis = analyse_consistency([{"requirement_id": r["requirement_id"], "text": r["original_text"]} for r in rows])
    inputs = {}
    for row in rows:
        rid = row["requirement_id"]
        inputs[rid] = {
            "original_text_sha256": _digest(row["original_text"]),
            "context": {"document_id": document_id, "section": row["source"]["section"],
                        "section_hierarchy": (section_contexts or {}).get(rid, []),
                        "current_text": row.get("final_text", row["original_text"])},
        }
    events = copy.deepcopy(previous["events"]) if previous else []
    previous_pairs = {p["pair_id"]: p for p in previous["pairs"]} if previous else {}
    pairs = []
    for outcome in analysis["pairs"]:
        ids = sorted(outcome["requirement_ids"])
        pid = _pair_id(ids)
        binding = _digest({"document_id": document_id, "inputs": {rid: inputs[rid] for rid in ids}})
        row = {"pair_id": pid, "requirement_ids": ids, "binding": binding,
               "original_outcome": copy.deepcopy(outcome), "applicability": "unknown",
               "review_event": None, "invalidation": None}
        prior = previous_pairs.get(pid)
        if prior and prior["binding"] != binding:
            row["invalidation"] = "Requirement text or context changed; a new review is required"
        elif prior and prior.get("review_event") is not None:
            event = events[prior["review_event"] - 1]
            if event["binding"] != binding or event["pair_id"] != pid:
                raise ValueError("Previous review event does not match pair binding")
            row.update(applicability=event["applicability"], review_event=event["sequence"])
        if outcome["classification"] == "conflict" and row["applicability"] == "not_applicable":
            row.update(applicability="unknown", review_event=None,
                       invalidation="Confirmed contradiction requires resolution")
        pairs.append(row)
    by_id = {p["pair_id"]: p for p in pairs}
    seen = set()
    if decisions is not None and not isinstance(decisions, list):
        raise ValueError("Review actions must contain a decisions list")
    for decision in decisions or []:
        if not isinstance(decision, dict) or set(decision) != {"requirement_ids", "applicability", "reviewer", "rationale"}:
            raise ValueError("Each decision requires exactly requirement_ids, applicability, reviewer and rationale")
        ids = decision["requirement_ids"]
        if not isinstance(ids, list) or len(ids) != 2 or any(not isinstance(rid, str) for rid in ids) or ids[0] == ids[1]:
            raise ValueError("A review requires two distinct requirement IDs")
        pid = _pair_id(ids)
        if pid not in by_id or pid in seen:
            raise ValueError("Unknown or repeated pair in review actions")
        seen.add(pid)
        if (not isinstance(decision["applicability"], str) or decision["applicability"] not in STATES
                or any(not isinstance(decision[k], str) or not decision[k].strip() for k in ("reviewer", "rationale"))):
            raise ValueError("Valid applicability, explicit reviewer and nonempty rationale are required")
        row = by_id[pid]
        if row["original_outcome"]["classification"] == "conflict" and decision["applicability"] == "not_applicable":
            raise ValueError("Confirmed contradictions cannot be dismissed as not_applicable")
        event = {**copy.deepcopy(decision), "sequence": len(events) + 1, "pair_id": pid,
                 "binding": row["binding"], "recorded_at": datetime.now(timezone.utc).isoformat()}
        events.append(event)
        row.update(applicability=event["applicability"], review_event=event["sequence"], invalidation=None)
    result = {"version": 1, "decision_effect": "none", "comparison_basis": "original_text",
              "document_id": document_id, "generated_at": datetime.now(timezone.utc).isoformat(),
              "parent_sha256": previous["snapshot_sha256"] if previous else None,
              "requirement_inputs": inputs, "pairs": pairs, "events": events}
    result["snapshot_sha256"] = _digest(result)
    return result


def write_review(path: Path, review: dict[str, Any]) -> None:
    """Publish an immutable new snapshot exclusively; never replace an earlier record."""
    if path.exists():
        raise FileExistsError(f"Review output already exists: {path}")
    payload = (json.dumps(review, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".c1-pair-review-pending-", dir=path.parent)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    # Exclusive publication; a failure retains the pending snapshot for inspection.
    os.link(name, path)
    Path(name).unlink()


def pair_review_run(input_path: Path, source: Path, out: Path, *,
                    previous_path: Path | None = None, actions_path: Path | None = None) -> None:
    from c1_requirement_quality.contract import validate_contract_artifact as _validate_contract_artifact
    if out.exists():
        raise FileExistsError(f"Review output already exists: {out}")
    artifact = json.loads(input_path.read_text(encoding="utf-8-sig"))
    _validate_contract_artifact(artifact)
    _, manifest = verify_source(input_path, source)
    nir_path = input_path.parent / "internal" / "normalized_ingestion.json"
    nir = json.loads(nir_path.read_text(encoding="utf-8"))
    sections = {}
    for row in artifact["requirements"]:
        matches = [r for r in nir["requirements"] if r["raw_text"] == row["original_text"]
                   and NIRRequirement(**r).to_source_dict() == row["source"]]
        if len(matches) != 1:
            raise ValueError("Cannot bind requirement to unique verified source context")
        sections[row["requirement_id"]] = matches[0]["section_hierarchy"]
    previous = load_review(previous_path) if previous_path else None
    actions = json.loads(actions_path.read_text(encoding="utf-8-sig")) if actions_path else None
    if actions is not None and (not isinstance(actions, dict) or set(actions) != {"decisions"}):
        raise ValueError("Actions must contain exactly a decisions list")
    review = build_review(artifact, manifest["document_id"], previous=previous,
                          decisions=actions["decisions"] if actions is not None else None,
                          section_contexts=sections)
    # Recheck immutable inputs immediately before publication.
    verify_source(input_path, source)
    if hashlib.sha256(nir_path.read_bytes()).hexdigest() != manifest["normalized_sha256"]:
        raise ValueError("Normalized source changed during review")
    write_review(out, review)
    counts = {state: sum(p["applicability"] == state for p in review["pairs"]) for state in sorted(STATES)}
    print(f"[c1] applicability only; no tier/readiness effect: {counts}")
    print(f"[c1] wrote {len(review['pairs'])} pairs to {out}")
