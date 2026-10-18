"""Structured fact extraction from requirement text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

NEGATION_TOKENS = frozenset(
    {"not", "no", "never", "cannot", "can't", "mustn't", "won't"}
)

NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")
OPERATOR_PATTERN = re.compile(
    r"\b(?:at least|at most|less than|greater than|more than|between|up to|minimum of|maximum of|>=|<=|>|<|=)\b",
    re.IGNORECASE,
)
UNITS_PATTERN = re.compile(
    r"\b(?:years|year|days|day|old|characters|char|chars|seconds|sec|secs|minutes|min|mins|hours|percent|%|users|attempts|bytes|MB|GB)\b",
    re.IGNORECASE,
)
CONSTRAINT_PATTERN = re.compile(
    r"(?P<operator>between|at least|at most|less than|greater than|more than|up to|minimum of|maximum of|>=|<=|>|<|=)\s*"
    r"(?P<first>\d+(?:\.\d+)?)"
    r"(?:\s+and\s+(?P<second>\d+(?:\.\d+)?))?"
    r"(?:\s+(?:failed|unsuccessful)\s*)?(?:\s*(?P<unit>years?|days?|old|characters?|chars?|seconds?|secs?|minutes?|mins?|hours?|percent|%|users|attempts|bytes|units?|MB|GB))?",
    re.IGNORECASE,
)
CONDITION_PATTERN = re.compile(
    r"\b(?:if|when|unless|provided that|where)\b\s+[^,.!;]+", re.IGNORECASE
)
CLAUSE_SEPARATOR = re.compile(r"(?<=[.!?])\s+|;|\r?\n+")
ACTOR_PATTERN = re.compile(
    r"\b(?:the system|the user|users|administrators|admin|members|member|the application|the service)\b",
    re.IGNORECASE,
)
ACTION_PATTERN = re.compile(
    r"\b(?:shall|must|should|may|can)\s+(?:not\s+)?([a-z]+(?:\s+[a-z]+)?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NumericConstraint:
    """One explicit numeric comparison and its locally associated values/unit."""

    raw_text: str
    operator: str | None
    values: tuple[str, ...]
    unit: str | None


@dataclass(frozen=True)
class Fact:
    """An atomic fact extracted from requirement text.

    Fact fields represent explicitly extracted text spans without invented or assumed details.
    Legacy numeric_values, comparison_operators and units remain for caller compatibility;
    constraints provides their relationship-preserving representation.
    """

    text: str
    actor: str | None = None
    action: str | None = None
    target: str | None = None
    numeric_values: tuple[str, ...] = ()
    comparison_operators: tuple[str, ...] = ()
    units: tuple[str, ...] = ()
    constraints: tuple[NumericConstraint, ...] = ()
    conditions: tuple[str, ...] = ()
    is_negated: bool = False
    start_offset: int = 0
    end_offset: int = 0

    def to_dict(self) -> dict[str, object]:
        """Export fact attributes to a dictionary representation."""
        res: dict[str, object] = {
            "text": self.text,
            "is_negated": self.is_negated,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
        }
        if self.actor is not None:
            res["actor"] = self.actor
        if self.action is not None:
            res["action"] = self.action
        if self.target is not None:
            res["target"] = self.target
        if self.numeric_values:
            res["numeric_values"] = list(self.numeric_values)
        if self.comparison_operators:
            res["comparison_operators"] = list(self.comparison_operators)
        if self.units:
            res["units"] = list(self.units)
        if self.constraints:
            res["constraints"] = [
                {"raw_text": c.raw_text, "operator": c.operator,
                 "values": list(c.values), "unit": c.unit}
                for c in self.constraints
            ]
        if self.conditions:
            res["conditions"] = list(self.conditions)
        return res


def _get_spacy_nlp() -> Any | None:
    """Lazy-load spaCy model if available, returning None if uninstalled or unmodelled."""
    try:
        import spacy

        try:
            return spacy.load("en_core_web_sm")
        except Exception:
            return None
    except ImportError:
        return None


class FactExtractor:
    """Extracts structured atomic facts from requirement text."""

    def __init__(self, use_spacy: bool = True) -> None:
        self.nlp = _get_spacy_nlp() if use_spacy else None

    def _split_clauses(self, text: str) -> list[tuple[str, int, int]]:
        """Split text into clause spans with start and end character offsets."""
        clauses: list[tuple[str, int, int]] = []
        start = 0
        for match in CLAUSE_SEPARATOR.finditer(text):
            raw = text[start : match.start()]
            left = len(raw) - len(raw.lstrip())
            clause = raw.strip()
            if clause:
                c_start = start + left
                clauses.append((clause, c_start, c_start + len(clause)))
            start = match.end()
        raw = text[start:]
        left = len(raw) - len(raw.lstrip())
        final_clause = raw.strip()
        if final_clause:
            c_start = start + left
            c_end = c_start + len(final_clause)
            clauses.append((final_clause, c_start, c_end))
        return clauses

    def extract_facts(self, text: str) -> list[Fact]:
        """Extract atomic facts from input text."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        cleaned = text.strip()
        if not cleaned:
            return []

        clause_spans = self._split_clauses(text)
        facts: list[Fact] = []

        for clause_text, start_offset, end_offset in clause_spans:
            tokens = set(re.findall(r"\b[a-z']+\b", clause_text.lower()))
            is_negated = bool(tokens & NEGATION_TOKENS)

            nums = tuple(NUMBER_PATTERN.findall(clause_text))
            ops = tuple(OPERATOR_PATTERN.findall(clause_text))
            units = tuple(UNITS_PATTERN.findall(clause_text))
            constraints = tuple(
                NumericConstraint(
                    raw_text=m.group(0),
                    operator=m.group("operator"),
                    values=tuple(v for v in (m.group("first"), m.group("second")) if v),
                    unit=m.group("unit"),
                )
                for m in CONSTRAINT_PATTERN.finditer(clause_text)
            )
            conds = tuple(c.strip() for c in CONDITION_PATTERN.findall(clause_text))

            actor: str | None = None
            action: str | None = None
            target: str | None = None

            # Attempt spaCy parsing if model is available
            if self.nlp is not None:
                try:
                    doc = self.nlp(clause_text)
                    for token in doc:
                        if token.dep_ in ("nsubj", "nsubjpass") and actor is None:
                            actor = token.text
                        elif token.pos_ == "VERB" and action is None:
                            action = token.text
                        elif token.dep_ in ("dobj", "pobj", "attr") and target is None:
                            target = token.text
                except (OSError, RuntimeError, ValueError):
                    # Keep deterministic regex extraction available if local parsing fails.
                    actor = action = target = None

            # Fallback to deterministic regex matching if spacy parsing produced no actor/action
            if actor is None:
                actor_match = ACTOR_PATTERN.search(clause_text)
                if actor_match:
                    actor = actor_match.group(0)

            if action is None:
                action_match = ACTION_PATTERN.search(clause_text)
                if action_match:
                    action = action_match.group(0)
                    # Infer target from text after action if not set
                    after_action = clause_text[action_match.end():].strip()
                    if after_action and target is None:
                        target = after_action.rstrip(".!?")

            facts.append(
                Fact(
                    text=clause_text,
                    actor=actor,
                    action=action,
                    target=target,
                    numeric_values=nums,
                    comparison_operators=ops,
                    units=units,
                    constraints=constraints,
                    conditions=conds,
                    is_negated=is_negated,
                    start_offset=start_offset,
                    end_offset=end_offset,
                )
            )

        return facts


def extract_facts(text: str, use_spacy: bool = True) -> list[Fact]:
    """Convenience function to extract atomic facts from requirement text."""
    return FactExtractor(use_spacy=use_spacy).extract_facts(text)
