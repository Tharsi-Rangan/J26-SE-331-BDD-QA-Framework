"""Internal advisory requirement-pair diagnostics; never changes C1 decisions.

Scores reuse retrieval's cosine clipped to [0, 1], without display rounding.
They are not probabilities or proof of equivalence. Thresholds are experimental.
"""
from __future__ import annotations

import math
from numbers import Real
from typing import Any

from c1_requirement_quality.rag.retriever import SentenceTransformersEmbedder, cosine_similarity

_cosine_similarity = cosine_similarity


def requirement_pair_diagnostics(
    requirements: list[dict[str, Any]], *, embedder: Any | None = None,
    threshold: float | None = None, batch_size: int = 8, max_pairs: int = 10_000,
) -> dict[str, Any]:
    """Compare original requirement texts without mutating records or merging IDs.

    A missing threshold yields null flags. At a supplied cutoff, equality flags
    a possible duplicate for human review. Pair count is bounded before encoding.
    Injected encoders may use any consistent nonzero embedding dimension.
    """
    for name, value in (("batch_size", batch_size), ("max_pairs", max_pairs)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if threshold is not None:
        if isinstance(threshold, bool) or not isinstance(threshold, Real):
            raise TypeError("threshold must be a real number or None")
        threshold = float(threshold)
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("threshold must be finite and between 0 and 1")
    if not isinstance(requirements, list):
        raise TypeError("requirements must be a list")
    rows, seen = [], set()
    for row in requirements:
        if not isinstance(row, dict):
            raise ValueError("each requirement must be an object")
        rid, text = row.get("requirement_id"), row.get("original_text")
        if not isinstance(rid, str) or not rid.strip() or rid in seen:
            raise ValueError("requirement IDs must be non-empty and unique")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("original_text must be a non-empty string")
        seen.add(rid)
        rows.append({"requirement_id": rid, "original_text": text})
    rows.sort(key=lambda row: row["requirement_id"])
    if len(rows) * (len(rows) - 1) // 2 > max_pairs:
        raise ValueError("pair count exceeds max_pairs; partition the input explicitly")
    encoder = embedder if embedder is not None else SentenceTransformersEmbedder()
    builtin = isinstance(encoder, SentenceTransformersEmbedder)
    vectors, metadata = [], []
    # No comparisons means no reason to load a model.
    if len(rows) >= 2:
        for offset in range(0, len(rows), batch_size):
            texts = [row["original_text"] for row in rows[offset:offset + batch_size]]
            if builtin:
                result = encoder.encode_with_diagnostics(texts, batch_size=batch_size)
                batch, info = result["embeddings"], result["diagnostics"]
            else:
                batch = encoder.encode(texts)
                info = [{"input_tokens": None, "token_limit": None, "truncated": None} for _ in texts]
            if len(batch) != len(texts) or len(info) != len(texts):
                raise ValueError("embedding/diagnostic count must match input count")
            vectors.extend(batch)
            metadata.extend(info)
    dimension = None
    normalized = []
    for vector in vectors:
        if not isinstance(vector, (list, tuple)) or not vector:
            raise ValueError("embedding must be a non-empty vector")
        if any(isinstance(x, bool) or not isinstance(x, Real) or not math.isfinite(x) for x in vector):
            raise ValueError("embedding values must be finite real numbers")
        if dimension is None:
            dimension = len(vector)
        if len(vector) != dimension:
            raise ValueError("embedding dimensions must match across all batches")
        scale = max(abs(x) for x in vector)
        if scale == 0:
            raise ValueError("zero-norm embeddings cannot establish similarity")
        # Scaling avoids overflow/underflow while preserving cosine direction.
        scaled = [x / scale for x in vector]
        norm = math.sqrt(sum(x * x for x in scaled))
        normalized.append([x / norm for x in scaled])
    pairs = []
    for i in range(len(normalized)):
        for j in range(i + 1, len(normalized)):
            score = cosine_similarity(normalized[i], normalized[j])
            pairs.append({"requirement_ids": [rows[i]["requirement_id"], rows[j]["requirement_id"]],
                          "similarity": score,
                          "possible_duplicate": score >= threshold if threshold is not None else None})
    for i, row in enumerate(rows):
        row["embedding_diagnostics"] = metadata[i] if metadata else {
            "input_tokens": None, "token_limit": None, "truncated": None}
    return {"diagnostic_version": 1, "status": "experimental", "advisory_only": True,
            "human_review_required": True, "threshold": threshold,
            "threshold_policy": "experimental; similarity >= threshold; null when unset",
            "score_definition": "cosine clipped to [0, 1]; not a probability",
            "embedding_source": "local_sentence_transformers" if builtin else "injected",
            "requested_model": encoder.model_name if builtin else None,
            "loaded_model": encoder.loaded_model_name if builtin else None,
            "embedding_dimension": dimension, "requirements": rows, "pairs": pairs}
