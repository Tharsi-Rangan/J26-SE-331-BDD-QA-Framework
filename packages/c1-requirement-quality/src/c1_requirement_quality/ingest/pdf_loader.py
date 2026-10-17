"""Text-based PDF SRS loader with page tracking, layout extraction, and table support."""

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
from c1_requirement_quality.ingest.classifier import (
    BULLET_PREFIX,
    CONSTRAINT_PREDICATES,
    MODAL_PATTERN,
    NUMBERED_PREFIX,
    OUTLINE_HEADING_PATTERN,
    PAGE_NUM_ONLY,
    REQ_ID_PREFIX,
    SYSTEM_RESPONSE_PATTERN,
    TOC_DOT_LEADER_PATTERN,
    TOC_HEADING_PATTERN,
    USER_ACTION_PATTERN,
    detect_repeated_headers_footers,
    is_introductory_section,
    is_use_case_section,
)



def _extract_with_pdfplumber(path: Path) -> tuple[str, list[dict[str, Any]], list[NIRTable], list[ExtractionWarning]]:
    import pdfplumber

    pages_data: list[dict[str, Any]] = []
    tables: list[NIRTable] = []
    warnings: list[ExtractionWarning] = []
    full_text_parts: list[str] = []

    with pdfplumber.open(path) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            full_text_parts.append(f"--- Page {page_idx} ---\n{page_text}")

            extracted_tables = []
            try:
                extracted_tables = page.extract_tables() or []
            except Exception as e:
                warnings.append(
                    ExtractionWarning(
                        code="PDF_TABLE_EXTRACTION_FAILED",
                        message=f"Failed to extract tables on page {page_idx}: {e}",
                        page=page_idx,
                    )
                )

            for tab_idx, raw_table in enumerate(extracted_tables, start=1):
                if not raw_table:
                    continue
                cleaned_rows = [
                    [str(cell).strip() if cell is not None else "" for cell in row]
                    for row in raw_table
                ]
                headers = cleaned_rows[0] if cleaned_rows else []
                data_rows = cleaned_rows[1:] if len(cleaned_rows) > 1 else []
                table_id = f"Page{page_idx}-Table{tab_idx}"
                
                table_obj = NIRTable(
                    table_id=table_id,
                    headers=headers,
                    rows=data_rows,
                    page=page_idx,
                    line=1,
                )
                tables.append(table_obj)

            pages_data.append({
                "page_num": page_idx,
                "text": page_text,
            })

    return "\n\n".join(full_text_parts), pages_data, tables, warnings


