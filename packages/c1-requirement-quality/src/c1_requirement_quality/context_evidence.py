"""Read-only, archive-verified context citations for human pair review.

Context never enters the consistency analyser. Only explicit references to both
original document labels select a citation; no semantic applicability is inferred.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re

from c1_requirement_quality.ingest import load_srs_document
from c1_requirement_quality.source_integrity import VerifiedWorkflowContext, _verify_snapshot, sha256


def _local_context(c1_dir, artifact, identity):
    """Check bytes locally; callers verify workflow ancestry separately.

    The local primitive also runs during lineage loading, so it must not recurse
    through the public workflow verifier. Re-ingestion is deterministic, not ML.
    """
    name = artifact["source_document"]["name"]
    if Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("Invalid contextual source filename")
    internal = Path(c1_dir) / "internal"
    archive = internal / "source" / name
    raw = archive.read_bytes()
    normalized = (internal / "normalized_ingestion.json").read_bytes()
    if sha256(raw) != identity["sha256"] or sha256(normalized) != identity["normalized_sha256"]:
        raise ValueError("Context source or normalized provenance hash mismatch")
    payload = json.loads(normalized)
    # Stage B supports physical DOCX paragraph citations only. Other source
    # layouts remain available through existing original-requirement evidence.
    if payload.get("format") != "docx":
        return {}, {}
    doc = load_srs_document(archive)
    if (payload.get("context_items") != [asdict(item) for item in doc.context_items]
            or payload.get("requirements") != [asdict(item) for item in doc.requirements]
            or payload.get("source_blocks") != doc.source_blocks or payload.get("raw_text") != doc.raw_text):
        raise ValueError("Context identity/provenance does not match archived source ingestion")
    blocks = {b["paragraph"]: b for b in doc.source_blocks if b["kind"] == "paragraph"}
    contexts = {}
    for item in doc.context_items:
        block = blocks.get(item.line)
        if item.table_id or not block or item.raw_text not in block["text"]:
            continue
        label = item.doc_item_number
        if label in contexts:
            raise ValueError("Ambiguous contextual document label")
        quote = block["text"]
        if not re.match(r"^" + re.escape(label) + r"(?:[.:)]|\s)", quote):
            continue
        contexts[label] = {"kind": "verified_source_context", "text": quote,
            "doc_item_number": label, "source": item.to_source_dict(),
            "section_hierarchy": item.section_hierarchy,
            "provenance": {**identity, "paragraph": item.line,
                "source_block_sha256": sha256(quote.encode("utf-8")),
                "context_record_sha256": sha256(json.dumps(asdict(item), sort_keys=True, ensure_ascii=False).encode("utf-8"))},
            "decision_effect": "human_review_context_only"}
    labels = {}
    for row in artifact["requirements"]:
        matching = [r for r in doc.requirements if r.raw_text == row["original_text"] and r.to_source_dict() == row["source"]]
        if len(matching) == 1:
            labels[row["requirement_id"]] = matching[0].doc_item_number
    if archive.read_bytes() != raw or (internal / "normalized_ingestion.json").read_bytes() != normalized:
        raise ValueError("Context source changed during verification")
    return contexts, labels


def _for_pair(contexts, labels, ids):
    if any(rid not in labels for rid in ids) or len({labels[rid] for rid in ids}) != 2:
        return {}
    return {"CONTEXT:" + label: item for label, item in contexts.items()
            if all(re.search(r"(?<![\w-])" + re.escape(labels[rid]) + r"(?![\w-])", item["text"]) for rid in ids)}


def verified_pair_context(context, rows, identity):
    if not isinstance(context, VerifiedWorkflowContext):
        raise ValueError("Verified workflow context required for source context citations")
    _, manifest, artifact, _ = _verify_snapshot(context.input_path, context.source)
    expected = {k: manifest[k] for k in ("document_id", "sha256", "normalized_sha256")}
    if identity != expected:
        raise ValueError("Context belongs to another source identity")
    original = {r["requirement_id"]: r for r in artifact["requirements"]}
    if any(r["requirement_id"] not in original or any(r[k] != original[r["requirement_id"]][k]
           for k in ("original_text", "source")) for r in rows):
        raise ValueError("Context requirement source binding mismatch")
    contexts, labels = _local_context(context.input_path.parent, artifact, expected)
    return lambda ids: _for_pair(contexts, labels, ids)


def validate_context_reviews(c1_dir, artifact, identity, reviews):
    selected = [r for r in reviews if any(k.startswith("CONTEXT:") or v.get("kind") == "verified_source_context"
                                         for k, v in r.get("evidence", {}).items())]
    if not selected:
        return
    contexts, labels = _local_context(c1_dir, artifact, identity)
    for review in selected:
        expected = _for_pair(contexts, labels, review["requirement_ids"])
        for ref, evidence in review["evidence"].items():
            if ref.startswith("CONTEXT:") or evidence.get("kind") == "verified_source_context":
                if ref not in expected or evidence != expected[ref] or ref not in review["evidence_refs"]:
                    raise ValueError("Context citation identity/provenance mismatch")
