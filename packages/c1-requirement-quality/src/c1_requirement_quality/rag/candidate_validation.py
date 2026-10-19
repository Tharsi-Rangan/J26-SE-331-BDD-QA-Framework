"""Source-bound candidate evidence validation; never publishes refinement decisions."""
from __future__ import annotations

import json
import os
import tempfile
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from c1_requirement_quality.contract import validate_contract_artifact
from c1_requirement_quality.lexical_patterns import PLACEHOLDER_PATTERN
from c1_requirement_quality.ml.ml_diagnostics import _require_memory
from c1_requirement_quality.refinement import stable_candidate_id
from c1_requirement_quality.source_integrity import sha256, verify_source, VerifiedWorkflowContext, _verify_snapshot
from c1_requirement_quality.workflow_persistence import load_state
from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser

POLICY = "c1-candidate-rag-v1"


def verification_policy() -> dict[str, Any]:
    """Explicit semantic versions, not detection of arbitrary source-code edits.

    Bump the affected version whenever its verification semantics change. Model
    assets and retrieval top_k are separately checked by the existing loader.
    """
    configuration = {
        "symbolic": "obligation-and-numeric-interval-v1",
        "applicability": "explicit-obligation-signature-v1",
        "fact_extraction": "rule-based-no-spacy-v1",
        "placeholders": "incomplete-facts-never-supported-v1",
        "passage_aggregation": "error-contradiction-support-v1",
        "claim_aggregation": "every-claim-attributed-and-supported-v1",
        "meaning": "c1-conservative-meaning-v1",
        "nli": {"score": "finite-real-required-v1", "truncation": True,
                "label_mapping": "contradiction-entailment-neutral-v1",
                "confidence_threshold": None},
        "retrieval": "dense-srs-chunks-v1",
    }
    return {"version": 1, "configuration": configuration,
            "sha256": sha256(_canonical(configuration))}


def compare_meaning(original: str, candidate: str) -> dict[str, Any]:
    """Conservative obligation comparison, not a semantic-equivalence model.

    Only whitespace and terminal full stops are normalized. Changed wording,
    reordered clauses and human-supplied facts require further review, even when
    retrieved source evidence independently supports them.
    """
    from c1_requirement_quality.rag.fact_extractor import extract_facts
    before = extract_facts(original, use_spacy=False)
    after = extract_facts(candidate, use_spacy=False)
    normalize = lambda text: " ".join(text.rstrip(".").split())
    old = [normalize(f.text) for f in before]
    new = [normalize(f.text) for f in after]
    differences = {}
    def value(fact, attribute):
        # The existing extractor can include the first object word in action.
        # Preserve a literal predicate/remainder comparison without inferring roles.
        match = re.search(r"\b(?:shall|must|may|can|could|should|might|will|would)\s+(?:not\s+)?(\w+)\s*(.*)", fact.text, re.I)
        if match and attribute in {"action", "target"}:
            return normalize(match.group(1 if attribute == "action" else 2))
        return getattr(fact, attribute)
    for attribute in ("actor", "action", "target", "is_negated", "numeric_values", "units", "conditions", "constraints"):
        left = [value(f, attribute) for f in before]
        right = [value(f, attribute) for f in after]
        if left != right:
            differences[attribute] = {"original": [f.to_dict() for f in before],
                                      "candidate": [f.to_dict() for f in after]}
    modals = lambda text: re.findall(r"\b(?:shall|must|may|can|could|should|might|will|would)\b", text, re.I)
    if modals(original) != modals(candidate):
        differences["modality"] = {"original": modals(original), "candidate": modals(candidate)}
    return {"policy": "c1-conservative-meaning-v1",
            "status": "preserved" if old and old == new else "changed_or_unproven",
            "removed_or_changed_obligations": list((Counter(old) - Counter(new)).elements()),
            "added_or_changed_obligations": list((Counter(new) - Counter(old)).elements()),
            "differences": differences}


