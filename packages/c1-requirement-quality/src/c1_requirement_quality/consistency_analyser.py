"""Conservative deterministic cross-requirement consistency checks.

Only explicit, text-grounded patterns are classified as consistent or
contradictory. Unsupported comparisons remain unassessed for human review.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Mapping, Sequence
from typing import Any


_TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z]+(?:'[a-z]+)?", re.IGNORECASE)
_CONDITION = re.compile(r"\b(?:only\s+)?(?:if|when|unless)\b", re.IGNORECASE)
_BETWEEN = re.compile(
    r"\bbetween\s+(?P<low>\d+(?:\.\d+)?)\s+and\s+(?P<high>\d+(?:\.\d+)?)"
    r"(?:\s+(?P<unit>[a-zA-Z%]+))?", re.IGNORECASE,
)
_BOUND = re.compile(
    r"(?P<operator>at\s+least|no\s+less\s+than|greater\s+than|more\s+than|"
    r"at\s+most|no\s+more\s+than|less\s+than|under|over|minimum(?:\s+of)?|"
    r"maximum(?:\s+of)?|>=|<=|>|<)\s*(?P<value>\d+(?:\.\d+)?)"
    r"(?:\s*(?P<unit>%|[a-zA-Z]+))?", re.IGNORECASE,
)
_UNIT_ALIASES = {
    "seconds": "second", "secs": "second", "sec": "second",
    "minutes": "minute", "mins": "minute", "min": "minute",
    "hours": "hour", "hrs": "hour", "hr": "hour",
    "days": "day", "weeks": "week", "months": "month", "years": "year",
    "characters": "character", "chars": "character", "bytes": "byte",
    "requests": "request", "attempts": "attempt", "times": "time",
    "users": "user", "records": "record", "items": "item",
    "percent": "%", "percentage": "%",
}
_MODAL = frozenset({"shall", "must"})
_NEGATIVE_MODAL = re.compile(r"\b(?:shall|must)\s+not\b", re.IGNORECASE)
_OPPOSING_ACTIONS = {
    "allow": ("allow", 1), "permit": ("allow", 1),
    "deny": ("allow", -1), "prohibit": ("allow", -1), "forbid": ("allow", -1),
    "enable": ("enable", 1), "disable": ("enable", -1),
    "accept": ("accept", 1), "reject": ("accept", -1),
    "include": ("include", 1), "exclude": ("include", -1),
}


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token.lower() for token in _TOKEN.findall(text))


def _condition_parts(text: str) -> tuple[str, str]:
    match = _CONDITION.search(text)
    if match is None:
        return text, ""
    return text[:match.start()], " ".join(_tokens(text[match.start():]))


def _unit_key(unit: str | None) -> str | None:
    if unit is None:
        return None
    lowered = unit.lower()
    if lowered in _UNIT_ALIASES:
        return _UNIT_ALIASES[lowered]
    if lowered.endswith("s") and lowered[:-1] in _UNIT_ALIASES:
        return _UNIT_ALIASES[lowered[:-1]]
    return lowered


def _bound_for(operator: str, value: float) -> tuple[float | None, bool, float | None, bool]:
    op = " ".join(operator.lower().split())
    if op in {"at least", "no less than", "minimum", "minimum of", ">="}:
        return value, True, None, False
    if op in {"greater than", "more than", "over", ">"}:
        return value, False, None, False
    if op in {"at most", "no more than", "maximum", "maximum of", "<="}:
        return None, False, value, True
    return None, False, value, False


def _numeric_constraint(text: str) -> dict[str, Any] | None:
    between = list(_BETWEEN.finditer(text))
    bounds = list(_BOUND.finditer(text))
    # Multiple constraints within one requirement require richer parsing.
    if len(between) + len(bounds) != 1:
        return None
    if between:
        match = between[0]
        low, high = float(match.group("low")), float(match.group("high"))
        if low > high:
            return None
        return {
            "low": low, "low_inclusive": True,
            "high": high, "high_inclusive": True,
            "unit": _unit_key(match.group("unit")),
            "span": _span(text, match.start(), match.end()),
        }
    match = bounds[0]
    low, low_inclusive, high, high_inclusive = _bound_for(
        match.group("operator"), float(match.group("value"))
    )
    return {
        "low": low, "low_inclusive": low_inclusive,
        "high": high, "high_inclusive": high_inclusive,
        "unit": _unit_key(match.group("unit")),
        "span": _span(text, match.start(), match.end()),
    }


def _span(text: str, start: int, end: int) -> dict[str, Any]:
    return {"start_offset": start, "end_offset": end, "text": text[start:end]}


def _numeric_core(text: str, constraint: Mapping[str, Any]) -> tuple[str, ...]:
    span = constraint["span"]
    without_bound = text[:span["start_offset"]] + " " + text[span["end_offset"]:]
    body, _ = _condition_parts(without_bound)
    tokens = _tokens(body)
    return tuple(token for token in tokens if token not in _MODAL)


def _intervals_conflict(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    lows = [(item["low"], item["low_inclusive"]) for item in (left, right) if item["low"] is not None]
    highs = [(item["high"], item["high_inclusive"]) for item in (left, right) if item["high"] is not None]
    if not lows or not highs:
        return False
    low_value = max(value for value, _ in lows)
    high_value = min(value for value, _ in highs)
    if low_value > high_value:
        return True
    if low_value < high_value:
        return False
    low_closed = all(inclusive for value, inclusive in lows if value == low_value)
    high_closed = all(inclusive for value, inclusive in highs if value == high_value)
    return not (low_closed and high_closed)


def _polarity_core(text: str) -> tuple[tuple[str, ...], int]:
    core, _ = _condition_parts(text)
    negative = _NEGATIVE_MODAL.search(core) is not None
    core = _NEGATIVE_MODAL.sub(" ", core)
    raw_tokens = [token for token in _tokens(core) if token not in _MODAL]
    action_matches = [index for index, token in enumerate(raw_tokens) if token in _OPPOSING_ACTIONS]
    polarity = -1 if negative else 1
    if len(action_matches) == 1:
        index = action_matches[0]
        canonical, action_polarity = _OPPOSING_ACTIONS[raw_tokens[index]]
        raw_tokens[index] = canonical
        polarity *= action_polarity
    return tuple(raw_tokens), polarity


def _pair_result(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    left_id, right_id = str(left["requirement_id"]), str(right["requirement_id"])
    left_text, right_text = str(left["text"]), str(right["text"])
    left_core, left_condition = _condition_parts(left_text)
    right_core, right_condition = _condition_parts(right_text)
    left_tokens, right_tokens = _tokens(left_text), _tokens(right_text)
    left_evidence, right_evidence = _span(left_text, 0, len(left_text)), _span(right_text, 0, len(right_text))

    if left_tokens == right_tokens:
        return _result(left_id, right_id, "consistent", "The normalized obligations and conditions are identical.", left_evidence, right_evidence)

    left_numeric, right_numeric = _numeric_constraint(left_text), _numeric_constraint(right_text)
    if left_numeric and right_numeric and _numeric_core(left_text, left_numeric) == _numeric_core(right_text, right_numeric):
        if left_condition != right_condition:
            return _result(left_id, right_id, "unassessed", "Numeric constraints have different or unmatched conditions; overlap is not established.", left_numeric["span"], right_numeric["span"])
        if left_numeric["unit"] is None or right_numeric["unit"] is None or left_numeric["unit"] != right_numeric["unit"]:
            return _result(left_id, right_id, "potential_conflict", "The same apparent attribute has numeric constraints with missing or different units; compatibility cannot be determined.", left_numeric["span"], right_numeric["span"])
        if _intervals_conflict(left_numeric, right_numeric):
            return _result(left_id, right_id, "conflict", "The explicit bounds on the same attribute, unit, and condition have no overlapping value.", left_numeric["span"], right_numeric["span"])
        return _result(left_id, right_id, "consistent", "The explicit bounds on the same attribute, unit, and condition have a non-empty overlap.", left_numeric["span"], right_numeric["span"])

    left_polarity_core, left_polarity = _polarity_core(left_text)
    right_polarity_core, right_polarity = _polarity_core(right_text)
    if left_polarity_core and left_polarity_core == right_polarity_core:
        if left_condition != right_condition:
            return _result(left_id, right_id, "unassessed", "The obligations have different conditions or scopes; the analyzer cannot establish whether they overlap.", left_evidence, right_evidence)
        if left_polarity != right_polarity:
            return _result(left_id, right_id, "conflict", "The requirements state the same obligation under the same condition with explicit opposite grammatical negation or a supported opposing action verb.", left_evidence, right_evidence)
        return _result(left_id, right_id, "consistent", "The requirements state the same explicitly worded obligation and condition.", left_evidence, right_evidence)

    return _result(left_id, right_id, "unassessed", "No supported comparison rule matched both requirements; no consistency conclusion is inferred.", None, None)


def _result(
    left_id: str,
    right_id: str,
    classification: str,
    explanation: str,
    left_evidence: Mapping[str, Any] | None,
    right_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "requirement_ids": [left_id, right_id],
        "classification": classification,
        "analysis_state": "analyzed" if classification != "unassessed" else "unassessed",
        "explanation": explanation,
        "evidence": [
            {"requirement_id": req_id, **dict(span)}
            for req_id, span in ((left_id, left_evidence), (right_id, right_evidence))
            if span is not None
        ],
    }


def analyse_consistency(requirements: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Analyze all unordered pairs; retain unassessed pairs explicitly.

    Inputs require stable IDs and exact requirement text. Pair order follows
    source order, making output reproducible.
    """
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, Mapping):
            raise TypeError(f"requirement at index {index} must be an object")
        requirement_id, text = requirement.get("requirement_id"), requirement.get("text")
        if not isinstance(requirement_id, str) or not requirement_id:
            raise ValueError(f"requirement at index {index} requires a non-empty requirement_id")
        if requirement_id in seen:
            raise ValueError(f"duplicate requirement_id: {requirement_id}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{requirement_id} requires non-empty text")
        seen.add(requirement_id)
        normalized.append({"requirement_id": requirement_id, "text": text})

    pairs = [_pair_result(left, right) for left, right in itertools.combinations(normalized, 2)]
    incomplete = len(normalized) < 2 or any(pair["analysis_state"] == "unassessed" for pair in pairs)
    return {
        "analysis_state": "partially_analyzed" if incomplete else "analyzed",
        "requirements_analyzed": len(normalized),
        "pairs_analyzed": sum(pair["analysis_state"] == "analyzed" for pair in pairs),
        "pairs_unassessed": sum(pair["analysis_state"] == "unassessed" for pair in pairs),
        "pairs": pairs,
    }


