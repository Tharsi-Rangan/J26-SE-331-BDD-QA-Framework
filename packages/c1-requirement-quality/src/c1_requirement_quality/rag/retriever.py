"""Dense vector retrieval engine for SRS evidence chunks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from c1_requirement_quality.rag.indexer import SRSChunk, SRSIndexer
from c1_requirement_quality.rag.model_loading import RAGModelLoadError

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass(frozen=True)
class RetrievalResult:
    """Candidate evidence chunk retrieved by dense semantic similarity search.

    Note: Similarity scores identify candidate evidence for downstream verification.
    High similarity indicates topical relevance only and does NOT establish factual support.
    """

    chunk_id: str
    text: str
    section: str | None
    similarity: float
    start_line: int
    end_line: int

    def to_dict(self) -> dict[str, object]:
        """Export retrieval result to a contract-compatible evidence item dictionary."""
        res: dict[str, object] = {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "similarity": self.similarity,
        }
        if self.section is not None:
            res["section"] = self.section
        return res


def _cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Compute cosine similarity between two equal-length numeric vectors."""
    if len(vec_a) != len(vec_b):
        raise ValueError("Vector dimensions must match")
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    similarity = dot / (norm_a * norm_b)
    return max(0.0, min(1.0, float(similarity)))


class SentenceTransformersEmbedder:
    """Lazy-loaded wrapper for local sentence-transformers embedding models."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        self.model_name = model_name
        self._model: Any | None = None

    @property
    def loaded_model_name(self) -> str | None:
        """Return the model ID only after local model weights were loaded."""
        return self.model_name if self._model is not None else None

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as err:
                raise RAGModelLoadError("embedding", self.model_name, err) from err
            # RAG is local-only: never fetch weights during a run.
            try:
                self._model = SentenceTransformer(
                    self.model_name, local_files_only=True, device="cpu"
                )
            except Exception as err:
                raise RAGModelLoadError("embedding", self.model_name, err) from err
        return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode a list of text strings into dense vector embeddings."""
        if not texts:
            return []
        model = self._load_model()
        embeddings = model.encode(texts, convert_to_numpy=True)
        return [list(map(float, vec)) for vec in embeddings]


class DenseRetriever:
    """Dense vector retriever over SRSIndexer chunks.

    Retrieval finds candidate evidence chunks based on semantic similarity.
    Fact verification (entailment/contradiction) is handled separately in downstream tasks.
    """

    def __init__(
        self,
        chunks: list[SRSChunk],
        embedder: Any | None = None,
        model_name: str = DEFAULT_MODEL_NAME,
    ) -> None:
        if not isinstance(chunks, list):
            raise TypeError("chunks must be a list of SRSChunk objects")
        self.chunks = chunks
        self.model_name = model_name
        self._embedder = embedder
        self._indexed_chunks: list[SRSChunk] | None = None

    @property
    def loaded_model_name(self) -> str | None:
        """Model ID for a loaded built-in embedder; injected fakes are omitted."""
        if isinstance(self._embedder, SentenceTransformersEmbedder):
            return self._embedder.loaded_model_name
        return None

    @classmethod
    def from_srs_text(
        cls,
        srs_text: str,
        embedder: Any | None = None,
        model_name: str = DEFAULT_MODEL_NAME,
    ) -> DenseRetriever:
        """Construct a retriever directly from raw Markdown SRS text."""
        chunks = SRSIndexer(srs_text).chunk_document()
        return cls(chunks=chunks, embedder=embedder, model_name=model_name)

    def _get_embedder(self) -> Any:
        if self._embedder is None:
            self._embedder = SentenceTransformersEmbedder(self.model_name)
        return self._embedder

    def _ensure_indexed(self) -> None:
        if self._indexed_chunks is not None:
            return
        if not self.chunks:
            self._indexed_chunks = []
            return

        embedder = self._get_embedder()
        texts = [chunk.text for chunk in self.chunks]
        embeddings = embedder.encode(texts)

        indexed: list[SRSChunk] = []
        for chunk, emb in zip(self.chunks, embeddings, strict=True):
            indexed.append(
                SRSChunk(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    section=chunk.section,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    embedding=tuple(float(v) for v in emb),
                )
            )
        self._indexed_chunks = indexed

    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievalResult]:
        """Retrieve top_k most similar SRS chunks for a query string."""
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")

        cleaned_query = query.strip()
        if not cleaned_query or not self.chunks:
            return []

        self._ensure_indexed()
        assert self._indexed_chunks is not None

        embedder = self._get_embedder()
        query_embedding = embedder.encode([cleaned_query])[0]

        results: list[RetrievalResult] = []
        for chunk in self._indexed_chunks:
            if chunk.embedding is None:
                continue
            sim = _cosine_similarity(query_embedding, chunk.embedding)
            results.append(
                RetrievalResult(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    section=chunk.section,
                    similarity=round(sim, 4),
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                )
            )

        results.sort(key=lambda r: (-r.similarity, r.start_line))
        return results[:top_k]
