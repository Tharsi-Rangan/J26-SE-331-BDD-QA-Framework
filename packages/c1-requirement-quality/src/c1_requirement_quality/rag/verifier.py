"""Conservative fact verification using local NLI and explicit constraints."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from c1_requirement_quality.rag.fact_extractor import Fact, extract_facts
from c1_requirement_quality.rag.model_loading import RAGModelLoadError


class VerificationOutcome(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class VerificationResult:
    outcome: VerificationOutcome
    evidence_ids: tuple[str, ...] = ()
    method: str = "symbolic"
    diagnostic: str | None = None
    component: str | None = None
    model_name: str | None = None


class LocalNLI:
    """Lazy local transformers NLI; loads cached weights only."""

    def __init__(self, model_name: str = "cross-encoder/nli-deberta-v3-small") -> None:
        self.model_name = model_name
        self._pipeline: Any | None = None

    @property
    def loaded_model_name(self) -> str | None:
        """Return the model ID only after the local NLI pipeline was loaded."""
        return self.model_name if self._pipeline is not None else None

    def _load(self) -> Any:
        if self._pipeline is None:
            try:
                from transformers import pipeline
            except ImportError as err:
                raise RAGModelLoadError("nli", self.model_name, err) from err
            try:
                self._pipeline = pipeline(
                    "text-classification", model=self.model_name, tokenizer=self.model_name,
                    local_files_only=True, device=-1,
                )
            except Exception as err:
                raise RAGModelLoadError("nli", self.model_name, err) from err
        return self._pipeline

    def classify(self, premise: str, hypothesis: str) -> str:
        result = self._load()(
            {"text": premise, "text_pair": hypothesis}, truncation=True
        )
        if not result:
            raise RuntimeError("NLI model returned no classification")
        prediction = result[0] if isinstance(result, list) else result
        if not isinstance(prediction, dict) or "label" not in prediction:
            raise RuntimeError("NLI model returned an unsupported classification format")
        return str(prediction["label"]).lower()


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\d+(?:\.\d+)?|[a-z]+(?:'[a-z]+)?", text.lower()))


def _content_signature(text: str) -> tuple[str, ...]:
    ignored = {"at", "least", "most", "less", "than", "greater", "more", "between", "up", "to", "minimum", "maximum", "of", "and", "not", "no", "never", "cannot", "can't", "mustn't", "won't"}
    return tuple(t for t in _tokens(text) if t not in ignored and not t[0].isdigit())


def _constraint_interval(constraint: Any) -> tuple[Decimal | None, bool, Decimal | None, bool] | None:
    """Convert a recognized comparison into lower/upper bounds and inclusivity."""
    values = tuple(Decimal(value) for value in constraint.values)
    operator = (constraint.operator or "").lower()
    if operator == "between" and len(values) == 2:
        return values[0], True, values[1], True
    if len(values) != 1:
        return None
    value = values[0]
    if operator in {"at least", "minimum of", ">=", "greater than or equal to"}:
        return value, True, None, False
    if operator in {"greater than", "more than", ">"}:
        return value, False, None, False
    if operator in {"at most", "maximum of", "up to", "<=", "less than or equal to"}:
        return None, False, value, True
    if operator in {"less than", "<"}:
        return None, False, value, False
    return None


def _intervals_disjoint(
    left: tuple[Decimal | None, bool, Decimal | None, bool],
    right: tuple[Decimal | None, bool, Decimal | None, bool],
) -> bool:
    left_lower, left_inc, left_upper, left_upper_inc = left
    right_lower, right_inc, right_upper, right_upper_inc = right
    if left_upper is not None and right_lower is not None:
        if left_upper < right_lower or (left_upper == right_lower and not (left_upper_inc and right_inc)):
            return True
    if right_upper is not None and left_lower is not None:
        if right_upper < left_lower or (right_upper == left_lower and not (right_upper_inc and left_inc)):
            return True
    return False


def _interval_subset(
    subset: tuple[Decimal | None, bool, Decimal | None, bool],
    superset: tuple[Decimal | None, bool, Decimal | None, bool],
) -> bool:
    sub_lower, sub_lower_inc, sub_upper, sub_upper_inc = subset
    super_lower, super_lower_inc, super_upper, super_upper_inc = superset
    if super_lower is not None:
        if sub_lower is None or sub_lower < super_lower:
            return False
        if sub_lower == super_lower and sub_lower_inc and not super_lower_inc:
            return False
    if super_upper is not None:
        if sub_upper is None or sub_upper > super_upper:
            return False
        if sub_upper == super_upper and sub_upper_inc and not super_upper_inc:
            return False
    return True


def verify_symbolically(fact: Fact, evidence: str, evidence_id: str) -> VerificationResult:
    """Use exact and tightly matched attribute checks; otherwise abstain."""
    if _tokens(fact.text) == _tokens(evidence):
        return VerificationResult(VerificationOutcome.SUPPORTED, (evidence_id,))
    # Opposite polarity is only actionable when the token content otherwise matches.
    negators = {"not", "no", "never", "cannot", "can't", "mustn't", "won't"}
    fneg = bool(set(_tokens(fact.text)) & negators)
    eneg = bool(set(_tokens(evidence)) & negators)
    if _content_signature(fact.text) == _content_signature(evidence) and fneg != eneg:
        return VerificationResult(VerificationOutcome.CONTRADICTED, (evidence_id,))

    # Numeric reasoning requires an unambiguous unit and matching property and
    # condition context. A differing threshold alone is never a contradiction.
    if fact.constraints:
        candidate_sig = _content_signature(fact.text)
        if candidate_sig and candidate_sig == _content_signature(evidence):
            evidence_facts = extract_facts(evidence, use_spacy=False)
            for candidate_constraint in fact.constraints:
                for source_fact in evidence_facts:
                    for source_constraint in source_fact.constraints:
                        same_unit = bool(candidate_constraint.unit) and (
                            candidate_constraint.unit.casefold() ==
                            (source_constraint.unit or "").casefold()
                        )
                        same_conditions = fact.conditions == source_fact.conditions
                        if not (same_unit and same_conditions and _content_signature(source_fact.text) == candidate_sig):
                            continue
                        target_range = _constraint_interval(candidate_constraint)
                        source_range = _constraint_interval(source_constraint)
                        if target_range is None or source_range is None:
                            continue
                        if _interval_subset(source_range, target_range):
                            return VerificationResult(VerificationOutcome.SUPPORTED, (evidence_id,), "symbolic_numeric")
                        if _intervals_disjoint(source_range, target_range):
                            return VerificationResult(VerificationOutcome.CONTRADICTED, (evidence_id,), "symbolic_numeric")
    return VerificationResult(VerificationOutcome.INCONCLUSIVE)


class FactVerifier:
    """Verify facts against candidate evidence, with injectable NLI classifier."""

    def __init__(self, nli: Any | None = None) -> None:
        self.nli = nli

    def verify(self, fact: Fact, evidence: list[Any]) -> VerificationResult:
        if not evidence:
            return VerificationResult(VerificationOutcome.INCONCLUSIVE, diagnostic="No evidence retrieved")
        seen: list[str] = []
        inconclusive: list[Any] = []
        for item in evidence:
            evidence_id = str(item.chunk_id)
            symbolic = verify_symbolically(fact, item.text, evidence_id)
            if symbolic.outcome is VerificationOutcome.SUPPORTED:
                return symbolic
            if symbolic.outcome is VerificationOutcome.CONTRADICTED:
                return symbolic
            seen.append(evidence_id)
            inconclusive.append(item)
        if self.nli is None:
            return VerificationResult(VerificationOutcome.INCONCLUSIVE, tuple(seen), diagnostic="No NLI classifier configured")
        try:
            outcomes: list[str] = [self.nli.classify(item.text, fact.text).lower() for item in inconclusive]
        except (ImportError, OSError, RuntimeError, ValueError, KeyError) as err:
            model_name = getattr(self.nli, "model_name", None)
            component = "nli"
            if isinstance(err, RAGModelLoadError):
                component = err.component
                model_name = err.model_name
            return VerificationResult(
                VerificationOutcome.ERROR, tuple(seen), "nli", str(err),
                component, model_name,
            )
        if any(label in {"entailment", "entails", "supported"} for label in outcomes):
            return VerificationResult(
                VerificationOutcome.SUPPORTED, tuple(seen), "nli",
                model_name=getattr(self.nli, "loaded_model_name", None),
            )
        if any(label in {"contradiction", "contradicts"} for label in outcomes):
            return VerificationResult(
                VerificationOutcome.CONTRADICTED, tuple(seen), "nli",
                model_name=getattr(self.nli, "loaded_model_name", None),
            )
        return VerificationResult(
            VerificationOutcome.INCONCLUSIVE, tuple(seen), "nli",
            model_name=getattr(self.nli, "loaded_model_name", None),
        )
