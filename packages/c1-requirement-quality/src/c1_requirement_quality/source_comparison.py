"""Comparison-only views of explicit source labels; never modify source evidence."""
from __future__ import annotations

from dataclasses import dataclass
import re


_LABEL = r"(?:LIB|FR|NFR|REQ(?:-[A-Z][A-Z0-9]*)?)[- ]\d+"
_PREFIX = re.compile(rf"^\s*{_LABEL}(?:[.:)])?\s+(?P<body>.+)\Z", re.I | re.S)
_ID = re.compile(rf"{_LABEL}(?:[.:)])?", re.I)
# An identifier used as the subject ("LIB-001 shall ...") is not a label.
# Require a separately stated subject, rather than removing arbitrary ID tokens.
_OBLIGATION = re.compile(
    r"^(?:the\s+|an?\s+|users?\b|members?\b|administrators?\b|students?\b|librarians?\b)"
    r"[^.!?;]*\b(?:shall|must|should|may|can|will)\b", re.I,
)
_ID_HEADERS = {"id", "requirement id", "req id"}
_TEXT_HEADERS = {"statement", "requirement", "description", "requirement text", "text"}


def obligation_text(text: str) -> str:
    """Ignore only a known leading label followed by an independent obligation.

    The returned value is a substring used for comparison, not an evidence quote.
    Unknown prefixes and identifiers within the obligation remain literal.
    """
    match = _PREFIX.fullmatch(text)
    if match and _OBLIGATION.match(match["body"]):
        return match["body"]
    return text


@dataclass(frozen=True)
class SourceComparison:
    text: str
    comparison_text: str
    start_offset: int
    end_offset: int


def source_comparisons(text: str) -> list[SourceComparison]:
    """Recognize a complete two-column ID/statement table, otherwise keep text.

    Table comparisons retain whole literal rows and offsets into the original
    passage. No retrieval chunks are split or renamed. Unsupported/ambiguous
    tables fall back to the unchanged passage, never guessed cell selection.
    """
    rows = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped:
            if not (stripped.startswith("|") and stripped.endswith("|")):
                break
            cells = [cell.strip() for cell in stripped[1:-1].split("|")]
            if len(cells) != 2:
                break
            start = offset + len(line) - len(line.lstrip())
            rows.append((cells, stripped, start))
        offset += len(line)
    else:
        if len(rows) >= 3:
            headers = [" ".join(c.casefold().replace("_", " ").replace("-", " ").split()) for c in rows[0][0]]
            id_columns = [i for i, c in enumerate(headers) if c in _ID_HEADERS]
            text_columns = [i for i, c in enumerate(headers) if c in _TEXT_HEADERS]
            if (len(id_columns) == len(text_columns) == 1
                    and id_columns[0] != text_columns[0]
                    and all(re.fullmatch(r":?-{3,}:?", c) for c in rows[1][0])):
                views = []
                for cells, quote, start in rows[2:]:
                    body = cells[text_columns[0]]
                    if not (_ID.fullmatch(cells[id_columns[0]]) and _OBLIGATION.match(body)):
                        break
                    views.append(SourceComparison(quote, body, start, start + len(quote)))
                else:
                    return views
    return [SourceComparison(text, obligation_text(text), 0, len(text))]
