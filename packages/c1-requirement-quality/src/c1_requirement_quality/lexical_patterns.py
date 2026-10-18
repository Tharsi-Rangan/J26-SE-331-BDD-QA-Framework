"""Canonical compiled lexical patterns for requirement quality and refinement."""
from __future__ import annotations

import re

# Keep symbolic comparisons distinct in conservative identity checks. Unknown
# operators remain literal tokens; recognizing one never implies numeric proof.
COMPARISON_TOKEN_PATTERN = re.compile(
    r"[<>!=]=?|[≤≥≠]|\d+(?:\.\d+)?|[a-z]+(?:'[a-z]+)?", re.IGNORECASE
)

# Placeholder markers: bracketed tokens like [PLACEHOLDER] and explicit TBD/TBC markers.
PLACEHOLDER_PATTERN: re.Pattern[str] = re.compile(
    r"\[[^\]]+\]|\bTBD\b|\bTBC\b", re.IGNORECASE
)
