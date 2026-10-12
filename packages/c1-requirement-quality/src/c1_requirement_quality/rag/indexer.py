"""SRS document chunking and indexing for RAG grounding analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

HEADING_PATTERN = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class SRSChunk:
    """A traceable evidence chunk extracted from a Markdown SRS document."""

    chunk_id: str
    text: str
    section: str | None
    start_line: int
    end_line: int
    embedding: tuple[float, ...] | None = None

    def to_dict(self) -> dict[str, object]:
        """Export chunk fields to a schema-compatible dictionary."""
        res: dict[str, object] = {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }
        if self.section is not None:
            res["section"] = self.section
        if self.embedding is not None:
            res["embedding"] = list(self.embedding)
        return res


class SRSIndexer:
    """Parses and chunks Markdown SRS documents with section breadcrumb tracking."""

    def __init__(self, srs_text: str) -> None:
        if not isinstance(srs_text, str):
            raise TypeError("srs_text must be a string")
        self.srs_text = srs_text

    def chunk_document(self) -> list[SRSChunk]:
        """Split srs_text into traceable evidence chunks with section breadcrumbs."""
        lines = self.srs_text.splitlines(keepends=True)
        chunks: list[SRSChunk] = []
        heading_stack: dict[int, str] = {}
        block_lines: list[tuple[int, str]] = []

        def flush_block() -> None:
            if not block_lines:
                return
            first_line = block_lines[0][0]
            last_line = block_lines[-1][0]
            chunk_id = f"SRS-L{first_line:04d}-L{last_line:04d}"
            block_text = "".join(line for _, line in block_lines).strip()
            if block_text:
                breadcrumb = (
                    " > ".join(title for _, title in sorted(heading_stack.items()))
                    if heading_stack
                    else None
                )
                chunks.append(
                    SRSChunk(
                        chunk_id=chunk_id,
                        text=block_text,
                        section=breadcrumb,
                        start_line=first_line,
                        end_line=last_line,
                    )
                )
            block_lines.clear()

        for line_number, raw_line in enumerate(lines, start=1):
            content = raw_line.rstrip("\r\n")
            heading_match = HEADING_PATTERN.match(content)
            if heading_match:
                flush_block()
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                # Clear deeper or equal heading levels
                heading_stack = {
                    lvl: t for lvl, t in heading_stack.items() if lvl < level
                }
                heading_stack[level] = title
            elif content.strip():
                block_lines.append((line_number, raw_line))
            else:
                flush_block()
        flush_block()

        return chunks

    def compute_embeddings(self, embedder: Any = None) -> list[SRSChunk]:
        """Placeholder interface for local sentence embedding generation.

        In Task 2, no embedding models are loaded or downloaded. When embedder is None,
        returns chunk_document() output with embedding=None.
        """
        chunks = self.chunk_document()
        if embedder is None:
            return chunks
        # Future task will invoke embedder.encode() here.
        return chunks


def index_srs(srs_text: str) -> list[SRSChunk]:
        """Convenience function to chunk an SRS text into traceable SRSChunk objects."""
        return SRSIndexer(srs_text).chunk_document()
