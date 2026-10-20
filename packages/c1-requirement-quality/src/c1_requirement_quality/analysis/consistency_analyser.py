"""Conservative deterministic cross-requirement consistency checks.

Only explicit, text-grounded patterns are classified as consistent or
conflicting. Unsupported comparisons remain unassessed for human review.
"""

from __future__ import annotations

import itertools
import re
from decimal import Decimal
from collections.abc import Mapping, Sequence
from typing import Any
from c1_requirement_quality.lexical_patterns import COMPARISON_TOKEN_PATTERN


_TOKEN = COMPARISON_TOKEN_PATTERN
POLICY_VERSION = "deterministic-consistency-policy-definitions-v2"
_NUMBER_WORDS = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split(),
    range(21), strict=True,
))
_VALUE = r"(?:\d+(?:\.\d+)?|" + "|".join(_NUMBER_WORDS) + r")(?![\w-])"
_CONDITION = re.compile(r"\b(?:only\s+)?(?:if|when|unless)\b", re.IGNORECASE)
_BETWEEN = re.compile(
    rf"\bbetween\s+(?P<low>{_VALUE})\s+and\s+(?P<high>{_VALUE})"
    r"(?:\s+(?P<unit>[a-zA-Z%]+))?", re.IGNORECASE,
)
_BOUND = re.compile(
    r"(?P<operator>at\s+least|no\s+less\s+than|greater\s+than|more\s+than|"
    r"at\s+most|no\s+more\s+than|less\s+than|under|over|minimum(?:\s+of)?|"
    rf"maximum(?:\s+of)?|>=|<=|>|<)\s*(?P<value>{_VALUE})"
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
    "books": "book", "loans": "loan",
    "percent": "%", "percentage": "%",
}
_KNOWN_UNITS = set(_UNIT_ALIASES) | set(_UNIT_ALIASES.values())
# These complete templates assert a permission ceiling or assign a named policy
# parameter. Ordinary "at most" bounds remain interval constraints.
_POLICY_DEFINITIONS = (
    re.compile(rf"(?P<subject>(?:a|an|the) [a-z][a-z0-9 '-]*?)\s+(?:shall|must)\s+be allowed to "
               rf"(?P<action>borrow|hold|reserve) a maximum of (?P<value>{_VALUE}) "
               rf"(?P<unit>books?|loans?|items?) at a time"
               r"(?P<condition> (?:if|when|unless) [^.!?;]+)?\.?", re.I),
    re.compile(rf"(?P<subject>the (?:maximum|minimum) [a-z][a-z0-9 '-]*?)\s+(?:shall|must)\s+be "
               rf"(?:exactly )?(?P<value>{_VALUE}) (?P<unit>[a-z]+|%)"
               r"(?P<condition> (?:if|when|unless) [^.!?;]+)?\.?", re.I),
)
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


def _number(value: str) -> float:
    return float(_NUMBER_WORDS[value.lower()]) if value.lower() in _NUMBER_WORDS else float(value)


def _policy_definition(text: str) -> dict[str, Any] | None:
    for template, pattern in enumerate(_POLICY_DEFINITIONS):
        match = pattern.fullmatch(text.strip())
        if match is None or match["unit"].lower() not in _KNOWN_UNITS:
            continue
        # Only the numeric value and the template's main shall/must assignment
        # are normalized. Actor, object, units and conditions remain literal.
        key = (" ".join(match["subject"].casefold().split()), match.groupdict().get("action", "").lower(),
               match["unit"].lower(), " ".join((match["condition"] or "").casefold().split()))
        value = match["value"].lower()
        return {"key": (template, key), "value": Decimal(str(_NUMBER_WORDS[value])) if value in _NUMBER_WORDS else Decimal(value)}
    return None


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
        if (any(match[name].lower() in _NUMBER_WORDS for name in ("low", "high"))
                and (match["unit"] or "").lower() not in _KNOWN_UNITS):
            return None
        low, high = _number(match.group("low")), _number(match.group("high"))
        if low > high:
            return None
        return {
            "low": low, "low_inclusive": True,
            "high": high, "high_inclusive": True,
            "unit": _unit_key(match.group("unit")),
            "span": _span(text, match.start(), match.end()),
        }
    match = bounds[0]
    if match["value"].lower() in _NUMBER_WORDS and (match["unit"] or "").lower() not in _KNOWN_UNITS:
        return None
    low, low_inclusive, high, high_inclusive = _bound_for(
        match.group("operator"), _number(match.group("value"))
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


def _literal_numeric_scope(text: str, constraint: Mapping[str, Any]) -> str:
    """Keep identifier punctuation/conditions literal around one bound."""
    span = constraint["span"]
    body = text[:span["start_offset"]] + " BOUND " + text[span["end_offset"]:]
    body = re.sub(r"\b(?:shall|must)\b", "shall", body, count=1, flags=re.I)
    return " ".join(body.strip().rstrip(".").casefold().split())


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

    left_policy, right_policy = _policy_definition(left_text), _policy_definition(right_text)
    if left_policy or right_policy:
        # Preserve explicit grammatical contradiction without treating an
        # unsupported definition form as an ordinary compatible upper bound.
        if not left_policy or not right_policy:
            ln, rn = _numeric_constraint(left_text), _numeric_constraint(right_text)
            if (ln and rn and ln["unit"] and ln["unit"] == rn["unit"]
                    and _literal_numeric_scope(left_text, ln) == _literal_numeric_scope(right_text, rn)
                    and _intervals_conflict(ln, rn)):
                return _result(left_id, right_id, "conflict",
                    "The explicit bounds on the same literal attribute, unit, and condition have no overlapping value.",
                    ln["span"], rn["span"])
            known = left_policy or right_policy
            unknown_text = right_text if left_policy else left_text
            positive_text = re.sub(r"\b(shall|must)\s+not(?=\s+be\b)", r"\1", unknown_text, count=1, flags=re.I)
            opposite = _policy_definition(positive_text) if positive_text != unknown_text else None
            if opposite and opposite["key"] == known["key"] and opposite["value"] == known["value"]:
                return _result(left_id, right_id, "conflict",
                    "Explicit opposite grammatical negation of the same policy definition and value under the same literal scope.",
                    left_evidence, right_evidence)
        if not left_policy or not right_policy or left_policy["key"] != right_policy["key"]:
            return _result(left_id, right_id, "unassessed",
                "Policy definitions have unmatched actors, predicates, objects, units, conditions or definition forms; no equivalence is inferred.",
                left_evidence, right_evidence)
        disagrees = left_policy["value"] != right_policy["value"]
        result = _result(left_id, right_id, "conflict" if disagrees else "consistent",
            "Conflicting authoritative policy definitions require human resolution. Neither value is selected as correct; this is a policy disagreement, not a proof of disjoint count intervals."
            if disagrees else "The same explicit policy definition assigns equivalent numeric values.",
            left_evidence, right_evidence)
        result.update(comparison_kind="authoritative_policy_definition", human_resolution_required=disagrees)
        if disagrees:
            result["conflict_kind"] = "policy_definition_disagreement"
        return result

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
        "policy_version": POLICY_VERSION,
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
