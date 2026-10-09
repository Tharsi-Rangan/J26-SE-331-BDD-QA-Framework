"""Extract numbered requirements from a Markdown SRS."""

from __future__ import annotations

import re
from pathlib import Path


HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
NUMBERED_REQUIREMENT_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?:REQ(?:UIREMENT)?[- ]?)?"
    r"(?P<number>\d+(?:\.\d+)*)(?:[.):]|\s+-)\s+"
    r"(?P<text>\S.*)$",
    re.IGNORECASE,
)


def extract_requirements(path: Path) -> list[dict[str, object]]:
    """Extract requirement text and source locations without assigning IDs."""
    content = path.read_text(encoding="utf-8-sig")
    requirements: list[dict[str, object]] = []
    section = "Unspecified"
    seen_numbers: set[str] = set()

    for line_number, line in enumerate(content.splitlines(), start=1):
        heading = HEADING_PATTERN.match(line)
        if heading:
            section = heading.group(1).strip()
            continue

        match = NUMBERED_REQUIREMENT_PATTERN.match(line)
        if not match:
            continue

        source_number = match.group("number")
        text = match.group("text").strip()

        if source_number in seen_numbers:
            raise ValueError(
                f"Duplicate requirement number {source_number} "
                f"at line {line_number}"
            )

        seen_numbers.add(source_number)
        requirements.append(
            {
                "source": {"section": section, "line": line_number},
                "original_text": text,
            }
        )

    return requirements


def parse_srs(path: Path, project_code: str) -> list[dict[str, object]]:
    """Extract requirements and assign provisional IDs.

    This compatibility function preserves the existing parser interface.
    Persistent ID assignment will be handled by the registry in the CLI.
    """
    if not re.fullmatch(r"[A-Z0-9]{2,10}", project_code):
        raise ValueError(
            "project_code must contain 2-10 uppercase letters or digits"
        )

    requirements = extract_requirements(path)

    for index, requirement in enumerate(requirements, start=1):
        requirement["requirement_id"] = f"REQ-{project_code}-{index:03d}"

    return requirements