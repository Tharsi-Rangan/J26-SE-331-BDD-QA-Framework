"""Unified dispatcher for multi-format SRS ingestion and text normalization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from c1_requirement_quality.ingest.docx_loader import load_docx_srs
from c1_requirement_quality.ingest.json_loader import load_json_srs
from c1_requirement_quality.ingest.markdown_loader import load_markdown_srs
from c1_requirement_quality.ingest.models import NIRDocument
from c1_requirement_quality.ingest.pdf_loader import load_pdf_srs
from c1_requirement_quality.ingest.txt_loader import load_txt_srs


def load_srs_document(path: Path) -> NIRDocument:
    """Load and normalize an SRS specification from any supported format."""
    if not path.is_file():
        raise FileNotFoundError(f"SRS file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in (".md", ".markdown"):
        return load_markdown_srs(path)
    elif suffix == ".txt":
        return load_txt_srs(path)
    elif suffix == ".pdf":
        return load_pdf_srs(path)
    elif suffix == ".docx":
        return load_docx_srs(path)
    elif suffix == ".json":
        return load_json_srs(path)
    else:
        # Fallback heuristic: try reading as Markdown/text
        try:
            return load_markdown_srs(path)
        except Exception as err:
            raise ValueError(f"Unsupported or unparseable SRS format '{suffix}' for file: {path.name}") from err


def read_srs_text(path: Path) -> str:
    """Read the full normalized UTF-8 text of an SRS document for grounding/refinement.

    Preserves exact text byte streams for Markdown/TXT to maintain byte-for-byte backward
    compatibility with legacy tests, while extracting layout text for PDF, DOCX, and JSON.
    """
    if not path.is_file():
        raise FileNotFoundError(f"SRS file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in (".md", ".markdown", ".txt"):
        return path.read_text(encoding="utf-8-sig")

    doc = load_srs_document(path)
    return doc.raw_text


def extract_srs_requirements(path: Path) -> list[dict[str, Any]]:
    """Extract requirements from any supported SRS document format.

    Returns a list of dicts with 'source' and 'original_text' matching the C1 pipeline contract.
    """
    doc = load_srs_document(path)
    return [req.to_legacy_item() for req in doc.requirements]
