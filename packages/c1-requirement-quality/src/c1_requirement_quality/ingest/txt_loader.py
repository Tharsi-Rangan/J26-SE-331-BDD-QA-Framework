"""Plain text SRS loader with outline headings, multiline statements, and table extraction."""

from __future__ import annotations

import re
from pathlib import Path

from c1_requirement_quality.ingest.markdown_loader import load_markdown_srs
from c1_requirement_quality.ingest.models import (
    ExtractionWarning,
    NIRDocument,
    NIRRequirement,
    NIRTable,
)

OUTLINE_HEADING_PATTERN = re.compile(
    r"^(?:(?:SECTION|CHAPTER|PART)\s+\d+[:.]?\s*)?"
    r"(?P<sec_num>\d+(?:\.\d+)*)?\s*"
    r"(?P<title>[A-Z][A-Za-z0-9\s,-]{2,60})\s*$",
)

TXT_REQ_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?P<number>(?:REQ(?:UIREMENT)?[- ]?)?\d+(?:\.\d+)*|[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+)(?:[.):]|\s+-)?\s+(?P<text>[A-Za-z].*)$",
    re.IGNORECASE,
)


def load_txt_srs(path: Path) -> NIRDocument:
    """Load and parse an SRS document in plain text format."""
    content = path.read_text(encoding="utf-8-sig")

    # If document has Markdown style markers, delegate to markdown loader
    if "#" in content or "|" in content:
        doc = load_markdown_srs(path)
        # re-tag format as txt
        return NIRDocument(
            source_path=path,
            format="txt",
            raw_text=doc.raw_text,
            sections=doc.sections,
            requirements=doc.requirements,
            tables=doc.tables,
            warnings=doc.warnings,
        )

    lines = content.splitlines()
    sections: list[str] = []
    current_section = "Unspecified"
    hierarchy: list[str] = ["Unspecified"]
    requirements: list[NIRRequirement] = []
    warnings: list[ExtractionWarning] = []
    seen_in_section: set[str] = set()

    i = 0
    num_lines = len(lines)

    while i < num_lines:
        line = lines[i]
        line_num = i + 1
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Check outline headings: all uppercase or numbered title like "1.0 Overview"
        # Must not look like a requirement statement (no "shall", "must", etc.)
        is_potential_heading = (
            (stripped.isupper() and len(stripped) < 70)
            or (re.match(r"^\d+(?:\.\d+)*\s+[A-Z][a-z0-9\s]{2,40}$", stripped) and not any(w in stripped.lower() for w in ("shall", "must", "should", "will")))
            or re.match(r"^(?:SECTION|CHAPTER)\s+\d+", stripped, re.IGNORECASE)
        )

        if is_potential_heading:
            current_section = stripped
            if current_section not in sections:
                sections.append(current_section)
            hierarchy = [current_section]
            seen_in_section = set()
            i += 1
            continue

        # Check requirement
        match = TXT_REQ_PATTERN.match(line)
        if match:
            source_number = match.group("number")
            initial_text = match.group("text").strip()

            if source_number in seen_in_section:
                raise ValueError(
                    f"Duplicate requirement number {source_number} at line {line_num}"
                )
            seen_in_section.add(source_number)

            req_lines = [initial_text]
            req_start_line = line_num
            i += 1

            # Accumulate multiline continuation
            while i < num_lines:
                cand = lines[i]
                cand_str = cand.strip()
                if not cand_str:
                    break
                if TXT_REQ_PATTERN.match(cand):
                    break
                if cand_str.isupper() and len(cand_str) < 70:
                    break
                if re.match(r"^\d+(?:\.\d+)*\s+[A-Z]", cand_str) and not any(w in cand_str.lower() for w in ("shall", "must")):
                    break

                req_lines.append(cand_str)
                i += 1

            full_text = " ".join(req_lines)
            requirements.append(
                NIRRequirement(
                    doc_item_number=source_number,
                    section_title=current_section,
                    section_hierarchy=list(hierarchy),
                    raw_text=full_text,
                    page=None,
                    line=req_start_line,
                    table_id=None,
                )
            )
            continue

        i += 1

    return NIRDocument(
        source_path=path,
        format="txt",
        raw_text=content,
        sections=sections if sections else [current_section],
        requirements=requirements,
        tables=[],
        warnings=warnings,
    )
