"""Markdown and plain text SRS loader with multiline, table, and hierarchy support."""

from __future__ import annotations

import re
from pathlib import Path

from c1_requirement_quality.ingest.models import (
    ExtractionWarning,
    NIRDocument,
    NIRRequirement,
    NIRTable,
)

HEADING_ATX = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
SETEXT_DASH = re.compile(r"^\s{0,3}-{3,}\s*$")
SETEXT_EQUAL = re.compile(r"^\s{0,3}={3,}\s*$")

NUMBERED_REQ_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?P<number>(?:REQ(?:UIREMENT)?[- ]?)?\d+(?:\.\d+)*|[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+)(?:[.):]|\s+-)?\s+(?P<text>\S.*)$",
    re.IGNORECASE,
)

EXPLICIT_REQ_ID_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?P<id>REQ-[A-Za-z0-9_-]+)[:.]?\s+(?P<text>\S.*)$",
    re.IGNORECASE,
)

TABLE_ROW_PATTERN = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_SEP_PATTERN = re.compile(r"^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")


def _is_table_row(line: str) -> bool:
    return bool(TABLE_ROW_PATTERN.match(line))


def _parse_table_cells(line: str) -> list[str]:
    match = TABLE_ROW_PATTERN.match(line)
    if not match:
        return []
    inner = match.group(1)
    return [c.strip() for c in inner.split("|")]