def consistency_for_requirement(
    requirement_id: str, analysis: Mapping[str, Any]
) -> dict[str, Any]:
    """Aggregate pair outcomes for one requirement without hiding uncertainty."""
    related: list[str] = []
    conflicts: list[dict[str, str]] = []
    relevant: list[Mapping[str, Any]] = []
    for pair in analysis.get("pairs", []):
        ids = pair.get("requirement_ids", [])
        if requirement_id not in ids:
            continue
        other_id = ids[1] if ids[0] == requirement_id else ids[0]
        relevant.append(pair)
        if pair.get("classification") != "unassessed":
            related.append(other_id)
        if pair.get("classification") == "conflict":
            evidence_text = "; ".join(
                f'{item["requirement_id"]}: {item["text"]!r}'
                for item in pair.get("evidence", [])
            )
            conflicts.append({
                "with_requirement_id": other_id,
                "explanation": (
                    str(pair.get("explanation", "Explicit contradiction detected."))
                    + (f" Evidence: {evidence_text}." if evidence_text else "")
                ),
            })

    if conflicts:
        status = "conflict"
    elif any(pair.get("classification") == "potential_conflict" for pair in relevant):
        status = "potential_conflict"
    elif relevant and all(pair.get("classification") == "consistent" for pair in relevant):
        status = "consistent"
    else:
        # The frozen contract has no unassessed status. Keep its current
        # conservative sentinel and record the real state in diagnostics.
        status = "potential_conflict"

    if conflicts:
        check = "fail"
    elif any(pair.get("analysis_state") == "unassessed" for pair in relevant) or not relevant:
        check = "skipped"
    elif status == "consistent":
        check = "pass"
    else:
        check = "skipped"
    return {
        "status": status,
        "related_requirement_ids": sorted(set(related)),
        "conflicts": conflicts,
        "check": check,
        "analysis_state": "analyzed" if check != "skipped" else "partially_analyzed",
        "requirements_analyzed": analysis.get("requirements_analyzed", 0),
        "pairs_unassessed": sum(
            pair.get("analysis_state") == "unassessed" for pair in relevant
        ),
        "pairs": [dict(pair) for pair in relevant],
    }
