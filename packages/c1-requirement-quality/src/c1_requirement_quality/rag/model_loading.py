"""Shared errors for local RAG model loading."""

from __future__ import annotations


class RAGModelLoadError(RuntimeError):
    """A named local model could not be loaded; no download is attempted here."""

    def __init__(self, component: str, model_name: str, cause: BaseException) -> None:
        self.component = component
        self.model_name = model_name
        self.cause = cause
        super().__init__(
            f"{component} model '{model_name}' could not be loaded from the local "
            f"Hugging Face cache ({type(cause).__name__}: {cause}). Install the "
            "declared [rag] dependencies and explicitly cache the model before "
            "running in offline mode. See the C1 RAG setup instructions."
        )
