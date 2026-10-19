"""Optional MiniLM CLI sidecars; no deterministic or applicability policy effect."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from c1_requirement_quality.ml.ml_diagnostics import available_memory_bytes
from c1_requirement_quality.rag.retriever import DEFAULT_MODEL_NAME, SentenceTransformersEmbedder
from c1_requirement_quality.ml.requirement_similarity import requirement_pair_diagnostics

from c1_requirement_quality.model_paths import get_minilm_cache_dir, MINILM_CACHED_REVISION

CACHED_REVISION = MINILM_CACHED_REVISION
MIN_AVAILABLE_BYTES = 3 * 1024 ** 3


def default_model_directory() -> Path:
    """Select the known cached snapshot explicitly, without hub resolution/network."""
    return get_minilm_cache_dir()


def checkpoint_provenance(directory: Path) -> dict[str, Any]:
    required = ["modules.json", "config.json", "sentence_bert_config.json",
                "tokenizer_config.json", "tokenizer.json", "1_Pooling/config.json"]
    weight = "model.safetensors" if (directory / "model.safetensors").is_file() else "pytorch_model.bin"
    for name in [*required, weight]:
        if not (directory / name).is_file():
            raise FileNotFoundError(f"MiniLM checkpoint incomplete: missing {name} in {directory}. Cache it separately; no download attempted.")
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    if config.get("model_type") != "bert" or config.get("hidden_size") != 384 or config.get("num_hidden_layers") != 6:
        raise ValueError("Expected all-MiniLM-L6-v2 BERT architecture (6 layers, width 384)")
    hashes = {}
    optional = [name for name in ("config_sentence_transformers.json", "special_tokens_map.json", "vocab.txt") if (directory / name).is_file()]
    for name in [*required, *optional, weight]:
        with (directory / name).open("rb") as stream:
            hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    cached = directory.name == CACHED_REVISION and directory.parent.name == "snapshots" and directory.parent.parent.name == "models--sentence-transformers--all-MiniLM-L6-v2"
    return {"identifier": DEFAULT_MODEL_NAME, "local_directory": str(directory.resolve()),
            "cache_revision": CACHED_REVISION if cached else None,
            "revision_basis": "local snapshot directory name" if cached else "custom local directory; revision unknown",
            "asset_sha256": hashes, "device": "cpu", "local_files_only": True,
            "identity_note": "Local asset hashes recorded; not independently authenticated against a remote checkpoint"}


def similarity_diagnostics_run(input_path: Path, out: Path, *, model_dir: Path | None = None,
                               threshold: float | None = None, batch_size: int = 4,
                               max_pairs: int = 10_000) -> None:
    from c1_requirement_quality.contract import validate_contract_artifact as _validate_contract_artifact
    if out.exists():
        raise FileExistsError(f"Diagnostic output already exists: {out}")
    raw = input_path.read_bytes()
    artifact = json.loads(raw.decode("utf-8-sig"))
    _validate_contract_artifact(artifact)
    # Reuse the existing component's exact validation before any model/cache access.
    requirement_pair_diagnostics([], threshold=threshold, batch_size=batch_size, max_pairs=max_pairs)
    rows = artifact["requirements"]
    ids = [r["requirement_id"] for r in rows]
    if len(ids) != len(set(ids)) or any(not r["original_text"].strip() for r in rows):
        raise ValueError("Similarity input requires unique IDs and nonempty original texts")
    pair_count = len(rows) * (len(rows) - 1) // 2
    if pair_count > max_pairs:
        raise ValueError("pair count exceeds max_pairs; no model loaded")
    available = available_memory_bytes()
    if available < MIN_AVAILABLE_BYTES:
        raise RuntimeError(f"Insufficient available RAM ({available / 1024 ** 3:.2f} GiB); at least 3 GiB required. No diagnostic published.")
    directory = model_dir if model_dir is not None else default_model_directory()
    provenance = checkpoint_provenance(directory)
    embedder = SentenceTransformersEmbedder(model_name=str(directory.resolve()))
    try:
        report = requirement_pair_diagnostics(rows, embedder=embedder, threshold=threshold,
                                             batch_size=batch_size, max_pairs=max_pairs)
    except MemoryError:
        raise RuntimeError("Insufficient memory during MiniLM inference; no diagnostic published") from None
    if len(report["pairs"]) != pair_count:
        raise ValueError("Incomplete pair diagnostics; no output published")
    if input_path.read_bytes() != raw:
        raise RuntimeError("Validated input changed during diagnostics; no output published")
    if checkpoint_provenance(directory) != provenance:
        raise RuntimeError("MiniLM checkpoint changed during diagnostics; no output published")
    report.update(decision_effect="none", input_sha256=hashlib.sha256(raw).hexdigest(),
                  run_id=artifact["run_id"], source_document=copy.deepcopy(artifact["source_document"]),
                  model=provenance, available_ram_before_bytes=available, batch_size=batch_size,
                  max_pairs=max_pairs,
                  interpretation="Semantic similarity only: not proof of duplication, contradiction, logical consistency or pair applicability")
    for pair in report["pairs"]:
        pair["selected_candidate"] = pair["possible_duplicate"]
    report["selected_candidate_pairs"] = [copy.deepcopy(pair) for pair in report["pairs"] if pair["selected_candidate"] is True]
    encoded = (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".c1-similarity-pending-", dir=out.parent)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(name, out)
    Path(name).unlink()
    print(f"[c1] wrote {pair_count} experimental similarity pairs to {out}; no C1 decisions changed")
