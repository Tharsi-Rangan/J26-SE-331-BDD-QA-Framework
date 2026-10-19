"""Structured JSON SRS loader supporting direct requirement exports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from c1_requirement_quality.ingest.models import (
    ExtractionWarning,
    NIRDocument,
    NIRRequirement,
    NIRTable,
)


def load_json_srs(path: Path) -> NIRDocument:
    """Load and parse an SRS document in structured JSON format."""
    content = path.read_text(encoding="utf-8-sig")
    data = json.loads(content)

    sections: list[str] = []
    requirements: list[NIRRequirement] = []
    tables: list[NIRTable] = []
    warnings: list[ExtractionWarning] = []

    raw_text_parts: list[str] = []

    raw_items: list[dict[str, Any]] = []

    if isinstance(data, list):
        raw_items = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        if "requirements" in data and isinstance(data["requirements"], list):
            raw_items = [item for item in data["requirements"] if isinstance(item, dict)]
        elif "sections" in data and isinstance(data["sections"], list):
            for sec in data["sections"]:
                sec_title = sec.get("title", sec.get("name", "Unspecified"))
                sec_reqs = sec.get("requirements", [])
                for r in sec_reqs:
                    if isinstance(r, dict):
                        r_copy = dict(r)
                        r_copy.setdefault("section", sec_title)
                        raw_items.append(r_copy)
        else:
            # Single requirement object
            raw_items = [data]

    for idx, item in enumerate(raw_items, start=1):
        # Extract requirement text
        text = (
            item.get("text")
            or item.get("original_text")
            or item.get("statement")
            or item.get("description")
            or item.get("specification")
            or ""
        )
        if not text or not str(text).strip():
            warnings.append(
                ExtractionWarning(
                    code="JSON_EMPTY_REQUIREMENT_TEXT",
                    message=f"JSON item at index {idx} has empty requirement text",
                    line=idx,
                )
            )
            continue

        raw_text_val = str(text).strip()
        raw_text_parts.append(raw_text_val)

        # Extract section
        section = (
            item.get("section")
            or item.get("section_title")
            or item.get("module")
            or "Unspecified"
        )
        if isinstance(section, dict):
            section = section.get("section", "Unspecified")
        section_str = str(section).strip()
        if section_str not in sections:
            sections.append(section_str)

        # Extract doc item number / ID
        doc_item = str(
            item.get("doc_item_number")
            or item.get("id")
            or item.get("requirement_id")
            or item.get("number")
            or f"JSON-{idx}"
        ).strip()

        page = item.get("page")
        line = item.get("line", idx)
        table_id = item.get("table_id")

        requirements.append(
            NIRRequirement(
                doc_item_number=doc_item,
                section_title=section_str,
                section_hierarchy=[section_str],
                raw_text=raw_text_val,
                page=int(page) if page is not None else None,
                line=int(line) if isinstance(line, int) and line >= 1 else idx,
                table_id=str(table_id) if table_id else None,
                provenance_notes="Structured JSON record",
            )
        )

    return NIRDocument(
        source_path=path,
        format="json",
        raw_text="\n\n".join(raw_text_parts) if raw_text_parts else content,
        sections=sections if sections else ["Unspecified"],
        requirements=requirements,
        tables=tables,
        warnings=warnings,
    )
