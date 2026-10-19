"""Normalized Intermediate Representation (NIR) models for SRS ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExtractionWarning:
    """Warning encountered during document parsing or structural extraction."""
    code: str
    message: str
    section: str = "Unspecified"
    page: int | None = None
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "section": self.section,
            "page": self.page,
            "line": self.line,
        }


@dataclass(frozen=True)
class NIRTable:
    """Tabular structure extracted verbatim from an SRS document."""
    table_id: str
    headers: list[str]
    rows: list[list[str]]
    page: int | None = None
    line: int | None = None
    caption: str = ""
    raw_markdown: str = ""

    def to_markdown(self) -> str:
        """Render table as a standard Markdown table."""
        if not self.headers and not self.rows:
            return ""
        cols = max(len(self.headers), max((len(r) for r in self.rows), default=0))
        headers = self.headers + [""] * (cols - len(self.headers)) if self.headers else [f"Col {i+1}" for i in range(cols)]
        
        lines = [
            "| " + " | ".join(h.replace("\n", " ").strip() for h in headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in self.rows:
            padded_row = row + [""] * (cols - len(row))
            lines.append("| " + " | ".join(c.replace("\n", " ").strip() for c in padded_row) + " |")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "headers": self.headers,
            "rows": self.rows,
            "page": self.page,
            "line": self.line,
            "caption": self.caption,
        }


@dataclass(frozen=True)
class NIRRequirement:
    """Individual requirement statement extracted from an SRS document."""
    doc_item_number: str
    section_title: str
    section_hierarchy: list[str]
    raw_text: str
    page: int | None = None
    line: int = 1
    table_id: str | None = None
    provenance_notes: str = ""
    category: str = "REQUIREMENT"  # "REQUIREMENT" | "CONTEXT" | "UNCERTAIN"
    sub_category: str = ""         # "HEADING" | "TOC" | "USE_CASE_STEP" | "SYSTEM_RESPONSE" | "EXPLANATION" | etc.
    classification_reason: str = ""

    def to_source_dict(self) -> dict[str, Any]:
        """Convert to contract-compliant source object adhering to c1-validated-requirements schema.

        The schema strictly allows only 'section' (string) and 'line' (integer >= 1).
        Additional physical coordinates (table or page) are attached to section when present.
        """
        section_str = self.section_title
        extras: list[str] = []
        if self.table_id:
            extras.append(f"Table: {self.table_id}")
        if self.page is not None:
            extras.append(f"p. {self.page}")
        elif self.provenance_notes and "Row" in self.provenance_notes:
            extras.append(self.provenance_notes)

        if extras:
            section_str = f"{self.section_title} [{', '.join(extras)}]"

        return {
            "section": section_str,
            "line": max(1, self.line),
        }

    def to_legacy_item(self) -> dict[str, Any]:
        """Convert to dict matching legacy extract_requirements output."""
        return {
            "source": self.to_source_dict(),
            "original_text": self.raw_text,
            "doc_item_number": self.doc_item_number,
            "section_hierarchy": self.section_hierarchy,
            "page": self.page,
            "table_id": self.table_id,
            "category": self.category,
            "sub_category": self.sub_category,
        }


@dataclass(frozen=True)
class NIRDocument:
    """Normalized Intermediate Representation of an entire SRS document."""
    source_path: Path
    format: str
    raw_text: str
    sections: list[str]
    requirements: list[NIRRequirement]
    context_items: list[NIRRequirement] = field(default_factory=list)
    uncertain_items: list[NIRRequirement] = field(default_factory=list)
    tables: list[NIRTable] = field(default_factory=list)
    warnings: list[ExtractionWarning] = field(default_factory=list)
    # Physical source blocks retained separately from normalized grounding text.
    source_blocks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "format": self.format,
            "sections": self.sections,
            "requirements_count": len(self.requirements),
            "context_items_count": len(self.context_items),
            "uncertain_items_count": len(self.uncertain_items),
            "tables_count": len(self.tables),
            "warnings": [w.to_dict() for w in self.warnings],
        }

