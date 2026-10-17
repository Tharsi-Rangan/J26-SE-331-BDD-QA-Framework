"""RAG orchestration for traceable requirement fact grounding."""

from __future__ import annotations

from typing import Any

from c1_requirement_quality.rag.fact_extractor import Fact, extract_facts
from c1_requirement_quality.rag.retriever import DenseRetriever
from c1_requirement_quality.rag.model_loading import RAGModelLoadError
from c1_requirement_quality.rag.verifier import (
    FactVerifier,
    LocalNLI,
    VerificationOutcome,
    VerificationResult,
)


class RAGGroundingAnalyser:
    """Index a document once, then retrieve and verify each extracted fact."""

    def __init__(self, srs_text: str, *, embedder: Any | None = None,
                 verifier: FactVerifier | None = None, top_k: int = 5,
                 use_spacy: bool = True) -> None:
        self.retriever = DenseRetriever.from_srs_text(srs_text, embedder=embedder)
        self.verifier = verifier or FactVerifier(LocalNLI())
        self.top_k = top_k
        self.use_spacy = use_spacy
        self._embedding_load_error: RAGModelLoadError | None = None

    @property
    def loaded_model_names(self) -> tuple[str, ...]:
        """Exact built-in model IDs loaded during this analyser's execution."""
        names: list[str] = []
        embedding_name = self.retriever.loaded_model_name
        if embedding_name is not None:
            names.append(embedding_name)
        nli = self.verifier.nli
        if isinstance(nli, LocalNLI) and nli.loaded_model_name is not None:
            names.append(nli.loaded_model_name)
        return tuple(names)

    def analyse(self, requirement_text: str) -> dict[str, object]:
        facts = extract_facts(requirement_text, use_spacy=self.use_spacy)
        diagnostics: list[dict[str, object]] = []
        evidence: list[dict[str, object]] = []
        result_by_fact: list[VerificationOutcome] = []
        evidence_ids: set[str] = set()
        errors: list[str] = []
        for fact in facts:
            if self._embedding_load_error is not None:
                candidates = []
                err = self._embedding_load_error
                result = VerificationResult(
                    VerificationOutcome.ERROR,
                    method="embedding",
                    diagnostic=str(err),
                    component=err.component,
                    model_name=err.model_name,
                )
            else:
                try:
                    candidates = self.retriever.retrieve(fact.text, self.top_k)
                    result = self.verifier.verify(fact, candidates)
                except RAGModelLoadError as err:
                    self._embedding_load_error = err
                    candidates = []
                    result = VerificationResult(
                        VerificationOutcome.ERROR,
                        method="embedding",
                        diagnostic=str(err),
                        component=err.component,
                        model_name=err.model_name,
                    )
                except (ImportError, OSError, RuntimeError, ValueError) as err:
                    candidates = []
                    result = VerificationResult(
                        VerificationOutcome.ERROR,
                        method="retrieval",
                        diagnostic=f"Evidence retrieval failed: {type(err).__name__}: {err}",
                        component="retrieval",
                    )
            result_by_fact.append(result.outcome)
            if result.diagnostic:
                errors.append(result.diagnostic) if result.outcome is VerificationOutcome.ERROR else None
            matched = set(result.evidence_ids)
            diagnostics.append({
                "fact": fact.to_dict(),
                "outcome": result.outcome.value,
                "method": result.method,
                "component": result.component or result.method,
                "model": result.model_name,
                "diagnostic": result.diagnostic,
                "retrieved_evidence": [candidate.to_dict() for candidate in candidates],
            })
            for candidate in candidates:
                if candidate.chunk_id in matched and candidate.chunk_id not in evidence_ids:
                    evidence_ids.add(candidate.chunk_id)
                    evidence.append(candidate.to_dict())
        if not facts:
            status = "not_applicable"
        elif VerificationOutcome.ERROR in result_by_fact:
            status = "unsupported"
        elif VerificationOutcome.CONTRADICTED in result_by_fact:
            status = "partially_supported" if VerificationOutcome.SUPPORTED in result_by_fact else "unsupported"
        elif all(value is VerificationOutcome.SUPPORTED for value in result_by_fact):
            status = "supported"
        elif VerificationOutcome.SUPPORTED in result_by_fact:
            status = "partially_supported"
        else:
            status = "unsupported"
        return {
            "status": status,
            "evidence": evidence,
            "diagnostics": diagnostics,
            "errors": errors,
        }


def analyse_rag_grounding(requirement_text: str, srs_text: str, **kwargs: Any) -> dict[str, object]:
    """Convenience one-shot RAG analysis API."""
    return RAGGroundingAnalyser(srs_text, **kwargs).analyse(requirement_text)
