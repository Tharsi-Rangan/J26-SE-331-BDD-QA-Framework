"""Untrusted cloud clarification sidecars; explicit human actions remain separate."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from c1_requirement_quality.groq_generator import GroqGeneratorBackend
from c1_requirement_quality.source_integrity import verify_source
from c1_requirement_quality.workflow_persistence import load_state
from c1_requirement_quality.validation_lifecycle import clarification_resolution
from c1_requirement_quality.refinement import _evaluate_candidate, _consistency_with_candidate, _candidate_validation
from c1_requirement_quality.tier_classifier import classify_tier
from c1_requirement_quality.ml.ml_defect_classifier import EXPERIMENT2_LABELS, EXPERIMENT2_FILES

PROMPT_VERSION = "c1-clarification-v1"
REFS = {"type": "array", "maxItems": 8, "uniqueItems": True, "items": {"type": "string", "minLength": 1, "maxLength": 160}}
TEXT = {"type": "string", "minLength": 1, "maxLength": 1000}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


PROPOSAL_SCHEMA = _object({
    "schema_version": {"const": 1}, "requirement_id": {"type": "string", "minLength": 1, "maxLength": 100},
    "source_evidence_refs": REFS, "advisory_refs": REFS,
    "clarification_questions": {"type": "array", "maxItems": 3, "items": _object({
        "question": {"type": "string", "minLength": 1, "maxLength": 500}, "reason": TEXT,
        "source_evidence_refs": REFS, "advisory_refs": REFS})},
    "proposed_rewrite": {"anyOf": [{"type": "null"}, _object({"text": {"type": "string", "minLength": 1, "maxLength": 6000}, "source_evidence_refs": REFS})]},
    "unresolved_assumptions": {"type": "array", "maxItems": 5, "items": _object({"description": TEXT, "blocks_rewrite": {"type": "boolean"}})},
    "claimed_grounding_status": {"enum": ["supported", "insufficient", "conflicting"]},
})


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_diagnostics(path: Path, artifact: dict[str, Any], input_hash: str, kind: str) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    rows = artifact["requirements"]
    expected = {r["requirement_id"]: r["original_text"] for r in rows}
    records = data.get("requirements", [])
    text_key = "text" if kind == "distilbert" else "original_text"
    if (data.get("input_sha256") != input_hash or data.get("run_id") != artifact["run_id"]
            or data.get("advisory_only") is not True or data.get("status") != "experimental"
            or data.get("decision_effect") != "none" or len(records) != len(expected)
            or {r["requirement_id"]: r[text_key] for r in records} != expected):
        raise ValueError(f"{kind} diagnostics do not match input IDs, original texts, hash or advisory provenance")
    if kind == "distilbert":
        model = data.get("model", {})
        checkpoint = model.get("checkpoint", {})
        if (model.get("identifier") != "distilbert-requirement-defects"
                or model.get("label_order") != list(EXPERIMENT2_LABELS)
                or checkpoint.get("mapping_status") != "VERIFIED"
                or checkpoint.get("checkpoint_sha256") != EXPERIMENT2_FILES["model.safetensors"]
                or not isinstance(checkpoint.get("mapping_provenance"), str) or not checkpoint["mapping_provenance"].strip()):
            raise ValueError("DistilBERT diagnostic provenance is missing or unverified")
        for row in records:
            scores = row.get("scores", {})
            if (set(scores) != set(EXPERIMENT2_LABELS) or row.get("mapping_status") != "VERIFIED"
                    or row.get("checkpoint_sha256") != checkpoint["checkpoint_sha256"]
                    or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in scores.values())):
                raise ValueError("Invalid DistilBERT scores or checkpoint binding")
    else:
        model = data.get("model", {})
        if (data.get("source_document") != artifact["source_document"]
                or model.get("identifier") != "sentence-transformers/all-MiniLM-L6-v2"
                or model.get("local_files_only") is not True or data.get("embedding_dimension") != 384
                or not model.get("identity_note") or not model.get("asset_sha256")
                or any(not re.fullmatch(r"[0-9a-f]{64}", str(v)) for v in model["asset_sha256"].values())):
            raise ValueError("MiniLM diagnostic provenance is missing")
        seen = set()
        for pair in data.get("pairs", []):
            ids = pair.get("requirement_ids", [])
            score = pair.get("similarity")
            if (len(ids) != 2 or len(set(ids)) != 2 or not set(ids) <= expected.keys()
                    or tuple(sorted(ids)) in seen or type(score) not in (int, float)
                    or not math.isfinite(score) or not 0 <= score <= 1):
                raise ValueError("Invalid MiniLM pair")
            seen.add(tuple(sorted(ids)))
        if len(seen) != len(expected) * (len(expected) - 1) // 2:
            raise ValueError("MiniLM pair diagnostics are incomplete")
    return data, _hash(raw)


def _context(row: dict[str, Any], source_text: str, state: dict[str, Any],
             diagnostics: dict[str, dict[str, Any]], max_evidence_chars: int) -> dict[str, Any]:
    rid = row["requirement_id"]
    original = row["original_text"]
    start = source_text.find(original)
    if start < 0:
        raise ValueError("Original requirement is not an exact quotation of the verified normalized source")
    evidence = [{"ref": f"SRS:{rid}:original", "kind": "original_srs", "text": original,
                 "source": row["source"], "normalized_start_offset": start if source_text.count(original) == 1 else None}]
    record = state["requirements"][rid]
    resolution = clarification_resolution(record, original, [])
    # Only current valid, explicitly attributed human answers, never LLM proposals.
    for item in resolution["active_answers"]:
        answer = item["answer"]
        if answer.get("provenance", {}).get("kind") != "human_provided":
            continue
        evidence.append({"ref": "HUMAN:" + answer["answer_id"], "kind": "human_clarification_not_original_srs",
                         "question": item["question"]["text"], "text": answer["answer"]})
    if len(evidence) > 8 or sum(len(json.dumps(e, ensure_ascii=False)) for e in evidence) > max_evidence_chars:
        raise ValueError("Evidence size/count limit exceeded; no request sent")
    advisory = [{"ref": f"RULE:{rid}", "kind": "deterministic_diagnostics", "defects": row["defects"],
                 "consistency": row["consistency"], "tier": row["tier"],
                 "note": "Analysis only, never source evidence or approval"}]
    if "distilbert" in diagnostics:
        d = diagnostics["distilbert"]
        prediction = next(r for r in d["requirements"] if r["requirement_id"] == rid)
        advisory.append({"ref": f"ML:{rid}", "kind": "experimental_defect_scores", "scores": prediction["scores"],
                         "threshold": d["threshold"], "truncated": prediction.get("truncated"),
                         "model": {"identifier": d["model"]["identifier"], "checkpoint_sha256": d["model"]["checkpoint"]["checkpoint_sha256"]}, "note": "Not calibrated confidence or ground truth"})
    if "minilm" in diagnostics:
        d = diagnostics["minilm"]
        pairs = sorted([p for p in d["pairs"] if rid in p["requirement_ids"]], key=lambda p: (-p["similarity"], p["requirement_ids"]))[:3]
        advisory.append({"ref": f"SIM:{rid}", "kind": "experimental_similarity", "pairs": pairs,
                         "model": {"identifier": d["model"]["identifier"], "cache_revision": d["model"].get("cache_revision")}, "note": "Not duplication, contradiction, consistency or applicability evidence"})
    return {"requirement_id": rid, "original_text": original, "source_evidence": evidence,
            "advisory_context": advisory, "unresolved_questions": resolution["unresolved_questions"],
            "rewrite_blocked": row["consistency"]["status"] == "conflict" or record["escalation_active"]}


def validate_proposal(proposal: dict[str, Any], context: dict[str, Any], source_text: str,
                      rows: list[dict[str, Any]], record: dict[str, Any], source_format: str | None) -> dict[str, Any]:
    if list(Draft202012Validator(PROPOSAL_SCHEMA).iter_errors(proposal)):
        raise ValueError("Clarification proposal does not match internal schema v1")
    if proposal["requirement_id"] != context["requirement_id"]:
        raise ValueError("Proposal requirement ID mismatch")
    evidence = {e["ref"]: e for e in context["source_evidence"]}
    advisory = {a["ref"] for a in context["advisory_context"]}
    def refs(value):
        if not set(value["source_evidence_refs"]) <= evidence.keys() or not set(value.get("advisory_refs", [])) <= advisory:
            raise ValueError("Unknown or misclassified evidence/advisory reference")
    refs(proposal)
    children = [*proposal["clarification_questions"]]
    if proposal["proposed_rewrite"] is not None:
        children.append(proposal["proposed_rewrite"])
    if any(not set(child["source_evidence_refs"]) <= set(proposal["source_evidence_refs"])
           or not set(child.get("advisory_refs", [])) <= set(proposal["advisory_refs"]) for child in children):
        raise ValueError("Child references must be declared by the proposal")
    supplied_numbers = set(re.findall(r"\d+(?:\.\d+)?", " ".join(e["text"] for e in evidence.values())))
    seen = set()
    for question in proposal["clarification_questions"]:
        refs(question)
        text = question["question"].strip()
        if (not text.endswith("?") or text.count("?") != 1 or text.casefold() in seen
                or not question["reason"].strip() or not question["source_evidence_refs"]):
            raise ValueError("Questions require one clear question, rationale and evidence references")
        if set(re.findall(r"\d+(?:\.\d+)?", text + " " + question["reason"])) - supplied_numbers:
            raise ValueError("Question invents an unsupported numerical value")
        seen.add(text.casefold())
    result = copy.deepcopy(proposal)
    rewrite = proposal["proposed_rewrite"]
    validation: dict[str, Any] = {"rewrite_status": "not_proposed", "claimed_grounding_is_authoritative": False}
    if rewrite is not None:
        refs(rewrite)
        text = rewrite["text"]
        cited = set(rewrite["source_evidence_refs"])
        cited_source = "\n\n".join(e["text"] for ref, e in evidence.items()
                                     if ref in cited and e["kind"] == "original_srs")
        scoped_record = copy.deepcopy(record)
        for question in scoped_record["questions"].values():
            if "HUMAN:" + str(question.get("current_answer_id")) not in cited:
                question["current_answer_id"] = None
        evaluation = _evaluate_candidate(text, cited_source, context["original_text"], scoped_record, source_format=source_format)
        consistency = _consistency_with_candidate(context["requirement_id"], text, rows)
        tier = classify_tier(evaluation["quality_findings"], evaluation["grounding"], consistency,
                             original_text=context["original_text"], candidate_text=text)
        candidate = _candidate_validation(evaluation, consistency, text=text, tier=tier["tier"],
                                         clarification_questions=context["unresolved_questions"])
        numbers = set(re.findall(r"\d+(?:\.\d+)?", text))
        rejected = (not rewrite["source_evidence_refs"] or context["rewrite_blocked"]
                    or proposal["claimed_grounding_status"] == "conflicting"
                    or any(a["blocks_rewrite"] for a in proposal["unresolved_assumptions"])
                    or bool(numbers - supplied_numbers) or evaluation["grounding"]["status"] != "supported"
                    or consistency["status"] == "conflict"
                    or bool({r["type"] for r in evaluation["quality_findings"]} - {r["type"] for r in context["advisory_context"][0]["defects"]}))
        validation.update(rewrite_status="rejected" if rejected else "grounded_proposal_requires_human_review",
                          evaluation=evaluation, consistency=consistency, candidate_validation=candidate)
        if rejected:
            result["proposed_rewrite"] = None
            validation["rejected_rewrite"] = copy.deepcopy(rewrite)
            validation["reason"] = "Unsupported values/facts, unresolved assumptions, escalation, conflict or quality regression"
            if not result["clarification_questions"]:
                raise ValueError("Rejected rewrite leaves no independently valid clarification questions")
    result["validation"] = validation
    return result


def propose_clarifications_run(input_path: Path, source: Path, out: Path, requirement_ids: list[str], *,
                               defect_diagnostics: Path | None = None, similarity_diagnostics: Path | None = None,
                               max_requests: int = 2, max_evidence_chars: int = 6000,
                               max_context_chars: int = 12000) -> None:
    from c1_requirement_quality.contract import validate_contract_artifact as _validate_contract_artifact
    if out.exists():
        raise FileExistsError(f"Proposal output already exists: {out}")
    if (not requirement_ids or len(set(requirement_ids)) != len(requirement_ids)
            or type(max_requests) is not int or not 1 <= max_requests <= 5 or len(requirement_ids) > max_requests):
        raise ValueError("Select unique requirement IDs within max_requests (1..5; default 2)")
    if (type(max_evidence_chars) is not int or not 1 <= max_evidence_chars <= 20000
            or type(max_context_chars) is not int or not 1 <= max_context_chars <= 40000):
        raise ValueError("Invalid evidence/context size limit")
    raw = input_path.read_bytes()
    artifact = json.loads(raw.decode("utf-8-sig"))
    _validate_contract_artifact(artifact)
    source_text, manifest = verify_source(input_path, source)
    state, _ = load_state(input_path, source)
    inputs = {}
    hashes = {}
    for kind, path in [("distilbert", defect_diagnostics), ("minilm", similarity_diagnostics)]:
        if path is not None:
            inputs[kind], hashes[kind] = _load_diagnostics(path, artifact, _hash(raw), kind)
    rows = {r["requirement_id"]: r for r in artifact["requirements"]}
    if not set(requirement_ids) <= rows.keys():
        raise ValueError("Unknown selected requirement ID")
    contexts = [_context(rows[rid], source_text, state, inputs, max_evidence_chars) for rid in requirement_ids]
    for context in contexts:
        if len(json.dumps(context, ensure_ascii=False)) > max_context_chars:
            raise ValueError("Request context size limit exceeded; no request sent")
    backend = GroqGeneratorBackend.from_environment()
    proposals = []
    for context in contexts:
        started = time.perf_counter()
        response = backend.propose_clarification(context)
        validated = validate_proposal(response["proposal"], context, source_text,
                                      list(rows.values()), state["requirements"][context["requirement_id"]],
                                      "docx" if source.suffix.lower() == ".docx" else None)
        proposals.append({"proposal": validated, "request": {
            "context_sha256": _hash(json.dumps(context, sort_keys=True, ensure_ascii=False).encode()),
            "sent_context": context, "model_requested": backend.model, "model_returned": response["model"],
            "recorded_at": datetime.now(timezone.utc).isoformat(), "latency_seconds": time.perf_counter() - started,
            "usage": response["usage"], "http_status": 200, "temperature": 0,
            "max_output_tokens": backend.max_output_tokens, "timeout_seconds": backend.timeout}})
    if input_path.read_bytes() != raw:
        raise ValueError("Validated input changed; proposals not published")
    verify_source(input_path, source)
    load_state(input_path, source)
    for kind, path in [("distilbert", defect_diagnostics), ("minilm", similarity_diagnostics)]:
        if path is not None and _hash(path.read_bytes()) != hashes[kind]:
            raise ValueError("Advisory diagnostic changed; proposals not published")
    report = {"schema_version": 1, "prompt_version": PROMPT_VERSION, "provider": "groq",
              "advisory_only": True, "human_review_required": True, "decision_effect": "none",
              "input_sha256": _hash(raw), "source_sha256": manifest["sha256"],
              "document_id": manifest["document_id"], "run_id": artifact["run_id"],
              "diagnostic_sha256": hashes, "limits": {"max_requests": max_requests,
              "max_evidence_chars": max_evidence_chars, "max_context_chars": max_context_chars},
              "proposals": proposals}
    payload = (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".c1-clarifications-pending-", dir=out.parent)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(name, out)
    Path(name).unlink()
    print(f"[c1] wrote {len(proposals)} untrusted clarification proposals to {out}; explicit human actions required")
