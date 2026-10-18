"""Word DOCX SRS loader with style hierarchy, multiline paragraphs, and table extraction."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from c1_requirement_quality.ingest.models import (
    ExtractionWarning,
    NIRDocument,
    NIRRequirement,
    NIRTable,
)

DOCX_REQ_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?P<number>(?:REQ(?:UIREMENT)?[- ]?)?\d+(?:\.\d+)*|[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+)(?:[.):]|\s+-)?\s+(?P<text>[A-Za-z].*)$",
    re.IGNORECASE,
)


def load_docx_srs(path: Path) -> NIRDocument:
    """Load and parse an SRS document in Microsoft Word (.docx) format."""
    import docx

    doc = docx.Document(str(path))
    paragraphs = doc.paragraphs
    paragraph_by_element = {p._p: (i + 1, p) for i, p in enumerate(paragraphs)}
    table_by_element = {t._tbl: (i + 1, t) for i, t in enumerate(doc.tables)}
    source_blocks: list[dict[str, Any]] = []
    block_sections: dict[Any, list[str]] = {}
    headings: dict[int, str] = {}
    for element in doc.element.body:
        if element in paragraph_by_element:
            number, paragraph = paragraph_by_element[element]
            style = getattr(paragraph.style, "name", "")
            if style.startswith("Heading"):
                level = int(style.split()[-1]) if style.split()[-1].isdigit() else 1
                headings = {k: v for k, v in headings.items() if k < level}
                headings[level] = paragraph.text.strip()
            source_blocks.append({"kind": "paragraph", "paragraph": number,
                                  "text": paragraph.text, "style": style, "page": None})
        elif element in table_by_element:
            number, table = table_by_element[element]
            source_blocks.append({"kind": "table", "table_id": f"Table-{number}",
                                  "rows": [[c.text for c in row.cells] for row in table.rows], "page": None})
        block_sections[element] = [headings[k] for k in sorted(headings)] or ["Unspecified"]
    normalized_paragraphs = {p._p: p.text.strip() for p in paragraphs}
    normalized_tables: dict[Any, str] = {}
    warnings: list[ExtractionWarning] = [
        ExtractionWarning(
            code="DOCX_PAGE_NUMBERS_UNAVAILABLE",
            message="DOCX format does not store physical page boundaries; requirement page numbers recorded as unknown.",
        )
    ]

    raw_text_parts: list[str] = []
    sections: list[str] = []
    current_section = "Unspecified"
    hierarchy: list[str] = ["Unspecified"]
    requirements: list[NIRRequirement] = []
    tables: list[NIRTable] = []
    seen_in_section: set[str] = set()

    # 1. Extract tables
    for tab_idx, table in enumerate(doc.tables, start=1):
        hierarchy = block_sections[table._tbl]
        current_section = hierarchy[-1]
        table_id = f"Table-{tab_idx}"
        rows_data: list[list[str]] = []
        for row in table.rows:
            rows_data.append([cell.text.strip() for cell in row.cells])

        if not rows_data:
            continue

        headers = rows_data[0]
        data_rows = rows_data[1:] if len(rows_data) > 1 else []

        tab_obj = NIRTable(
            table_id=table_id,
            headers=headers,
            rows=data_rows,
            page=None,
            line=tab_idx,
        )
        tables.append(tab_obj)
        normalized_tables[table._tbl] = tab_obj.to_markdown()

        # Inspect table rows for requirements
        id_col_idx = -1
        text_col_idx = -1
        for c_idx, h_name in enumerate(headers):
            h_lower = h_name.lower()
            if any(k in h_lower for k in ("req", "id", "item", "#", "number")) and id_col_idx == -1:
                id_col_idx = c_idx
            elif any(k in h_lower for k in ("requirement", "statement", "description", "specification", "shall", "text")) and text_col_idx == -1:
                text_col_idx = c_idx

        for r_idx, r_cells in enumerate(data_rows, start=1):
            req_id_val = r_cells[id_col_idx] if 0 <= id_col_idx < len(r_cells) else ""
            req_text_val = r_cells[text_col_idx] if 0 <= text_col_idx < len(r_cells) else ""

            if not req_text_val:
                for c_val in r_cells:
                    if any(modal in c_val.lower() for modal in ("shall", "must", "will", "should")):
                        req_text_val = c_val
                        break

            if not req_text_val and req_id_val:
                non_id_parts = [
                    f"[{headers[c_i]}: {r_cells[c_i]}]" if c_i < len(headers) and headers[c_i] else r_cells[c_i]
                    for c_i in range(len(r_cells))
                    if c_i != id_col_idx and r_cells[c_i]
                ]
                if non_id_parts:
                    req_text_val = " ".join(non_id_parts)

            if req_text_val and (req_id_val or any(modal in req_text_val.lower() for modal in ("shall", "must"))):
                doc_item = req_id_val if req_id_val else f"{table_id}-R{r_idx}"
                requirements.append(
                    NIRRequirement(
                        doc_item_number=doc_item,
                        section_title=current_section,
                        section_hierarchy=list(hierarchy),
                        raw_text=req_text_val.strip(),
                        page=None,
                        line=r_idx,
                        table_id=table_id,
                        provenance_notes=f"Row {r_idx}",
                    )
                )

    # 2. Extract paragraphs
    p_idx = 0
    total_paragraphs = len(paragraphs)

    while p_idx < total_paragraphs:
        p = paragraphs[p_idx]
        text = p.text.strip()
        style_name = getattr(p.style, "name", "")

        if not text:
            p_idx += 1
            continue

        # Check Heading styles
        is_heading = style_name.startswith("Heading") or (
            (text.isupper() and len(text) < 70)
            or re.match(r"^\d+(?:\.\d+)*\s+[A-Z]", text) and not any(w in text.lower() for w in ("shall", "must"))
        )

        if is_heading:
            current_section = text
            if current_section not in sections:
                sections.append(current_section)
            hierarchy = block_sections[p._p]
            seen_in_section = set()
            p_idx += 1
            continue

        # Check requirement statement
        match = DOCX_REQ_PATTERN.match(text)
        if match:
            source_number = match.group("number")
            initial_text = match.group("text").strip()

            if source_number in seen_in_section:
                warnings.append(
                    ExtractionWarning(
                        code="DOCX_DUPLICATE_REQ_NUMBER",
                        message=f"Duplicate requirement number {source_number} in section '{current_section}'",
                        section=current_section,
                    )
                )
            seen_in_section.add(source_number)

            collected = [initial_text]
            req_start_p = p_idx + 1
            p_idx += 1

            # Accumulate multiline continuation paragraphs
            while p_idx < total_paragraphs:
                cand_p = paragraphs[p_idx]
                # A table interrupts paragraph flow; never merge across it.
                if cand_p._p.getprevious() is not paragraphs[p_idx - 1]._p:
                    break
                cand_text = cand_p.text.strip()
                cand_style = getattr(cand_p.style, "name", "")

                if not cand_text:
                    p_idx += 1
                    break
                if cand_style.startswith("Heading") or DOCX_REQ_PATTERN.match(cand_text):
                    break
                if cand_text.isupper() and len(cand_text) < 70:
                    break
                if re.match(r"^\d+(?:\.\d+)*\s+[A-Z]", cand_text) and not any(w in cand_text.lower() for w in ("shall", "must")):
                    break

                collected.append(cand_text)
                normalized_paragraphs[cand_p._p] = ""
                p_idx += 1

            # Keep the complete obligation together for lexical grounding while
            # preserving every original paragraph verbatim in source_blocks.
            normalized_paragraphs[p._p] = text + (" " + " ".join(collected[1:]) if len(collected) > 1 else "")

            requirements.append(
                NIRRequirement(
                    doc_item_number=source_number,
                    section_title=current_section,
                    section_hierarchy=list(hierarchy),
                    raw_text=" ".join(collected),
                    page=None,
                    line=req_start_p,
                    table_id=None,
                    provenance_notes="DOCX paragraph flow",
                )
            )
            continue

        p_idx += 1

    for element in doc.element.body:
        text = normalized_paragraphs.get(element, normalized_tables.get(element, ""))
        if text:
            raw_text_parts.append(text)
    return NIRDocument(
        source_path=path,
        format="docx",
        raw_text="\n\n".join(raw_text_parts),
        sections=sections if sections else [current_section],
        requirements=requirements,
        tables=tables,
        warnings=warnings,
        source_blocks=source_blocks,
    )
