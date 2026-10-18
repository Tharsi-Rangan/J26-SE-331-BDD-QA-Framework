"""Source-bound candidate evidence validation; never publishes refinement decisions."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from c1_requirement_quality.contract import validate_contract_artifact
from c1_requirement_quality.lexical_patterns import PLACEHOLDER_PATTERN
from c1_requirement_quality.ml.ml_diagnostics import _require_memory
from c1_requirement_quality.refinement import stable_candidate_id
from c1_requirement_quality.source_integrity import sha256, verify_source
from c1_requirement_quality.workflow_persistence import load_state
from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser

POLICY = "c1-candidate-rag-v1"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _context(input_path: Path, source: Path, requirement_id: str,
             candidate_text: str, top_k: int) -> tuple[str, dict[str, Any]]:
    if not isinstance(candidate_text, str) or not candidate_text.strip():
        raise ValueError("Candidate text must be nonempty")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
        raise ValueError("top_k must be a positive integer")
    raw = input_path.read_bytes()
    artifact = json.loads(raw.decode("utf-8-sig"))
    validate_contract_artifact(artifact)
    text, manifest = verify_source(input_path, source)
    state, _ = load_state(input_path, source)
    rows = [r for r in artifact["requirements"] if r["requirement_id"] == requirement_id]
    if len(rows) != 1:
        raise ValueError("Requirement ID must identify exactly one source requirement")
    if input_path.read_bytes() != raw:
        raise ValueError("Parent artifact changed during context validation")
    return text, {
        "requirement_id": requirement_id,
        "original_text_sha256": sha256(rows[0]["original_text"].encode("utf-8")),
        "candidate_id": stable_candidate_id(requirement_id, candidate_text),
        "candidate_text_sha256": sha256(candidate_text.encode("utf-8")),
        "parent_artifact_sha256": sha256(raw), "snapshot_id": state["snapshot_id"],
        "source_manifest_sha256": sha256(_canonical(manifest)),
        "document_id": manifest["document_id"], "source_sha256": manifest["sha256"],
        "normalized_sha256": manifest["normalized_sha256"],
        "workflow_sha256": manifest.get("workflow_sha256"),
        "workflow_basis_sha256": sha256(_canonical(state)),
        "policy": POLICY, "retrieval": {"top_k": top_k, "use_spacy": False},
    }


def _verdict(result: dict[str, Any]) -> str:
    diagnostics = result.get("diagnostics", [])
    outcomes = [d.get("outcome") for d in diagnostics]
    if result.get("errors") or any(o not in {
        "SUPPORTED", "CONTRADICTED", "INCONCLUSIVE", "ERROR"} for o in outcomes):
        return "ERROR"
    if "ERROR" in outcomes:
        return "ERROR"
    if "CONTRADICTED" in outcomes:
        return "CONTRADICTED"
    if not outcomes or "INCONCLUSIVE" in outcomes:
        return "INCONCLUSIVE"
    # Support must include an attributable passage for every extracted claim.
    for diagnostic in diagnostics:
        if not diagnostic.get("fact", {}).get("text") or not any(
            e.get("outcome") == "SUPPORTED" for e in diagnostic.get("evidence_outcomes", [])
        ):
            return "INCONCLUSIVE"
    return "SUPPORTED"


def validate_candidate_run(input_path: Path, source: Path, requirement_id: str,
                           candidate_text: str, out: Path, *, top_k: int = 5,
                           analyser_factory: Callable[..., Any] = RAGGroundingAnalyser) -> str:
    """Publish evidence only and return its SHA256 receipt for trusted retention.

    The factory is an injection seam for offline tests. Production uses the
    existing local-only analyser. Preflight/integrity failures raise without
    publication; inference failures may publish an explicitly incomplete record.
    """
    if out.exists():
        raise FileExistsError(out)
    text, binding = _context(input_path, source, requirement_id, candidate_text, top_k)
    _require_memory()
    analyser = analyser_factory(text, top_k=top_k, use_spacy=False)
    try:
        models = analyser.model_provenance()
        _require_memory()
        try:
            result = analyser.analyse(candidate_text)
        except Exception as error:
            result = {"diagnostics": [], "evidence": [],
                      "errors": [f"{type(error).__name__}: {error}"]}
        if analyser.model_provenance() != models:
            raise ValueError("Model provenance changed during candidate validation")
        verdict = _verdict(result)
        if PLACEHOLDER_PATTERN.search(candidate_text) and verdict == "SUPPORTED":
            verdict = "INCONCLUSIVE"
        record = {"validation_version": 1, "binding": binding,
                  "candidate_text": candidate_text, "models": models,
                  "loaded_models": list(analyser.loaded_model_names),
                  "verdict": verdict,
                  "completion_status": "incomplete" if verdict == "ERROR" else "completed",
                  "scope": "source evidence only; not meaning preservation, approval or BDD readiness",
                  "grounding": result}
    finally:
        analyser.release()
    if _context(input_path, source, requirement_id, candidate_text, top_k)[1] != binding:
        raise ValueError("Candidate validation context changed; no sidecar published")
    encoded = _canonical(record) + b"\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".c1-candidate-validation-pending-", dir=out.parent)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(name, out)  # Exclusive publication; never replace another run.
    Path(name).unlink()
    return sha256(encoded)


def load_candidate_validation(path: Path, input_path: Path, source: Path,
                              requirement_id: str, candidate_text: str, *,
                              expected_sha256: str, top_k: int = 5,
                              analyser_factory: Callable[..., Any] = RAGGroundingAnalyser) -> dict[str, Any]:
    """Verify a separately retained receipt and current bindings without inference.

    A self-hash is not authentication. Callers must retain the returned publication
    receipt in trusted state; reading a digest from the sidecar itself is unsafe.
    This API does not authorize approval, even for a supported record.
    """
    raw = path.read_bytes()
    if sha256(raw) != expected_sha256:
        raise ValueError("Candidate validation receipt mismatch")
    record = json.loads(raw.decode("utf-8"))
    text, binding = _context(input_path, source, requirement_id, candidate_text, top_k)
    if (record.get("validation_version") != 1 or record.get("binding") != binding
            or record.get("candidate_text") != candidate_text):
        raise ValueError("Candidate validation binding mismatch")
    analyser = analyser_factory(text, top_k=top_k, use_spacy=False)
    try:
        if record.get("models") != analyser.model_provenance():
            raise ValueError("Candidate validation model provenance mismatch")
    finally:
        analyser.release()
    if _context(input_path, source, requirement_id, candidate_text, top_k)[1] != binding:
        raise ValueError("Candidate validation context changed while loading")
    verdict = _verdict(record["grounding"])
    if PLACEHOLDER_PATTERN.search(candidate_text) and verdict == "SUPPORTED":
        verdict = "INCONCLUSIVE"
    if (record.get("verdict") != verdict or record.get("completion_status") !=
            ("incomplete" if verdict == "ERROR" else "completed")):
        raise ValueError("Candidate validation verdict mismatch")
    return record
