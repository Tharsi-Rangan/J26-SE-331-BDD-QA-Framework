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


from c1_requirement_quality.ingest import extract_srs_requirements


def extract_requirements(path: Path) -> list[dict[str, object]]:
    """Extract requirement text and source locations without assigning IDs."""
    return extract_srs_requirements(path)


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