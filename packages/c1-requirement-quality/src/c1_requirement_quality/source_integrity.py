"""Local source snapshots and integrity verification; no shared contract fields."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace, dataclass, field
from pathlib import Path
from typing import Any

from c1_requirement_quality.ingest import load_srs_document
from c1_requirement_quality.ingest.models import NIRDocument


@dataclass(frozen=True)
class VerifiedWorkflowContext:
    """Paths to reverified local provenance, never a caller-selected policy flag."""
    input_path: Path
    source: Path
    source_scope: str | None = field(default=None, kw_only=True)

    def scoped(self, text: str):
        return VerifiedWorkflowContext(self.input_path, self.source, source_scope=text)


def resolve_workflow_policy(context, *, artifact=None, source_text=None):
    """Resolve policy only from sealed source/workflow provenance on every call."""
    if not isinstance(context, VerifiedWorkflowContext):
        raise ValueError("Verified workflow context required; provenance is unknown")
    text, manifest = verify_source(context.input_path, context.source)
    from c1_requirement_quality.workflow_persistence import load_state
    from c1_requirement_quality.contract import validate_contract_artifact
    state, current_manifest = load_state(context.input_path, context.source)
    current = json.loads(context.input_path.read_text(encoding="utf-8-sig"))
    validate_contract_artifact(current)
    if current_manifest != manifest or (artifact is not None and artifact != current):
        raise ValueError("Workflow provenance or parent artifact mismatch")
    rag = "rag_policy" in manifest
    if not rag and any((context.input_path.parent / name).exists() for name in
                       ("rag_diagnostics.json", "internal/rag_provenance.json")):
        raise ValueError("RAG provenance exists without its mandatory manifest policy")
    if context.source_scope is not None:
        if rag or any(line.strip() not in text for line in context.source_scope.splitlines() if line.strip()):
            raise ValueError("Unverified evidence scope")
        text = context.source_scope
    if source_text is not None and source_text != text:
        raise ValueError("Evaluation source does not match verified workflow source")
    return rag, text, manifest, state


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def document_identity(source: Path, explicit: str | None = None) -> str:
    """Logical identity survives edits; explicit IDs also survive path moves."""
    if explicit is not None:
        if not explicit.strip():
            raise ValueError("document_id must be non-empty")
        return explicit
    return "DOC-" + sha256(str(source.resolve()).casefold().encode("utf-8"))


def snapshot_source(c1_dir: Path, source: Path, document_id: str, *, stage_progress=None) -> tuple[NIRDocument, dict[str, Any]]:
    """Read original bytes once, then ingest the immutable local snapshot."""
    if stage_progress: stage_progress("read", "running", "")
    raw = source.read_bytes()
    archived = c1_dir / "internal" / "source" / source.name
    archived.parent.mkdir(parents=True, exist_ok=True)
    with archived.open("xb") as stream:
        stream.write(raw)
    archived.chmod(0o444)
    if stage_progress:
        stage_progress("read", "completed", "Source bytes archived")
        stage_progress("extract", "running", "")
    doc = replace(load_srs_document(archived), source_path=source.resolve())
    payload = asdict(doc)
    payload["source_path"] = str(doc.source_path)
    # Grounding uses exactly this full text, also for unsupported text extensions.
    normalized = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    nir = c1_dir / "internal" / "normalized_ingestion.json"
    nir.write_bytes(normalized)
    nir.chmod(0o444)
    manifest = {"manifest_version": 1, "document_id": document_id,
                "original_filename": source.name, "sha256": sha256(raw),
                "format": doc.format, "source_location": str(source.resolve()),
                "archived_source": f"source/{source.name}",
                "normalized_ingestion": "normalized_ingestion.json",
                "normalized_sha256": sha256(normalized)}
    return doc, manifest


def seal_source(c1_dir: Path, manifest: dict[str, Any]) -> None:
    """Bind the source snapshot to this exact validated contract artifact."""
    manifest = dict(manifest, artifact_sha256=sha256((c1_dir / "validated_requirements.json").read_bytes()))
    workflow = c1_dir / "internal" / "workflow_snapshot.json"
    if workflow.exists():
        manifest["workflow_sha256"] = sha256(workflow.read_bytes())
    else:
        manifest.pop("workflow_sha256", None)
    path = c1_dir / "internal" / "source_manifest.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    path.chmod(0o444)


def verify_source(input_path: Path, supplied_source: Path) -> tuple[str, dict[str, Any]]:
    """Fail closed on legacy artifacts, changed supplied bytes or altered archives."""
    internal = input_path.parent / "internal"
    manifest_path = internal / "source_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Source integrity manifest missing; legacy artifacts require an explicitly verified reprocessing run")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    filename = manifest["original_filename"]
    if (manifest.get("manifest_version") != 1 or not isinstance(filename, str)
            or Path(filename).name != filename or "/" in filename or "\\" in filename
            or manifest.get("archived_source") != f"source/{filename}"
            or manifest.get("normalized_ingestion") != "normalized_ingestion.json"):
        raise ValueError("Invalid source integrity manifest")
    if sha256(input_path.read_bytes()) != manifest["artifact_sha256"]:
        raise ValueError("Input artifact hash does not match source integrity manifest")
    archived = internal / "source" / filename
    for path in (archived, supplied_source):
        if sha256(path.read_bytes()) != manifest["sha256"]:
            raise ValueError(f"Original SRS hash mismatch: {path}")
    normalized = (internal / "normalized_ingestion.json").read_bytes()
    if sha256(normalized) != manifest["normalized_sha256"]:
        raise ValueError("Normalized ingestion hash mismatch")
    if "rag_policy" in manifest:
        if manifest["rag_policy"] != "c1-initial-rag-v1":
            raise ValueError("Unsupported RAG grounding policy")
        for relative, key in (("internal/rag_provenance.json", "rag_provenance_sha256"),
                              ("rag_diagnostics.json", "rag_diagnostics_sha256")):
            if sha256((input_path.parent / relative).read_bytes()) != manifest.get(key):
                raise ValueError("RAG provenance or diagnostics hash mismatch")
        provenance = json.loads((internal / "rag_provenance.json").read_text(encoding="utf-8"))
        if (provenance.get("status") != "completed" or provenance.get("policy") != manifest["rag_policy"]
                or provenance.get("input_sha256") != manifest["artifact_sha256"]
                or provenance.get("source_sha256") != manifest["sha256"]
                or provenance.get("normalized_sha256") != manifest["normalized_sha256"]):
            raise ValueError("RAG input/source binding mismatch")
    if "workflow_sha256" in manifest:
        workflow = internal / "workflow_snapshot.json"
        if not workflow.is_file() or sha256(workflow.read_bytes()) != manifest["workflow_sha256"]:
            raise ValueError("Workflow snapshot hash mismatch")
    artifact = json.loads(input_path.read_text(encoding="utf-8-sig"))
    if artifact.get("source_document", {}).get("name") != filename:
        raise ValueError("Artifact source filename does not match its manifest")
    payload = json.loads(normalized.decode("utf-8"))
    return payload["raw_text"], manifest


def require_refinement_grounding(manifest: dict[str, Any]) -> None:
    """Do not downgrade an authoritative initial RAG run to lexical refinement."""
    if manifest.get("rag_policy") == "c1-initial-rag-v1":
        raise ValueError("RAG refinement integration is pending; this initial RAG run is inspection-only. No refinement or approval was published.")


def copy_source_bundle(input_path: Path, c1_dir: Path, manifest: dict[str, Any],
                       workflow_state: dict[str, Any] | None = None) -> None:
    """Carry original bytes/NIR unchanged to the new refinement snapshot."""
    old = input_path.parent / "internal"
    target = c1_dir / "internal"
    (target / "source").mkdir(parents=True)
    for relative in (manifest["archived_source"], manifest["normalized_ingestion"]):
        path = target / relative
        with path.open("xb") as stream:
            stream.write((old / relative).read_bytes())
        path.chmod(0o444)
    if workflow_state is not None:
        from c1_requirement_quality.workflow_persistence import write_state
        write_state(c1_dir, workflow_state)
    seal_source(c1_dir, manifest)
