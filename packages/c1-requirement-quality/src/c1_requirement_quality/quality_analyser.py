"""Deterministic lexical quality checks for requirement text.

These rules report observable wording signals only. An empty result means that
no implemented rule matched; it does not establish that the requirement is
defect-free.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    """One independent lexical detector."""

    defect_type: str
    patterns: tuple[re.Pattern[str], ...]
    explanation: str


def _patterns(*expressions: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(expression, re.IGNORECASE) for expression in expressions)


RULES: tuple[Rule, ...] = (
    Rule(
        "vague",
        _patterns(
            r"\bsuitable\s+\w+(?:\s+\w+)?",
            r"\bappropriate\b",
            r"\breasonable\b",
            r"\beasy\b",
            r"\buser[- ]friendly\b",
            r"\bquickly\b",
        ),
        "The wording uses a subjective or underspecified qualifier.",
    ),
    Rule(
        "ambiguous",
        _patterns(
            r"\band/or\b",
            r"\beither\b[^.;,]*?\bor\b",
            r"\b(?:may|might|could)\b",
            r"\bas needed\b",
        ),
        "The wording permits multiple interpretations or leaves the choice open.",
    ),
    Rule(
        "incomplete",
        _patterns(
            r"\b(?:TBD|TBC)\b",
            r"\bto be (?:determined|defined|decided)\b",
            r"\[(?:[^\]])+\]",
        ),
        "The wording contains an explicit placeholder or unresolved decision.",
    ),
    Rule(
        "non_measurable",
        _patterns(
            r"\bquickly\b",
            r"\bpromptly\b",
            r"\befficiently\b",
            r"\bhigh[- ]performance\b",
            r"\bwithin a reasonable time\b",
        ),
        "The wording states a qualitative target without a measurable threshold.",
    ),
    Rule(
        "non_verifiable",
        _patterns(
            r"\bsecure\b",
            r"\breliable\b",
            r"\brobust\b",
            r"\bscalable\b",
            r"\bintuitive\b",
            r"\buser[- ]friendly\b",
        ),
        "The wording states a quality attribute without an objective verification criterion.",
    ),
)

QUANTITATIVE_RELIABILITY_PATTERN = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*%\s+(?:monthly\s+)?availability|"
    r"(?:availability|reliability)\s+(?:of\s+at least|of|at least|>=)\s*"
    r"\d+(?:\.\d+)?\s*%)",
    re.IGNORECASE,
)


def _findings_for_rule(text: str, rule: Rule) -> Iterable[dict[str, str]]:
    for pattern in rule.patterns:
        for match in pattern.finditer(text):
            yield {
                "type": rule.defect_type,
                "detector": "rule",
                "evidence_span": match.group(0),
                "explanation": rule.explanation,
            }


def _is_contextually_supported(text: str, finding: dict[str, str]) -> bool:
    return (
        finding["type"] == "non_verifiable"
        and finding["evidence_span"].lower() == "reliable"
        and QUANTITATIVE_RELIABILITY_PATTERN.search(text) is not None
    )


def analyse_requirement(text: str) -> list[dict[str, str]]:
    """Return deterministic, contract-shaped findings for one requirement."""
    if not text.strip():
        raise ValueError("Requirement text must not be empty")

    findings: list[dict[str, str]] = []
    for rule in RULES:
        findings.extend(
            finding
            for finding in _findings_for_rule(text, rule)
            if not _is_contextually_supported(text, finding)
        )
    return findings


def analyse_requirements(
    texts: Iterable[str],
) -> list[list[dict[str, str]]]:
    """Analyse each requirement independently, preserving input order."""
    return [analyse_requirement(text) for text in texts]
