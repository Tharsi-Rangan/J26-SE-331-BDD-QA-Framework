"""Conservative fact verification using local NLI and explicit constraints."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any
import re

from c1_requirement_quality.rag.fact_extractor import Fact, extract_facts
from c1_requirement_quality.rag.model_loading import RAGModelLoadError
from c1_requirement_quality.model_paths import DEBERTA_NLI_MODEL_NAME, get_deberta_nli_cache_dir
from c1_requirement_quality.lexical_patterns import COMPARISON_TOKEN_PATTERN
from c1_requirement_quality.lexical_patterns import PLACEHOLDER_PATTERN


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
    evidence_outcomes: tuple[tuple[str, str], ...] = ()
    evidence_assessments: tuple[dict[str, Any], ...] = ()


class LocalNLI:
    """Lazy local transformers NLI; loads cached weights only."""

    def __init__(self, model_name: str = DEBERTA_NLI_MODEL_NAME) -> None:
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
                model_path = self.model_name
                if self.model_name == DEBERTA_NLI_MODEL_NAME:
                    directory = get_deberta_nli_cache_dir()
                    if directory is None:
                        raise FileNotFoundError("DeBERTa snapshot unavailable in configured local model/cache directories")
                    model_path = str(directory)
                self._pipeline = pipeline(
                    "text-classification", model=model_path, tokenizer=model_path,
                    local_files_only=True, device="cpu",
                )
            except Exception as err:
                raise RAGModelLoadError("nli", self.model_name, err) from err
        return self._pipeline

    def classify_with_diagnostics(self, premise: str, hypothesis: str) -> dict[str, Any]:
        result = self._load()(
            {"text": premise, "text_pair": hypothesis}, truncation=True
        )
        if not result:
            raise RuntimeError("NLI model returned no classification")
        prediction = result[0] if isinstance(result, list) else result
        if not isinstance(prediction, dict) or "label" not in prediction:
            raise RuntimeError("NLI model returned an unsupported classification format")
        return {
            "label": str(prediction["label"]).lower(),
            "score": float(prediction["score"]) if "score" in prediction else None,
        }

    def classify(self, premise: str, hypothesis: str) -> str:
        return self.classify_with_diagnostics(premise, hypothesis)["label"]


def _tokens(text: str) -> tuple[str, ...]:
    # Ignore only a structural numbered-list prefix, never factual numbers.
    text = re.sub(r"^\s*\d+[.)]\s+", "", text)
    return tuple(COMPARISON_TOKEN_PATTERN.findall(text.lower()))


def _incomplete(text: str) -> bool:
    return bool(PLACEHOLDER_PATTERN.search(text) or re.search(
        r"\bto be (?:determined|defined|decided)\b", text, re.I))


def evidence_applicability(fact: Fact, evidence: str) -> str:
    """A narrow same-obligation basis, not a similarity/relevance threshold.

    Preserve actor, predicate, object, units and condition wording. Only list
    prefixes, obligation modals and negation are normalized. Numeric values,
    comparisons and entity identifiers remain literal. Unknown paraphrases remain uncertain, never excluded as
    irrelevant or silently declared consistent.
    """
    def signature(text):
        return tuple(t for t in _tokens(text) if t not in {
            "shall", "must", "not", "no", "never", "cannot", "can't", "mustn't", "won't"})
    return "APPLICABLE" if signature(fact.text) and signature(fact.text) == signature(evidence) else "UNCERTAIN"


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
    if _incomplete(fact.text) or _incomplete(evidence):
        return VerificationResult(VerificationOutcome.INCONCLUSIVE, diagnostic="Unresolved placeholder or missing information")
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
        """Aggregate all retrieved passages without hiding conflicting evidence.

        Evidence IDs attribute support/contradiction only; per-passage outcomes
        also retain neutral/error results. Errors block success even when other
        passages support the claim. This covers retrieved evidence, not the
        completeness of retrieval across the source document.
        """
        if not evidence:
            return VerificationResult(VerificationOutcome.INCONCLUSIVE, diagnostic="No evidence retrieved")
        results: list[tuple[str, VerificationResult]] = []
        assessments: list[dict[str, Any]] = []
        uncertain_contradiction = False
        for item in evidence:
            evidence_id = str(item.chunk_id)
            symbolic = verify_symbolically(fact, item.text, evidence_id)
            result = symbolic
            applicability = "APPLICABLE" if symbolic.outcome in {VerificationOutcome.SUPPORTED, VerificationOutcome.CONTRADICTED} else evidence_applicability(fact, item.text)
            raw_label = None
            incomplete = _incomplete(fact.text) or _incomplete(item.text)
            if symbolic.outcome is VerificationOutcome.INCONCLUSIVE and self.nli is not None and not incomplete:
                try:
                    label = self.nli.classify(item.text, fact.text).lower()
                    raw_label = label
                    outcome = (
                        VerificationOutcome.SUPPORTED if label in {"entailment", "entails", "supported"}
                        else VerificationOutcome.CONTRADICTED if label in {"contradiction", "contradicts"}
                        else VerificationOutcome.INCONCLUSIVE
                    )
                    if applicability != "APPLICABLE":
                        uncertain_contradiction |= outcome is VerificationOutcome.CONTRADICTED
                        outcome = VerificationOutcome.INCONCLUSIVE
                    result = VerificationResult(outcome, (evidence_id,), "nli",
                        model_name=getattr(self.nli, "loaded_model_name", None))
                except (ImportError, OSError, RuntimeError, ValueError, KeyError) as err:
                    result = VerificationResult(VerificationOutcome.ERROR, (evidence_id,), "nli", str(err),
                        getattr(err, "component", "nli"),
                        getattr(err, "model_name", getattr(self.nli, "model_name", None)))
            results.append((evidence_id, result))
            assessments.append({"chunk_id": evidence_id, "applicability": "INCOMPLETE" if incomplete else applicability,
                "raw_nli_label": raw_label, "outcome": result.outcome.value,
                "reason": "Unresolved placeholder/missing information" if incomplete else
                    "Matching explicit obligation signature" if applicability == "APPLICABLE" else
                    "Applicability not established; raw NLI cannot establish factual support or contradiction"})

        # Inspect every retrieved passage. Errors prevent success; contradiction
        # takes precedence over support, regardless of retrieval order.
        states = {result.outcome for _, result in results}
        outcome = next(state for state in (
            VerificationOutcome.ERROR, VerificationOutcome.CONTRADICTED,
            VerificationOutcome.SUPPORTED, VerificationOutcome.INCONCLUSIVE,
        ) if state in states)
        if outcome is VerificationOutcome.SUPPORTED and uncertain_contradiction:
            outcome = VerificationOutcome.INCONCLUSIVE
        decisive = [result for _, result in results if result.outcome is outcome]
        attributed = tuple(dict.fromkeys(eid for eid, result in results
            if result.outcome in {VerificationOutcome.SUPPORTED, VerificationOutcome.CONTRADICTED}))
        methods = {result.method for result in decisive}
        diagnostics = [result.diagnostic for _, result in results if result.diagnostic]
        if uncertain_contradiction:
            diagnostics.append("NLI contradiction with uncertain evidence applicability requires review")
        if outcome is VerificationOutcome.INCONCLUSIVE and self.nli is None:
            diagnostics.append("No NLI classifier configured")
        return VerificationResult(
            outcome, attributed, next(iter(methods)) if len(methods) == 1 else "mixed",
            "; ".join(diagnostics) or None, decisive[0].component, decisive[0].model_name,
            tuple((eid, result.outcome.value) for eid, result in results),
            tuple(assessments),
        )
