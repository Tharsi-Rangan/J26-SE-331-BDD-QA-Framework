"""Conservative, deterministic grounding checks against supplied SRS text.

This module only recognizes exact normalized claim matches and narrow conflicts
where otherwise identical claims differ in negation or numeric values. It does
not infer semantic equivalence from general lexical overlap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
CLAIM_SEPARATOR = re.compile(r"(?<=[.!?])(?:[ \t]+|\r?\n+)|;|\r?\n+")
TOKEN_PATTERN = re.compile(r"\d+(?:\.\d+)?|[a-z]+(?:'[a-z]+)?", re.IGNORECASE)
NEGATION_TOKENS = frozenset({"no", "not", "never"})


@dataclass(frozen=True)
class _SourceClaim:
    text: str
    chunk_id: str
    section: str | None


def _split_claims(text: str) -> list[str]:
    """Split simple sentence-like claims while retaining their exact wording."""
    claims: list[str] = []
    start = 0
    for separator in CLAIM_SEPARATOR.finditer(text):
        claim = text[start : separator.start()].strip()
        if claim:
            claims.append(claim)
        start = separator.end()
    final_claim = text[start:].strip()
    if final_claim:
        claims.append(final_claim)
    return claims


def _normal_form(text: str) -> tuple[str, ...]:
    return tuple(token.lower() for token in TOKEN_PATTERN.findall(text))


def _conflict_signature(text: str) -> tuple[tuple[str, ...], frozenset[str], tuple[str, ...]]:
    tokens = _normal_form(text)
    negation = frozenset(token for token in tokens if token in NEGATION_TOKENS)
    numbers = tuple(token for token in tokens if token[0].isdigit())
    content = tuple(
        token
        for token in tokens
        if token not in NEGATION_TOKENS and not token[0].isdigit()
    )
    return content, negation, numbers


def _are_narrowly_contradictory(left: str, right: str) -> bool:
    left_content, left_negation, left_numbers = _conflict_signature(left)
    right_content, right_negation, right_numbers = _conflict_signature(right)
    if not left_content or left_content != right_content:
        return False
    negation_conflict = left_negation != right_negation
    numeric_conflict = bool(left_numbers and right_numbers and left_numbers != right_numbers)
    return negation_conflict or numeric_conflict


def _source_claims(srs_text: str) -> list[_SourceClaim]:
    """Chunk non-heading SRS text and retain stable line-based trace IDs."""
    lines = srs_text.splitlines(keepends=True)
    claims: list[_SourceClaim] = []
    section: str | None = None
    block_lines: list[tuple[int, str]] = []

    def flush_block() -> None:
        if not block_lines:
            return
        first_line = block_lines[0][0]
        last_line = block_lines[-1][0]
        chunk_id = f"SRS-L{first_line:04d}-L{last_line:04d}"
        block_text = "".join(line for _, line in block_lines)
        claims.extend(
            _SourceClaim(text=claim, chunk_id=chunk_id, section=section)
            for claim in _split_claims(block_text)
        )
        block_lines.clear()

    for line_number, raw_line in enumerate(lines, start=1):
        content = raw_line.rstrip("\r\n")
        heading = HEADING_PATTERN.match(content)
        if heading:
            flush_block()
            section = heading.group(1).strip()
        elif content.strip():
            block_lines.append((line_number, raw_line))
        else:
            flush_block()
    flush_block()
    return claims


def analyse_grounding(candidate_text: str, srs_text: str) -> dict[str, object]:
    """Compare candidate claims with supplied SRS claims, without inference.

    The result includes contract-compatible ``status`` and ``evidence`` fields,
    plus standalone diagnostics (``unsupported_claims`` and ``conflicts``).
    Evidence quotes are exact substrings of ``srs_text``. The line range is
    encoded in each stable chunk ID because the shared evidence schema has no
    separate line-range fields.
    """
    if not isinstance(candidate_text, str) or not isinstance(srs_text, str):
        raise TypeError("candidate_text and srs_text must be strings")

    candidate_claims = _split_claims(candidate_text)
    if not candidate_claims:
        return {
            "status": "not_applicable",
            "evidence": [],
            "unsupported_claims": [],
            "conflicts": [],
        }

    source_claims = _source_claims(srs_text)
    evidence: list[dict[str, str]] = []
    evidence_keys: set[tuple[str, str]] = set()
    unsupported_claims: list[str] = []
    conflicts: list[dict[str, object]] = []
    fully_supported_count = 0
    conflicted_count = 0

    def add_evidence(source_claim: _SourceClaim) -> None:
        key = (source_claim.chunk_id, source_claim.text)
        if key in evidence_keys:
            return
        evidence_keys.add(key)
        item = {
            "chunk_id": source_claim.chunk_id,
            "text": source_claim.text,
        }
        if source_claim.section is not None:
            item["section"] = source_claim.section
        evidence.append(item)

    for candidate_claim in candidate_claims:
        candidate_form = _normal_form(candidate_claim)
        matches = [
            source_claim
            for source_claim in source_claims
            if _normal_form(source_claim.text) == candidate_form
        ]
        conflicting = [
            source_claim
            for source_claim in source_claims
            if _are_narrowly_contradictory(candidate_claim, source_claim.text)
        ]

        for source_claim in matches:
            add_evidence(source_claim)
        for source_claim in conflicting:
            add_evidence(source_claim)

        if conflicting:
            conflicted_count += 1
            conflicts.append(
                {
                    "claim": candidate_claim,
                    "evidence_chunk_ids": [
                        source_claim.chunk_id for source_claim in matches + conflicting
                    ],
                }
            )
        elif matches:
            fully_supported_count += 1
        else:
            unsupported_claims.append(candidate_claim)

    if conflicted_count:
        status = "partially_supported"
    elif fully_supported_count == len(candidate_claims):
        status = "supported"
    elif fully_supported_count:
        status = "partially_supported"
    else:
        status = "unsupported"

    return {
        "status": status,
        "evidence": evidence,
        "unsupported_claims": unsupported_claims,
        "conflicts": conflicts,
    }