@dataclass(frozen=True)
class CandidateGroundingContext(VerifiedWorkflowContext):
    """Trusted caller-supplied receipts; never obtain digests from proposal JSON."""

    receipts: dict[str, tuple[Path, str]] = field(default_factory=dict)
    top_k: int = 5
    analyser_factory: Callable[..., Any] = RAGGroundingAnalyser

    def check_parent(self, artifact: dict[str, Any]) -> None:
        _, _, authenticated, _ = _verify_snapshot(self.input_path, self.source)
        validate_contract_artifact(authenticated)
        if _canonical(artifact) != _canonical(authenticated):
            raise ValueError("Candidate grounding context belongs to a different parent artifact")

    def assess(self, requirement_id: str, candidate: str, srs_text: str,
               original: str | None, workflow_record: dict[str, Any] | None) -> dict[str, Any]:
        """Verify fresh evidence and meaning; do not infer, rank or publish decisions."""
        meaning = {"status": "unassessed"}
        try:
            text, binding, row, state = _candidate_snapshot(
                self.input_path, self.source, requirement_id, candidate, self.top_k)
            if (text != srs_text or row["original_text"] != original
                    or workflow_record is not None and workflow_record != state["requirements"][requirement_id]):
                raise ValueError("Candidate evaluation source, original text or workflow basis mismatch")
            meaning = compare_meaning(row["original_text"], candidate)
            reference = self.receipts.get(binding["candidate_id"])
            if reference is None:
                raise ValueError("Mandatory candidate RAG evidence receipt missing")
            path, digest = reference
            record = load_candidate_validation(path, self.input_path, self.source,
                requirement_id, candidate, expected_sha256=digest, top_k=self.top_k,
                analyser_factory=self.analyser_factory)
            if record["binding"] != binding:
                raise ValueError("Candidate evaluation context changed while loading evidence")
            result = dict(record["grounding"])
            verdict = record["verdict"]
            result.update(authority="rag", verdict=verdict,
                original_srs_status=result.get("status", "unsupported"),
                status="supported" if verdict == "SUPPORTED" else "unsupported",
                meaning_preservation=meaning,
                eligible_for_acceptance=(verdict == "SUPPORTED" and record["completion_status"] == "completed"
                                         and meaning["status"] == "preserved"),
                validation_receipt_sha256=digest, validation_binding=record["binding"],
                models=record["models"], completion_status=record["completion_status"])
            return result
        except (ValueError, OSError, RuntimeError, KeyError, TypeError, AttributeError) as error:
            return {"authority": "rag", "status": "unsupported", "verdict": "ERROR",
                    "evidence": [], "diagnostics": [], "errors": [f"{type(error).__name__}: {error}"],
                    "meaning_preservation": meaning,
                    "eligible_for_acceptance": False, "completion_status": "incomplete"}


def context_for_snapshot(input_path: Path, source: Path, supplied=None) -> CandidateGroundingContext:
    if supplied is not None:
        if supplied.input_path.resolve() != input_path.resolve() or supplied.source.resolve() != source.resolve():
            raise ValueError("Candidate grounding context belongs to a different snapshot/source")
        return supplied
    return CandidateGroundingContext(input_path, source)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _context(input_path: Path, source: Path, requirement_id: str,
             candidate_text: str, top_k: int) -> tuple[str, dict[str, Any]]:
    text, binding, _, _ = _candidate_snapshot(input_path, source, requirement_id, candidate_text, top_k)
    return text, binding


def _candidate_snapshot(input_path: Path, source: Path, requirement_id: str,
                        candidate_text: str, top_k: int):
    """Bind candidate facts and identity to one authenticated parsed snapshot."""
    if not isinstance(candidate_text, str) or not candidate_text.strip():
        raise ValueError("Candidate text must be nonempty")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
        raise ValueError("top_k must be a positive integer")
    text, manifest, artifact, state = _verify_snapshot(input_path, source)
    validate_contract_artifact(artifact)
    rows = [r for r in artifact["requirements"] if r["requirement_id"] == requirement_id]
    if len(rows) != 1:
        raise ValueError("Requirement ID must identify exactly one source requirement")
    return text, {
        "requirement_id": requirement_id,
        "original_text_sha256": sha256(rows[0]["original_text"].encode("utf-8")),
        "candidate_id": stable_candidate_id(requirement_id, candidate_text),
        "candidate_text_sha256": sha256(candidate_text.encode("utf-8")),
        "parent_artifact_sha256": manifest["artifact_sha256"], "snapshot_id": state["snapshot_id"],
        "source_manifest_sha256": sha256(_canonical(manifest)),
        "document_id": manifest["document_id"], "source_sha256": manifest["sha256"],
        "normalized_sha256": manifest["normalized_sha256"],
        "workflow_sha256": manifest.get("workflow_sha256"),
        "workflow_basis_sha256": sha256(_canonical(state)),
        "policy": POLICY, "retrieval": {"top_k": top_k, "use_spacy": False},
        "verification_policy": verification_policy(),
    }, rows[0], state


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