def load_markdown_srs(path: Path) -> NIRDocument:
    """Load and parse an SRS document in Markdown format."""
    content = path.read_text(encoding="utf-8-sig")
    lines = content.splitlines()

    sections: list[str] = []
    hierarchy_stack: list[tuple[int, str]] = []  # (level, title)
    current_section = "Unspecified"
    
    requirements: list[NIRRequirement] = []
    tables: list[NIRTable] = []
    warnings: list[ExtractionWarning] = []
    
    seen_in_section: set[str] = set()

    def get_current_hierarchy() -> list[str]:
        return [title for _, title in hierarchy_stack] if hierarchy_stack else [current_section]

    def set_new_heading(level: int, title: str):
        nonlocal current_section, hierarchy_stack, seen_in_section
        while hierarchy_stack and hierarchy_stack[-1][0] >= level:
            hierarchy_stack.pop()
        hierarchy_stack.append((level, title))
        current_section = title
        if title not in sections:
            sections.append(title)
        seen_in_section = set()

    i = 0
    num_lines = len(lines)

    while i < num_lines:
        line = lines[i]
        line_num = i + 1

        # 1. Check Setext Headings (line followed by === or ---)
        if i + 1 < num_lines and line.strip() and not _is_table_row(line):
            next_line = lines[i + 1]
            if SETEXT_EQUAL.match(next_line):
                title = line.strip()
                set_new_heading(1, title)
                i += 2
                continue
            if SETEXT_DASH.match(next_line) and not NUMBERED_REQ_PATTERN.match(line):
                title = line.strip()
                set_new_heading(2, title)
                i += 2
                continue

        # 2. Check ATX Headings (# Heading)
        atx_match = HEADING_ATX.match(line)
        if atx_match:
            hashes, title = atx_match.groups()
            set_new_heading(len(hashes), title.strip())
            i += 1
            continue

        # 3. Check Table Block
        if _is_table_row(line):
            table_lines: list[tuple[int, str]] = []
            while i < num_lines and _is_table_row(lines[i]):
                table_lines.append((i + 1, lines[i]))
                i += 1

            if len(table_lines) >= 2 and TABLE_SEP_PATTERN.match(table_lines[1][1]):
                headers = _parse_table_cells(table_lines[0][1])
                data_rows: list[list[str]] = []
                table_id = f"Table-{len(tables) + 1}"
                table_start_line = table_lines[0][0]

                for row_idx, (r_line_num, r_line) in enumerate(table_lines[2:], start=1):
                    row_cells = _parse_table_cells(r_line)
                    data_rows.append(row_cells)

                    # Inspect if this table row represents a requirement
                    # Look for explicit ID column or requirement indicator
                    req_id_val = ""
                    req_text_val = ""
                    
                    id_col_idx = -1
                    text_col_idx = -1

                    for c_idx, h_name in enumerate(headers):
                        h_lower = h_name.lower()
                        if any(k in h_lower for k in ("req", "id", "item", "#", "number")) and id_col_idx == -1:
                            id_col_idx = c_idx
                        elif any(k in h_lower for k in ("requirement", "statement", "description", "specification", "shall", "text")) and text_col_idx == -1:
                            text_col_idx = c_idx

                    if id_col_idx >= 0 and id_col_idx < len(row_cells):
                        req_id_val = row_cells[id_col_idx]
                    if text_col_idx >= 0 and text_col_idx < len(row_cells):
                        req_text_val = row_cells[text_col_idx]

                    # If no distinct text column was detected, check if any cell contains "shall", "must", or requirement text
                    if not req_text_val:
                        for cell in row_cells:
                            if any(modal in cell.lower() for modal in ("shall", "must", "will", "should")):
                                req_text_val = cell
                                break

                    # If no single prose text column exists but an explicit requirement ID column is present,
                    # concatenate non-ID column values with headers verbatim (without inventing synthetic prose)
                    if not req_text_val and req_id_val:
                        non_id_parts = [
                            f"[{headers[c_i]}: {row_cells[c_i]}]" if c_i < len(headers) and headers[c_i] else row_cells[c_i]
                            for c_i in range(len(row_cells))
                            if c_i != id_col_idx and row_cells[c_i]
                        ]
                        if non_id_parts:
                            req_text_val = " ".join(non_id_parts)

                    # If row has clear requirement characteristics
                    if req_text_val and (req_id_val or any(modal in req_text_val.lower() for modal in ("shall", "must"))):
                        doc_item = req_id_val if req_id_val else f"{table_id}-R{row_idx}"
                        requirements.append(
                            NIRRequirement(
                                doc_item_number=doc_item,
                                section_title=current_section,
                                section_hierarchy=get_current_hierarchy(),
                                raw_text=req_text_val.strip(),
                                page=None,
                                line=r_line_num,
                                table_id=table_id,
                                provenance_notes=f"Row {row_idx}",
                            )
                        )

                table_obj = NIRTable(
                    table_id=table_id,
                    headers=headers,
                    rows=data_rows,
                    page=None,
                    line=table_start_line,
                    raw_markdown="\n".join(tl[1] for tl in table_lines),
                )
                tables.append(table_obj)
            continue

        # 4. Check Numbered Requirement or Explicit REQ ID
        num_match = NUMBERED_REQ_PATTERN.match(line)
        id_match = EXPLICIT_REQ_ID_PATTERN.match(line) if not num_match else None

        if num_match or id_match:
            if num_match:
                source_number = num_match.group("number")
                initial_text = num_match.group("text").strip()
            else:
                source_number = id_match.group("id")  # type: ignore[union-attr]
                initial_text = id_match.group("text").strip()  # type: ignore[union-attr]

            # Duplicate check within current section (preserves backward compatibility)
            if source_number in seen_in_section:
                raise ValueError(
                    f"Duplicate requirement number {source_number} "
                    f"at line {line_num}"
                )
            seen_in_section.add(source_number)

            req_line_start = line_num
            collected_text_lines = [initial_text]
            i += 1

            # 5. Multiline Requirement Accumulation
            while i < num_lines:
                cand_line = lines[i]
                stripped = cand_line.strip()

                if not stripped:
                    # Lookahead: is the line after blank indented or a bullet?
                    if i + 1 < num_lines and (
                        lines[i + 1].startswith("  ")
                        or lines[i + 1].startswith("\t")
                        or lines[i + 1].strip().startswith(("-", "*", "•"))
                    ):
                        i += 1
                        continue
                    else:
                        break

                # Stop if next line is a heading, table, or new numbered requirement
                if HEADING_ATX.match(cand_line):
                    break
                if i + 1 < num_lines and (SETEXT_EQUAL.match(lines[i + 1]) or SETEXT_DASH.match(lines[i + 1])):
                    break
                if _is_table_row(cand_line):
                    break
                if NUMBERED_REQ_PATTERN.match(cand_line) or EXPLICIT_REQ_ID_PATTERN.match(cand_line):
                    break

                # If indented continuation text or sub-bullet
                if cand_line.startswith(("  ", "\t")) or cand_line.startswith((" -", " *", " +", " •")):
                    collected_text_lines.append(stripped)
                    i += 1
                else:
                    break

            full_req_text = " ".join(collected_text_lines)
            requirements.append(
                NIRRequirement(
                    doc_item_number=source_number,
                    section_title=current_section,
                    section_hierarchy=get_current_hierarchy(),
                    raw_text=full_req_text,
                    page=None,
                    line=req_line_start,
                    table_id=None,
                )
            )
            continue

        i += 1

    return NIRDocument(
        source_path=path,
        format="markdown",
        raw_text=content,
        sections=sections if sections else [current_section],
        requirements=requirements,
        tables=tables,
        warnings=warnings,
    )
