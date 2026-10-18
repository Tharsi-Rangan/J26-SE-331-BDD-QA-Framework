from dataclasses import dataclass

from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser
from c1_requirement_quality.rag.model_loading import RAGModelLoadError
from c1_requirement_quality.rag.verifier import FactVerifier


@dataclass
class Evidence:
    chunk_id: str
    text: str


class FakeEmbedder:
    def encode(self, texts):
        return [[1.0, float(len(text))] for text in texts]


class ExactVerifier(FactVerifier):
    def __init__(self):
        super().__init__()


def test_analyser_reuses_document_index_and_reports_inconclusive():
    analyser = RAGGroundingAnalyser(
        "# Access\nUsers may sign in.\n", embedder=FakeEmbedder(),
        verifier=ExactVerifier(), use_spacy=False,
    )
    result = analyser.analyse("Users can sign in.")
    assert result["status"] == "unsupported"
    assert result["diagnostics"][0]["outcome"] == "INCONCLUSIVE"


def test_analyser_exact_evidence_is_traceable():
    text = "The system shall allow login."
    analyser = RAGGroundingAnalyser(text, embedder=FakeEmbedder(), use_spacy=False)
    result = analyser.analyse(text)
    assert result["status"] == "supported"
    assert result["evidence"][0]["text"] == text
    assert result["evidence"][0]["chunk_id"] == "SRS-L0001-L0001"


def test_embedding_load_failure_is_named_and_not_retried_per_fact():
    class BrokenEmbedder:
        calls = 0

        def encode(self, texts):
            self.calls += 1
            raise RAGModelLoadError(
                "embedding", "sentence-transformers/test-model",
                OSError("model files are not cached"),
            )

    embedder = BrokenEmbedder()
    analyser = RAGGroundingAnalyser(
        "The system shall allow login. The system shall allow logout.",
        embedder=embedder,
        verifier=FactVerifier(),
        use_spacy=False,
    )
    result = analyser.analyse("The system shall allow login. The system shall allow logout.")

    assert embedder.calls == 1
    assert result["status"] == "unsupported"
    assert [item["outcome"] for item in result["diagnostics"]] == ["ERROR", "ERROR"]
    assert all(item["component"] == "embedding" for item in result["diagnostics"])
    assert all(item["model"] == "sentence-transformers/test-model" for item in result["diagnostics"])
    assert all("model files are not cached" in item["diagnostic"] for item in result["diagnostics"])


def test_analyser_retains_support_and_conflict_without_promoting_grounding():
    text = "The system shall allow login."
    analyser = RAGGroundingAnalyser(text, embedder=FakeEmbedder(),
        verifier=FactVerifier(), use_spacy=False)
    from c1_requirement_quality.rag.indexer import SRSChunk
    analyser.retriever.retrieve = lambda *args: [
        SRSChunk("support", text, None, 1, 1),
        SRSChunk("conflict", "The system shall not allow login.", None, 2, 2)]
    result = analyser.analyse(text)
    assert result["status"] == "unsupported"
    assert {item["chunk_id"] for item in result["evidence"]} == {"support", "conflict"}
    assert result["diagnostics"][0]["evidence_outcomes"] == [
        {"chunk_id": "support", "outcome": "SUPPORTED"},
        {"chunk_id": "conflict", "outcome": "CONTRADICTED"}]


def test_release_drops_model_cycles_and_indexed_embeddings():
    import weakref
    from c1_requirement_quality.rag.retriever import SentenceTransformersEmbedder
    from c1_requirement_quality.rag.verifier import LocalNLI
    class Model:
        pass
    embedder = SentenceTransformersEmbedder()
    nli = LocalNLI()
    model, pipeline = Model(), Model()
    model.cycle, pipeline.cycle = model, pipeline
    model_ref, pipeline_ref = weakref.ref(model), weakref.ref(pipeline)
    embedder._model, nli._pipeline = model, pipeline
    del model, pipeline
    analyser = RAGGroundingAnalyser("Source", embedder=embedder, verifier=FactVerifier(nli), use_spacy=False)
    analyser.retriever._indexed_chunks = [object()]
    analyser.release()
    assert model_ref() is None and pipeline_ref() is None
    assert analyser.retriever._indexed_chunks is None and analyser.retriever._embedder is None
    assert nli._pipeline is None and embedder._model is None
