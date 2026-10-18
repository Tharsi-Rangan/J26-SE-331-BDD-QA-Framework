"""Classification rules and heuristics for SRS requirement extraction quality (Phase 1A.1).

Defines three internal extraction categories:
- REQUIREMENT: identified requirement statements (functional and non-functional, modal and modal-less).
- CONTEXT: headings, TOC entries, use-case steps, explanations, and supporting text (preserved for RAG).
- UNCERTAIN: potential requirements that cannot safely be classified (preserved in diagnostics, not discarded).
"""

from __future__ import annotations

import re
from typing import Any

REQ_ID_PREFIX = re.compile(
    r"^(?:[-*•▪\u2022\u2023\u25aa\u25e6\u2043\u2219\uf0b7\ufffd\xb7]\s*)?"
    r"(?P<req_id>(?:REQ(?:UIREMENT)?(?:[-_][A-Za-z0-9.]+|\s+\d+)+|[A-Z]{2,6}(?:[-_][A-Za-z0-9.]+)+))\s*[:.-]?\s+(?P<text>.*)$",
    re.IGNORECASE,
)



MODAL_PATTERN = re.compile(
    r"\b(?:shall|must|will|should)\b",
    re.IGNORECASE,
)

CONSTRAINT_PREDICATES = re.compile(
    r"\b(?:"
    r"is\s+required|are\s+required|requires\s+that|required\s+in\s+order|"
    r"cannot\s+be|can\s+never\s+be|must\s+not|shall\s+not|may\s+not|"
    r"is\s+allowed|are\s+allowed|is\s+prohibited|is\s+forbidden|is\s+restricted|"
    r"never\s+unlocks?|no\s+backdoor|"
    r"has\s+no\s+limits|only\s+(?:one|[a-z0-9_-]+)\s+is\s+(?:allowed|used|permitted)|"
    r"expires\s+automatically|can\s+never|"
    r"is\s+identical|must\s+be\s+identical|have\s+different\s+names|"
    r"must\s+belong|must\s+be\s+selected|before\s+it\s+is\s+duplicated"
    r")\b",
    re.IGNORECASE,
)

USER_ACTION_PATTERN = re.compile(
    r"^(?:\d+[.):]\s*)?"
    r"(?:User|Customer|Actor|Operator|Admin|Client|Member|Manager|Writer|Developer|Analyst)\s+"
    r"(?:opens?|clicks?|selects?|writes?|types?|enters?|presses?|navigates?|logs?\s+in|chooses?|"
    r"drags?|drops?|confirms?|checks?|cancels?|initiates?|requests?|submits?|specifies?|views?|"
    r"retypes?|changes?|fills?|provides?)\b",
    re.IGNORECASE,
)

SYSTEM_RESPONSE_PATTERN = re.compile(
    r"^(?:\d+[.):]\s*)?"
    r"(?:The\s+system|System|The\s+database|The\s+application|The\s+server)\s+"
    r"(?:shall|must|will|should|validates?|verifies?|displays?|prompts?|stores?|encrypts?|"
    r"restores?|transmits?|sends?|generates?|blocks?|detects?|logs?)\b",
    re.IGNORECASE,
)

TOC_DOT_LEADER_PATTERN = re.compile(
    r"\.{3,}\s*\d+$|\s{3,}\d+$"
)

TOC_HEADING_PATTERN = re.compile(
    r"^(?:table\s+of\s+contents|contents|toc)$",
    re.IGNORECASE,
)

OUTLINE_HEADING_PATTERN = re.compile(
    r"^(?:(?:SECTION|CHAPTER|APPENDIX)\s+[A-Z0-9]+[:.]?\s*)?"
    r"(?:\d+(?:\.\d+)*[:.]?\s+)?(?P<title>[A-Z][A-Za-z0-9\s/&,:-]{2,70})$"
)


BULLET_PREFIX = re.compile(
    r"^\s*[-*•▪\u2022\u2023\u25aa\u25e6\u2043\u2219\uf0b7\ufffd\xb7]\s*"
)

NUMBERED_PREFIX = re.compile(
    r"^\s*(?P<num>\d+(?:\.\d+)*)(?:[.):]|\s+-|\s)\s*"
)


PAGE_NUM_ONLY = re.compile(
    r"^\s*(?:page\s+)?\d+(?:\s*(?:of|/)\s*\d+)?\s*$",
    re.IGNORECASE,
)

INTRODUCTORY_SECTIONS = (
    "purpose",
    "scope",
    "conventions",
    "intended audience",
    "reading suggestions",
    "references",
    "product perspective",
    "product features",
    "product functions",
    "overall description",
    "user classes",
    "user documentation",
    "glossary",
    "definitions",
    "document overview",
)

USE_CASE_SECTION_KEYWORDS = (
    "use case",
    "flow",
    "scenario",
    "workflow",
    "stimulus",
    "sequence",
)

REQUIREMENT_SECTION_KEYWORDS = (
    "requirement",
    "functional",
    "quality attribute",
    "nonfunctional",
    "interface",
    "performance",
    "security",
    "safety",
    "reliability",
    "usability",
    "maintainability",
    "portability",
    "testability",
    "hardware",
    "software interfaces",
    "communications interfaces",
    "design and implementation constraints",
    "operating environment",
    "assumptions and dependencies",
)


def is_introductory_section(sec: str) -> bool:
    """Check if section is an IEEE 830 / ISO 29148 introductory or overview section."""
    s = sec.lower()
    return any(intro in s for intro in INTRODUCTORY_SECTIONS)


def is_use_case_section(sec: str) -> bool:
    """Check if section is a use-case, workflow, or scenario data flow section."""
    s = sec.lower()
    return any(kw in s for kw in USE_CASE_SECTION_KEYWORDS)


def is_requirement_section(sec: str) -> bool:
    """Check if section typically contains normative functional/non-functional requirements."""
    s = sec.lower()
    return any(kw in s for kw in REQUIREMENT_SECTION_KEYWORDS)


def detect_repeated_headers_footers(pages_data: list[dict[str, Any]]) -> set[str]:
    """Detect running headers/footers repeated across >= 20% of pages (min 3 pages)."""
    from collections import Counter

    top_candidates: Counter[str] = Counter()
    bottom_candidates: Counter[str] = Counter()
    total_pages = len(pages_data)
    if total_pages < 2:
        return set()

    for p in pages_data:
        lines = [l.strip() for l in p.get("text", "").splitlines() if l.strip()]
        if not lines:
            continue
        for l in lines[:2]:
            top_candidates[l] += 1
        for l in lines[-2:]:
            bottom_candidates[l] += 1

    repeated: set[str] = set()
    threshold = max(3, int(total_pages * 0.20))
    for line, count in top_candidates.items():
        if count >= threshold:
            repeated.add(line)
    for line, count in bottom_candidates.items():
        if count >= threshold:
            repeated.add(line)
    return repeated
