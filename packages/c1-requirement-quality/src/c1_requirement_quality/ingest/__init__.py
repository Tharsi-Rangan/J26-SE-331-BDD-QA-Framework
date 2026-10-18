"""Multi-format SRS ingestion and normalization package for Component 1."""

from __future__ import annotations

from c1_requirement_quality.ingest.dispatcher import (
    extract_srs_requirements,
    load_srs_document,
    read_srs_text,
)
from c1_requirement_quality.ingest.models import (
    ExtractionWarning,
    NIRDocument,
    NIRRequirement,
    NIRTable,
)

__all__ = [
    "ExtractionWarning",
    "NIRDocument",
    "NIRRequirement",
    "NIRTable",
    "extract_srs_requirements",
    "load_srs_document",
    "read_srs_text",
]
