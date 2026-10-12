"""Unit tests for the dense retrieval engine."""

import pytest

from c1_requirement_quality.rag.indexer import SRSChunk
from c1_requirement_quality.rag.retriever import (
    DenseRetriever,
    RetrievalResult,
    SentenceTransformersEmbedder,
    _cosine_similarity,
)
from c1_requirement_quality.rag.model_loading import RAGModelLoadError


class FakeEmbedder:
    """Deterministic fake embedder for unit tests without downloading models."""

    VOCAB = ["login", "password", "register", "security", "admin"]

    def encode(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for text in texts:
            lower = text.lower()
            vec = [float(lower.count(word)) for word in self.VOCAB]
            # Ensure non-zero norm for fallback matches
            if sum(vec) == 0.0:
                vec = [0.1] * len(self.VOCAB)
            embeddings.append(vec)
        return embeddings


def test_cosine_similarity_basic_and_edge_cases():
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    with pytest.raises(ValueError, match="Vector dimensions must match"):
        _cosine_similarity([1.0], [1.0, 2.0])


def test_dense_retrieval_with_fake_embedder():
    srs = (
        "# User Authentication\n"
        "Users can log in with username and password.\n"
        "\n"
        "# Account Registration\n"
        "New users can register for an account.\n"
        "\n"
        "# System Security\n"
        "Admin users can manage security settings.\n"
    )

    retriever = DenseRetriever.from_srs_text(srs, embedder=FakeEmbedder())
    results = retriever.retrieve("User login with password", top_k=2)

    assert len(results) == 2
    # Top result should be Authentication section containing 'log in' and 'password'
    assert results[0].section == "User Authentication"
    assert "log in" in results[0].text
    assert results[0].similarity > results[1].similarity
    assert results[0].chunk_id == "SRS-L0002-L0002"
    assert results[0].start_line == 2
    assert results[0].end_line == 2


def test_retrieval_result_to_dict():
    res = RetrievalResult(
        chunk_id="SRS-L0001-L0002",
        text="Sample text",
        section="Auth",
        similarity=0.85,
        start_line=1,
        end_line=2,
    )
    assert res.to_dict() == {
        "chunk_id": "SRS-L0001-L0002",
        "text": "Sample text",
        "section": "Auth",
        "similarity": 0.85,
    }


def test_retrieve_handles_empty_inputs():
    retriever = DenseRetriever([], embedder=FakeEmbedder())
    assert retriever.retrieve("login", top_k=3) == []

    srs_retriever = DenseRetriever.from_srs_text(
        "1. The system shall allow login.\n", embedder=FakeEmbedder()
    )
    assert srs_retriever.retrieve("", top_k=3) == []
    assert srs_retriever.retrieve("   ", top_k=3) == []


def test_retrieve_validates_parameters():
    retriever = DenseRetriever([], embedder=FakeEmbedder())

    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        retriever.retrieve("login", top_k=0)

    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        retriever.retrieve("login", top_k=-2)

    with pytest.raises(TypeError, match="query must be a string"):
        retriever.retrieve(123, top_k=2)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="chunks must be a list"):
        DenseRetriever("not a list", embedder=FakeEmbedder())  # type: ignore[arg-type]


def test_lazy_embedder_loading_error_message(monkeypatch):
    embedder = SentenceTransformersEmbedder("dummy-model")

    def mock_import(*args, **kwargs):
        raise ImportError("No module named 'sentence_transformers'")

    monkeypatch.setattr("builtins.__import__", mock_import)

    with pytest.raises(RAGModelLoadError, match="embedding model 'dummy-model'"):
        embedder.encode(["test"])


def test_model_load_error_preserves_model_and_underlying_cause(monkeypatch):
    class BrokenSentenceTransformer:
        def __init__(self, *args, **kwargs):
            raise OSError("model files are not cached")

    monkeypatch.setitem(
        __import__("sys").modules,
        "sentence_transformers",
        type("FakeSentenceTransformers", (), {"SentenceTransformer": BrokenSentenceTransformer}),
    )
    embedder = SentenceTransformersEmbedder("sentence-transformers/test-model")

    with pytest.raises(RAGModelLoadError, match="model files are not cached") as error:
        embedder.encode(["test"])
    assert error.value.component == "embedding"
    assert error.value.model_name == "sentence-transformers/test-model"
