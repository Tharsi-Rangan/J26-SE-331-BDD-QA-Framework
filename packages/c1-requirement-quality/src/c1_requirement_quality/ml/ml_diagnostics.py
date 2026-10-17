"""Opt-in local DistilBERT diagnostics, isolated from deterministic C1 decisions."""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from c1_requirement_quality.ml.ml_defect_classifier import (
    DEFAULT_MODEL_DIR, EXPERIMENT2_LABELS, EXPERIMENT2_PROVENANCE,
    DistilBertDefectClassifier,
)

MIN_AVAILABLE_BYTES = 3 * 1024 ** 3


def available_memory_bytes() -> int:
    """Read available physical memory without importing model libraries."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                (name, ctypes.c_ulonglong) for name in
                ("total_physical", "available_physical", "total_page", "available_page",
                 "total_virtual", "available_virtual", "available_extended")]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise RuntimeError("Cannot determine available RAM; model loading refused")
        return int(status.available_physical)
    if sys.platform.startswith("linux"):
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("Available RAM measurement unsupported; model loading refused")


def _require_memory() -> int:
    available = available_memory_bytes()
    if available < MIN_AVAILABLE_BYTES:
        raise RuntimeError(f"Insufficient available RAM ({available / 1024 ** 3:.2f} GiB); at least 3 GiB required. No diagnostic published.")
    return available


def defect_diagnostics_run(input_path: Path, out: Path, *, model_dir: Path | None = None,
                           threshold: float | None = None) -> None:
    """Validate input, invoke the existing adapter, and exclusively publish a sidecar."""
    from c1_requirement_quality.contract import validate_contract_artifact as _validate_contract_artifact
    if out.exists():
        raise FileExistsError(f"Diagnostic output already exists: {out}")
    raw = input_path.read_bytes()
    artifact = json.loads(raw.decode("utf-8-sig"))
    _validate_contract_artifact(artifact)
    rows = artifact["requirements"]
    ids = [r["requirement_id"] for r in rows]
    if len(ids) != len(set(ids)) or any(not r["original_text"].strip() for r in rows):
        raise ValueError("Diagnostic input requires unique IDs and nonempty original text")
    # Constructor validates cutoff without loading weights. Explicit mapping requests
    # make the existing adapter fail closed for an unknown/altered checkpoint.
    classifier = DistilBertDefectClassifier(model_dir=model_dir or DEFAULT_MODEL_DIR,
        threshold=threshold, semantic_labels=EXPERIMENT2_LABELS,
        mapping_provenance=EXPERIMENT2_PROVENANCE)
    available = _require_memory()
    checkpoint = classifier.validate_checkpoint()
    if checkpoint["mapping_status"] != "VERIFIED":
        raise ValueError("Verified Experiment 2 checkpoint required for named diagnostics")
    results = []
    try:
        for row in rows:
            _require_memory()
            result = classifier.classify(row["original_text"], requirement_id=row["requirement_id"]).to_dict()
            if (result["mapping_status"] != "VERIFIED"
                    or result["checkpoint_sha256"] != checkpoint["checkpoint_sha256"]
                    or result["requirement_id"] != row["requirement_id"] or result["text"] != row["original_text"]
                    or set(result["scores"]) != set(EXPERIMENT2_LABELS)
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1
                           for v in result["scores"].values())):
                raise ValueError("Adapter returned inconsistent identity or scores; no diagnostic published")
            result.update(status="experimental", advisory_only=True, human_review_required=True)
            results.append(result)
    except MemoryError:
        raise RuntimeError("Insufficient memory during DistilBERT inference; no diagnostic published") from None
    if classifier.validate_checkpoint() != checkpoint:
        raise RuntimeError("Checkpoint changed during diagnostics; no output published")
    if input_path.read_bytes() != raw:
        raise RuntimeError("Input changed during diagnostics; no output published")
    payload: dict[str, Any] = {
        "diagnostic_version": 1, "status": "experimental", "advisory_only": True,
        "human_review_required": True, "decision_effect": "none",
        "input_sha256": hashlib.sha256(raw).hexdigest(), "run_id": artifact["run_id"],
        "model": {"identifier": classifier.model_name, "checkpoint": checkpoint,
                  "label_order": list(EXPERIMENT2_LABELS), "training_max_tokens": 128},
        "threshold": threshold, "threshold_policy": "experimental score >= cutoff; no predictions when unset",
        "score_interpretation": "Independent sigmoid scores; not calibrated confidence or validated accuracy",
        "available_ram_before_bytes": available, "inference_batch_size": 1,
        "requirements": results,
    }
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".c1-ml-diagnostic-pending-", dir=out.parent)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(name, out)  # exclusive; cannot overwrite a racing writer
    Path(name).unlink()
    print(f"[c1] wrote {len(results)} experimental advisory diagnostics to {out}; no C1 decisions changed")