def _extract_with_pypdf(path: Path) -> tuple[str, list[dict[str, Any]], list[NIRTable], list[ExtractionWarning]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages_data: list[dict[str, Any]] = []
    full_text_parts: list[str] = []
    warnings: list[ExtractionWarning] = [
        ExtractionWarning(
            code="PDF_FALLBACK_PYPDF",
            message="Used pypdf fallback; table layout extraction may be degraded",
        )
    ]

    for page_idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        full_text_parts.append(f"--- Page {page_idx} ---\n{text}")
        pages_data.append({"page_num": page_idx, "text": text})

    return "\n\n".join(full_text_parts), pages_data, [], warnings


def load_pdf_srs(path: Path) -> NIRDocument:
    """Load and parse an SRS document in text-based PDF format."""
    warnings: list[ExtractionWarning] = []
    try:
        raw_text, pages_data, tables, plumber_warnings = _extract_with_pdfplumber(path)
        warnings.extend(plumber_warnings)
    except Exception as err:
        try:
            raw_text, pages_data, tables, pypdf_warnings = _extract_with_pypdf(path)
            warnings.extend(pypdf_warnings)
        except Exception as pypdf_err:
            raise ValueError(f"Failed to parse PDF document {path.name}: {err}; pypdf fallback error: {pypdf_err}") from err

    sections: list[str] = []
    current_section = "Unspecified"
    hierarchy: list[str] = ["Unspecified"]
    requirements: list[NIRRequirement] = []
    context_items: list[NIRRequirement] = []
    uncertain_items: list[NIRRequirement] = []
    seen_in_section: set[str] = set()

    # Detect repeated headers and footers across pages
    repeated_hf = detect_repeated_headers_footers(pages_data)

    # 1. Extract requirements from tables
    for table in tables:
        headers = table.headers
        id_col_idx = -1
        text_col_idx = -1

        for c_idx, h_name in enumerate(headers):
            h_lower = h_name.lower()
            if any(k in h_lower for k in ("req", "id", "item", "#", "number")) and id_col_idx == -1:
                id_col_idx = c_idx
            elif any(k in h_lower for k in ("requirement", "statement", "description", "specification", "shall", "text")) and text_col_idx == -1:
                text_col_idx = c_idx

        for row_idx, row in enumerate(table.rows, start=1):
            req_id_val = row[id_col_idx] if 0 <= id_col_idx < len(row) else ""
            req_text_val = row[text_col_idx] if 0 <= text_col_idx < len(row) else ""

            if not req_text_val:
                for cell in row:
                    if any(modal in cell.lower() for modal in ("shall", "must", "will", "should")):
                        req_text_val = cell
                        break

            if not req_text_val and req_id_val:
                non_id_parts = [
                    f"[{headers[c_i]}: {row[c_i]}]" if c_i < len(headers) and headers[c_i] else row[c_i]
                    for c_i in range(len(row))
                    if c_i != id_col_idx and row[c_i]
                ]
                if non_id_parts:
                    req_text_val = " ".join(non_id_parts)

            doc_item = req_id_val if req_id_val else f"{table.table_id}-R{row_idx}"
            if req_text_val and (req_id_val or any(modal in req_text_val.lower() for modal in ("shall", "must"))):
                requirements.append(
                    NIRRequirement(
                        doc_item_number=doc_item,
                        section_title=current_section,
                        section_hierarchy=list(hierarchy),
                        raw_text=req_text_val.strip(),
                        page=table.page,
                        line=row_idx,
                        table_id=table.table_id,
                        provenance_notes=f"Row {row_idx}",
                        category="REQUIREMENT",
                        sub_category="TABLE_ROW",
                    )
                )
            elif req_text_val:
                context_items.append(
                    NIRRequirement(
                        doc_item_number=doc_item,
                        section_title=current_section,
                        section_hierarchy=list(hierarchy),
                        raw_text=req_text_val.strip(),
                        page=table.page,
                        line=row_idx,
                        table_id=table.table_id,
                        provenance_notes=f"Row {row_idx}",
                        category="CONTEXT",
                        sub_category="TABLE_ROW",
                    )
                )

    # 2. Extract requirements from text flow
    in_toc = False

    for page_info in pages_data:
        page_num = page_info["page_num"]
        lines = page_info["text"].splitlines()
        line_idx = 0
        total_p_lines = len(lines)

        while line_idx < total_p_lines:
            raw_line = lines[line_idx].strip()
            line_idx += 1
            source_line = line_idx  # retain the start before continuation advances it
            if not raw_line:
                continue

            # A. Repeated header/footer or standalone page numbers -> CONTEXT
            if raw_line in repeated_hf or PAGE_NUM_ONLY.match(raw_line):
                context_items.append(
                    NIRRequirement(
                        doc_item_number="",
                        section_title=current_section,
                        section_hierarchy=list(hierarchy),
                        raw_text=raw_line,
                        page=page_num,
                        line=source_line,
                        category="CONTEXT",
                        sub_category="HEADER_FOOTER",
                        classification_reason="Repeated running header/footer or page number",
                    )
                )
                continue

            # B. Table of Contents detection -> CONTEXT
            if TOC_HEADING_PATTERN.match(raw_line):
                in_toc = True
                context_items.append(
                    NIRRequirement(
                        doc_item_number="",
                        section_title=current_section,
                        section_hierarchy=list(hierarchy),
                        raw_text=raw_line,
                        page=page_num,
                        line=source_line,
                        category="CONTEXT",
                        sub_category="TOC_HEADING",
                    )
                )
                continue

            if in_toc:
                if (OUTLINE_HEADING_PATTERN.match(raw_line) or (raw_line.isupper() and len(raw_line) < 60)) and not TOC_DOT_LEADER_PATTERN.search(raw_line):
                    in_toc = False
                elif TOC_DOT_LEADER_PATTERN.search(raw_line) or re.match(r"^\d+(?:\.\d+)*\s+[A-Za-z].*\d+$", raw_line):
                    context_items.append(
                        NIRRequirement(
                            doc_item_number="",
                            section_title=current_section,
                            section_hierarchy=list(hierarchy),
                            raw_text=raw_line,
                            page=page_num,
                            line=source_line,
                            category="CONTEXT",
                            sub_category="TOC_ENTRY",
                            classification_reason="Table of contents dot-leader line",
                        )
                    )
                    continue
                else:
                    context_items.append(
                        NIRRequirement(
                            doc_item_number="",
                            section_title=current_section,
                            section_hierarchy=list(hierarchy),
                            raw_text=raw_line,
                            page=page_num,
                            line=source_line,
                            category="CONTEXT",
                            sub_category="TOC_ENTRY",
                        )
                    )
                    continue
            elif TOC_DOT_LEADER_PATTERN.search(raw_line):
                context_items.append(
                    NIRRequirement(
                        doc_item_number="",
                        section_title=current_section,
                        section_hierarchy=list(hierarchy),
                        raw_text=raw_line,
                        page=page_num,
                        line=source_line,
                        category="CONTEXT",
                        sub_category="TOC_ENTRY",
                        classification_reason="Table of contents dot-leader line",
                    )
                )
                continue


            # C. Glossary detection in glossary sections -> CONTEXT
            if "glossary" in current_section.lower() or "definitions" in current_section.lower():
                if ":" in raw_line and not any(w in raw_line.lower() for w in ("shall", "must", "will", "should")):
                    context_items.append(
                        NIRRequirement(
                            doc_item_number="",
                            section_title=current_section,
                            section_hierarchy=list(hierarchy),
                            raw_text=raw_line,
                            page=page_num,
                            line=source_line,
                            category="CONTEXT",
                            sub_category="GLOSSARY",
                        )
                    )
                    continue

            # D. Structural Heading Detection
            is_heading = False
            heading_title = ""
            m_head = OUTLINE_HEADING_PATTERN.match(raw_line)
            m_sec = re.match(r"^(?:Section|Chapter|Appendix)\s+([A-Z0-9]+)[:.]?\s*([A-Za-z0-9\s/&,:-]{2,70})$", raw_line, re.IGNORECASE)

            if ((raw_line.isupper() and len(raw_line) < 60) or m_head or m_sec) and not REQ_ID_PREFIX.match(raw_line):
                if not (MODAL_PATTERN.search(raw_line) or CONSTRAINT_PREDICATES.search(raw_line)):
                    is_heading = True
                    heading_title = raw_line



            if is_heading:
                current_section = heading_title
                if current_section not in sections:
                    sections.append(current_section)
                hierarchy = [current_section]
                seen_in_section = set()
                context_items.append(
                    NIRRequirement(
                        doc_item_number="",
                        section_title=current_section,
                        section_hierarchy=list(hierarchy),
                        raw_text=raw_line,
                        page=page_num,
                        line=source_line,
                        category="CONTEXT",
                        sub_category="HEADING",
                        classification_reason="Document section heading",
                    )
                )
                continue

            # Multiline continuation collector helper
            def collect_continuation(first_text: str, cur_idx: int) -> tuple[str, int]:
                collected = [first_text]
                while cur_idx < total_p_lines:
                    nxt = lines[cur_idx].strip()
                    if not nxt:
                        break
                    if nxt in repeated_hf or PAGE_NUM_ONLY.match(nxt):
                        break
                    if REQ_ID_PREFIX.match(nxt):
                        break
                    if BULLET_PREFIX.match(nxt):
                        # Join child bullet if parent statement introduced it with a colon
                        if collected[-1].rstrip().endswith(":"):
                            collected.append(BULLET_PREFIX.sub("", nxt).strip())
                            cur_idx += 1
                            continue
                        break
                    if NUMBERED_PREFIX.match(nxt):
                        break
                    if nxt.isupper() and len(nxt) < 60:
                        break
                    if re.match(r"^\d+(?:\.\d+)*\s+[A-Z]", nxt) and not any(w in nxt.lower() for w in ("shall", "must")):
                        break
                    collected.append(nxt)
                    cur_idx += 1
                return " ".join(collected), cur_idx

            # 1. Explicit Requirement ID (REQ-..., OE-..., CO-..., etc.) -> REQUIREMENT
            req_id_m = REQ_ID_PREFIX.match(raw_line)
            if req_id_m:
                r_id = req_id_m.group("req_id")
                r_text = req_id_m.group("text").strip()
                full_text, line_idx = collect_continuation(r_text, line_idx)

                if r_id in seen_in_section:
                    warnings.append(
                        ExtractionWarning(
                            code="PDF_DUPLICATE_REQ_NUMBER",
                            message=f"Duplicate requirement number {r_id} on page {page_num}",
                            section=current_section,
                            page=page_num,
                        )
                    )
                seen_in_section.add(r_id)

                requirements.append(
                    NIRRequirement(
                        doc_item_number=r_id,
                        section_title=current_section,
                        section_hierarchy=list(hierarchy),
                        raw_text=full_text,
                        page=page_num,
                        line=source_line,
                        category="REQUIREMENT",
                        classification_reason="Explicit requirement identifier tag",
                    )
                )
                continue

            # 2. Introductory/overview sections without explicit ID -> CONTEXT
            if is_introductory_section(current_section):
                full_text, line_idx = collect_continuation(raw_line, line_idx)
                context_items.append(
                    NIRRequirement(
                        doc_item_number="",
                        section_title=current_section,
                        section_hierarchy=list(hierarchy),
                        raw_text=full_text,
                        page=page_num,
                        line=source_line,
                        category="CONTEXT",
                        sub_category="INTRODUCTORY_TEXT",
                        classification_reason="Introductory or overview section narrative",
                    )
                )
                continue

            # 3. Procedural Use Case Steps (User clicks..., User opens...) -> CONTEXT
            is_use_case = is_use_case_section(current_section)
            if USER_ACTION_PATTERN.match(raw_line):
                full_text, line_idx = collect_continuation(raw_line, line_idx)
                context_items.append(
                    NIRRequirement(
                        doc_item_number="",
                        section_title=current_section,
                        section_hierarchy=list(hierarchy),
                        raw_text=full_text,
                        page=page_num,
                        line=source_line,
                        category="CONTEXT",
                        sub_category="USE_CASE_STEP",
                        classification_reason="Actor procedural action step in use case",
                    )
                )
                continue

            # 4. Bulleted or Numbered lines
            b_match = BULLET_PREFIX.match(raw_line)
            n_match = NUMBERED_PREFIX.match(raw_line)

            if b_match or n_match:
                prefix_num = n_match.group("num") if n_match else ""
                content_text = raw_line[b_match.end():] if b_match else raw_line[n_match.end():]
                full_text, line_idx = collect_continuation(content_text.strip(), line_idx)

                if is_use_case:
                    # In use-case sections, distinguish system responses / constraints from procedural steps
                    if MODAL_PATTERN.search(full_text) or CONSTRAINT_PREDICATES.search(full_text):

                        requirements.append(
                            NIRRequirement(
                                doc_item_number=prefix_num or "UC-REQ",
                                section_title=current_section,
                                section_hierarchy=list(hierarchy),
                                raw_text=full_text,
                                page=page_num,
                                line=source_line,
                                category="REQUIREMENT",
                                sub_category="SYSTEM_RESPONSE",
                                classification_reason="System response constraint in use case",
                            )
                        )
                    else:
                        context_items.append(
                            NIRRequirement(
                                doc_item_number=prefix_num,
                                section_title=current_section,
                                section_hierarchy=list(hierarchy),
                                raw_text=full_text,
                                page=page_num,
                                line=source_line,
                                category="CONTEXT",
                                sub_category="USE_CASE_STEP",
                                classification_reason="Procedural flow step in use case",
                            )
                        )
                    continue

                # In general or requirement sections:
                if MODAL_PATTERN.search(full_text) or CONSTRAINT_PREDICATES.search(full_text):
                    doc_item = prefix_num if prefix_num else f"REQ-p{page_num}-l{source_line}"
                    requirements.append(
                        NIRRequirement(
                            doc_item_number=doc_item,
                            section_title=current_section,
                            section_hierarchy=list(hierarchy),
                            raw_text=full_text,
                            page=page_num,
                            line=source_line,
                            category="REQUIREMENT",
                            classification_reason="Modal verb or normative constraint predicate",
                        )
                    )
                elif n_match:
                    uncertain_items.append(
                        NIRRequirement(
                            doc_item_number=prefix_num,
                            section_title=current_section,
                            section_hierarchy=list(hierarchy),
                            raw_text=full_text,
                            page=page_num,
                            line=source_line,
                            category="UNCERTAIN",
                            classification_reason="Numbered statement lacking explicit modal or constraint predicate",
                        )
                    )
                else:
                    context_items.append(
                        NIRRequirement(
                            doc_item_number="",
                            section_title=current_section,
                            section_hierarchy=list(hierarchy),
                            raw_text=full_text,
                            page=page_num,
                            line=source_line,
                            category="CONTEXT",
                            sub_category="SUPPORTING_TEXT",
                        )
                    )
                continue

            # 5. Standalone un-bulleted line with modal in requirement section
            if any(k in current_section.lower() for k in ("requirement", "feature", "interface", "attribute")):
                if MODAL_PATTERN.search(raw_line) or CONSTRAINT_PREDICATES.search(raw_line):
                    full_text, line_idx = collect_continuation(raw_line, line_idx)
                    requirements.append(
                        NIRRequirement(
                            doc_item_number=f"REQ-p{page_num}-l{source_line}",
                            section_title=current_section,
                            section_hierarchy=list(hierarchy),
                            raw_text=full_text,
                            page=page_num,
                            line=source_line,
                            category="REQUIREMENT",
                            classification_reason="Modal/constraint in requirement section",
                        )
                    )
                    continue

            # 6. Default: Supporting narrative explanation -> CONTEXT
            context_items.append(
                NIRRequirement(
                    doc_item_number="",
                    section_title=current_section,
                    section_hierarchy=list(hierarchy),
                    raw_text=raw_line,
                    page=page_num,
                    line=source_line,
                    category="CONTEXT",
                    sub_category="EXPLANATION",
                )
            )

    return NIRDocument(
        source_path=path,
        format="pdf",
        raw_text=raw_text,
        sections=sections if sections else [current_section],
        requirements=requirements,
        context_items=context_items,
        uncertain_items=uncertain_items,
        tables=tables,
        warnings=warnings,
        source_blocks=[{"kind": "page", "page": page["page_num"], "text": page["text"]}
                       for page in pages_data],
    )

