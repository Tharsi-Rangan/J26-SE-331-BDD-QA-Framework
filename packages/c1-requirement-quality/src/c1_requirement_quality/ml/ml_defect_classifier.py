"""DistilBERT multi-label requirement defect classifier for Component 1.

Integrates the fine-tuned DistilBERT sequence classification checkpoint exported
from Experiment 2. Named experimental scores require the exact verified asset
hashes; existing rule-based detectors and CLI defaults remain unchanged.
"""

from __future__ import annotations

import math
import hashlib
import json
import struct
from numbers import Real
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Supported semantic vocabulary; this order is NOT checkpoint provenance.
DEFECT_LABELS: tuple[str, ...] = (
    "VAGUE",
    "AMBIGUOUS",
    "INCOMPLETE",
    "NON_MEASURABLE",
    "NON_VERIFIABLE",
)

# Legacy vocabulary enumeration only; never use as checkpoint label provenance.
LABEL_INDEX_MAP: dict[int, str] = {
    index: label for index, label in enumerate(DEFECT_LABELS)
}

CONTRACT_LABEL_MAP: dict[str, str] = {
    "VAGUE": "vague",
    "AMBIGUOUS": "ambiguous",
    "INCOMPLETE": "incomplete",
    "NON_MEASURABLE": "non_measurable",
    "NON_VERIFIABLE": "non_verifiable",
}

from c1_requirement_quality.model_paths import get_distilbert_model_dir

DEFAULT_MODEL_DIR = get_distilbert_model_dir()


# Verified against the original Experiment 2 ZIP and notebook cells 139, 152,
# 161 and 169-171. Training annotations were provisional AI-assisted records.
# Identity establishes output semantics, never accuracy or calibration.
EXPERIMENT2_LABELS = DEFECT_LABELS
TRAINING_MAX_LENGTH = 128
EXPERIMENT2_FILES = {
    "model.safetensors": "122ce30b7321b271c279b63efd5501be81ee6e1f4f2282496ef1be459a9685cd",
    "config.json": "ce29b7bad10a51071c43ea2dd7885315b48bc2b258d99f0c0c8bde1d5e6032a5",
    "tokenizer.json": "da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0",
    "tokenizer_config.json": "e1c2a61a99bda00f6c55303a210b30e2f92dcf8b555e215812e2eb583e177ffd",
}
EXPERIMENT2_PROVENANCE = (
    "Colab Experiment 2; Untitled1.ipynb SHA256 "
    "131bdd5591ad39026b0b4dfd762bb5822c5573491fd03cefa2424da885b16b8e; "
    "label tensor: cell 161; export: cells 169-171; 36 provisional AI-assisted records"
)


class DistilBertModelLoadError(RuntimeError):
    """Raised when the DistilBERT checkpoint or dependencies cannot be loaded."""

    def __init__(self, model_path: Path | str, cause: BaseException | str) -> None:
        self.model_path = str(model_path)
        self.cause = cause
        super().__init__(
            f"DistilBERT defect classification model could not be loaded from "
            f"'{self.model_path}': {cause}. Ensure checkpoint files ('config.json', "
            f"'model.safetensors', 'tokenizer.json') exist locally and transformers "
            f"and torch dependencies are installed."
        )


@dataclass(frozen=True)
class DefectScore:
    """Individual score and classification status for a defect category."""

    label: str
    contract_type: str | None
    score: float
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClassificationResult:
    """Multi-label classification output for a single requirement."""

    requirement_id: str | None
    text: str
    scores: dict[str, float]
    labels: list[DefectScore]
    predicted_defects: list[str]
    status: str
    threshold_applied: float | None
    model_name: str
    mapping_status: str = "UNVERIFIED"
    mapping_provenance: str | None = None
    input_tokens: int | None = None
    truncated: bool | None = None
    token_limit: int = TRAINING_MAX_LENGTH
    checkpoint_sha256: str | None = None
    human_review_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "text": self.text,
            "status": self.status,
            "model_name": self.model_name,
            "threshold_applied": self.threshold_applied,
            "mapping_status": self.mapping_status,
            "mapping_provenance": self.mapping_provenance,
            "input_tokens": self.input_tokens,
            "truncated": self.truncated,
            "token_limit": self.token_limit,
            "checkpoint_sha256": self.checkpoint_sha256,
            "human_review_required": self.human_review_required,
            "scores": dict(self.scores),
            "labels": [label.to_dict() for label in self.labels],
            "predicted_defects": list(self.predicted_defects),
        }


def _validate_threshold(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("threshold must be a real number or None")
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("threshold must be finite and between 0 and 1")
    return value


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid function."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


class DistilBertDefectClassifier:
    """Inference engine for the fine-tuned DistilBERT requirement defect classifier."""

    def __init__(
        self,
        model_dir: Path | str | None = None,
        *,
        tokenizer: Any | None = None,
        model: Any | None = None,
        threshold: float | None = None,
        model_name: str = "distilbert-requirement-defects",
        semantic_labels: Sequence[str] | None = None,
        mapping_provenance: str | None = None,
    ) -> None:
        self.model_dir = Path(model_dir) if model_dir is not None else DEFAULT_MODEL_DIR
        self.tokenizer = tokenizer
        self.model = model
        self.threshold = _validate_threshold(threshold)
        if (tokenizer is None) != (model is None):
            raise ValueError("tokenizer and model must be supplied together")
        if semantic_labels is None:
            if mapping_provenance is not None:
                raise ValueError("mapping provenance requires semantic_labels")
            self.semantic_labels = None
        else:
            labels = tuple(semantic_labels)
            if len(labels) != 5 or set(labels) != set(DEFECT_LABELS):
                raise ValueError("semantic_labels must contain each of the five defect names exactly once")
            if not isinstance(mapping_provenance, str) or not mapping_provenance.strip():
                raise ValueError("semantic label mapping requires verified training provenance")
            if labels != EXPERIMENT2_LABELS:
                raise ValueError("semantic label order disagrees with verified Experiment 2 mapping")
            self.semantic_labels = None
        self._requested_labels = semantic_labels is not None
        self.mapping_provenance = None
        self._identity_verified = False
        self._injected = tokenizer is not None
        self._input_tokens: int | None = None
        self._truncated: bool | None = None
        self.model_name = model_name
        self._loaded = tokenizer is not None and model is not None
        self._loaded_asset_state = None
        self._loaded_report = None

    def _asset_state(self):
        """Cheap change detection; full hashes still bind initial/final batch checks.

        Changed identity, size, mtime or ctime forces revalidation. Explicit
        validate_checkpoint() always hashes all assets, including at batch end.
        """
        try:
            return tuple((name, stat.st_dev, stat.st_ino, stat.st_size,
                          stat.st_mtime_ns, stat.st_ctime_ns)
                         for name in EXPERIMENT2_FILES
                         for stat in [(self.model_dir / name).stat()])
        except OSError as err:
            # Preserve the checkpoint validator's actionable missing-asset diagnostics.
            self.validate_checkpoint()
            raise DistilBertModelLoadError(self.model_dir, err) from err

    def validate_checkpoint(self) -> dict[str, Any]:
        """Inspect local config/tensor metadata without loading weights or inferring label meaning.

        Named labels are enabled only for the known weights, configuration and
        tokenizer hashes. Caller-supplied labels/provenance cannot establish trust.
        Unknown checkpoints remain index-only unless named labels were requested,
        in which case validation fails. No model inference occurs here.
        """
        try:
            if not self.model_dir.is_dir():
                raise ValueError("directory does not exist or is not a directory")
            for name in ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json"):
                if not (self.model_dir / name).is_file():
                    raise ValueError(f"missing required checkpoint file: {name}")
            config = json.loads((self.model_dir / "config.json").read_text(encoding="utf-8"))
            if (config.get("model_type") != "distilbert"
                    or config.get("architectures") != ["DistilBertForSequenceClassification"]
                    or config.get("problem_type") != "multi_label_classification"):
                raise ValueError("unsupported checkpoint architecture or problem type")
            ids = config.get("id2label", {})
            if (set(ids) != {str(i) for i in range(5)}
                    or len(set(ids.values())) != 5
                    or config.get("label2id") != {name: int(i) for i, name in ids.items()}
                    or config.get("num_labels", 5) != 5):
                raise ValueError("checkpoint must configure exactly five consistent labels")
            if self.semantic_labels is not None:
                names = tuple(ids[str(i)] for i in range(5))
                if names != tuple(f"LABEL_{i}" for i in range(5)) and names != self.semantic_labels:
                    raise ValueError("checkpoint names disagree with supplied semantic label order")
            with (self.model_dir / "model.safetensors").open("rb") as stream:
                size = struct.unpack("<Q", stream.read(8))[0]
                if not 0 < size <= 16 * 1024 * 1024:
                    raise ValueError("invalid safetensors header size")
                header = json.loads(stream.read(size))
            width = config.get("dim")
            if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
                raise ValueError("invalid classifier hidden dimension")
            for name, shape in (("classifier.weight", [5, width]), ("classifier.bias", [5])):
                tensor = header.get(name, {})
                if tensor.get("shape") != shape or tensor.get("dtype") not in {"F32", "F16", "BF16"}:
                    raise ValueError("invalid classifier output dimension or dtype")
            digests = {}
            for name in EXPERIMENT2_FILES:
                with (self.model_dir / name).open("rb") as stream:
                    digests[name] = hashlib.file_digest(stream, "sha256").hexdigest()
            verified = digests == EXPERIMENT2_FILES
            if not verified and (self._requested_labels or self._identity_verified):
                raise ValueError("checkpoint identity mismatch: named labels require exact Experiment 2 assets")
            return {"architecture": config["architectures"][0], "output_dimension": 5,
                    "configured_labels": ids, "checkpoint_sha256": digests["model.safetensors"],
                    "mapping_status": "VERIFIED" if verified else "UNVERIFIED",
                    "mapping_provenance": EXPERIMENT2_PROVENANCE if verified else None}
        except (OSError, ValueError, TypeError, KeyError, struct.error) as err:
            raise DistilBertModelLoadError(self.model_dir, err) from err

    def _ensure_loaded(self) -> None:
        """Load tokenizer and model lazily from local checkpoint if not injected."""
        if self._injected:
            # An arbitrary injected model cannot inherit the on-disk checkpoint identity.
            return
        asset_state = self._asset_state()
        if self._loaded and asset_state == self._loaded_asset_state:
            return
        report = self.validate_checkpoint()
        if self._loaded:
            if report != self._loaded_report:
                raise DistilBertModelLoadError(self.model_dir, "checkpoint changed after model loading; create a fresh classifier")
            self._loaded_asset_state = asset_state
            return
        verified = report["mapping_status"] == "VERIFIED"
        self._identity_verified = verified
        self.semantic_labels = EXPERIMENT2_LABELS if verified else None
        self.mapping_provenance = report["mapping_provenance"]

        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as err:
            raise DistilBertModelLoadError(
                self.model_dir,
                f"missing required dependencies: {err}. Install transformers and torch.",
            ) from err

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                str(self.model_dir), local_files_only=True
            )
            self.model = AutoModelForSequenceClassification.from_pretrained(
                str(self.model_dir), local_files_only=True
            )
            if hasattr(self.model, "eval"):
                self.model.eval()
            # Detect asset changes during loading before releasing named results.
            loaded_report = self.validate_checkpoint()
            if loaded_report != report:
                raise ValueError("checkpoint changed while loading")
            self._loaded = True
            self._loaded_report = loaded_report
            self._loaded_asset_state = asset_state
        except Exception as err:
            raise DistilBertModelLoadError(self.model_dir, err) from err

    def predict_scores(self, text: str) -> dict[str, float]:
        """Compute sigmoid probability scores for each of the five defect categories."""
        if not isinstance(text, str):
            raise TypeError("Requirement text must be a string")
        if not text.strip():
            raise ValueError("Requirement text must not be empty")

        self._ensure_loaded()

        try:
            import torch
        except ImportError as err:
            raise DistilBertModelLoadError(
                self.model_dir, f"torch dependency not available: {err}"
            ) from err

        self._input_tokens = None
        self._truncated = None
        encode = getattr(self.tokenizer, "encode", None)
        if callable(encode):
            try:
                token_ids = encode(text, add_special_tokens=True, truncation=False)
            except (NotImplementedError, TypeError):
                # Some injected/custom tokenizers support calls but not token counting.
                token_ids = None
            if isinstance(token_ids, list) and all(isinstance(i, int) for i in token_ids):
                self._input_tokens = len(token_ids)
                self._truncated = len(token_ids) > TRAINING_MAX_LENGTH

        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=TRAINING_MAX_LENGTH,
        )

        with torch.no_grad():
            outputs = self.model(**inputs)
            logits = outputs.logits

        rows = logits.tolist() if hasattr(logits, "tolist") else logits
        if (not isinstance(rows, (list, tuple)) or len(rows) != 1
                or not isinstance(rows[0], (list, tuple)) or len(rows[0]) != 5):
            raise RuntimeError("Model output dimension mismatch: expected shape [1, 5]")
        scores: dict[str, float] = {}
        names = self.semantic_labels or tuple(f"INDEX_{i}" for i in range(5))
        for name, value in zip(names, rows[0], strict=True):
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise RuntimeError("Model logits must be finite real numbers")
            probability = _sigmoid(float(value))
            if not math.isfinite(probability):
                raise RuntimeError("Model prediction score must be finite")
            scores[name] = probability

        return scores

    def classify(
        self,
        text: str,
        *,
        requirement_id: str | None = None,
        threshold: float | None = None,
    ) -> ClassificationResult:
        """Classify a requirement and return structured multi-label results.

        If no threshold is configured, predictions are marked as 'requires_review'
        (experimental) rather than claiming validated multi-label classifications.
        """
        effective_threshold = _validate_threshold(threshold if threshold is not None else self.threshold)
        scores = self.predict_scores(text)

        labels: list[DefectScore] = []
        predicted_defects: list[str] = []

        # A numeric cutoff is not evidence of calibration or research validity.
        overall_status = "experimental"
        for label, score in scores.items():
            contract_type = CONTRACT_LABEL_MAP[label] if self.semantic_labels else None
            if self.semantic_labels is None or effective_threshold is None:
                label_status = "requires_review"
            elif score >= effective_threshold:
                label_status = "predicted"
                predicted_defects.append(label)
            else:
                label_status = "not_predicted"

            labels.append(
                DefectScore(
                    label=label,
                    contract_type=contract_type,
                    score=score,
                    status=label_status,
                )
            )

        return ClassificationResult(
            requirement_id=requirement_id,
            text=text,
            scores=scores,
            labels=labels,
            predicted_defects=predicted_defects,
            status=overall_status,
            threshold_applied=effective_threshold,
            model_name=self.model_name,
            mapping_status="VERIFIED" if self.semantic_labels else "UNVERIFIED",
            mapping_provenance=self.mapping_provenance,
            input_tokens=self._input_tokens,
            truncated=self._truncated,
            checkpoint_sha256=EXPERIMENT2_FILES["model.safetensors"] if self._identity_verified else None,
        )

    def classify_batch(
        self,
        requirements: Sequence[dict[str, Any] | str],
        *,
        threshold: float | None = None,
    ) -> list[ClassificationResult]:
        """Classify a collection of requirements."""
        _validate_threshold(threshold if threshold is not None else self.threshold)
        results: list[ClassificationResult] = []
        for item in requirements:
            if isinstance(item, str):
                results.append(self.classify(item, threshold=threshold))
            elif isinstance(item, dict):
                req_id = item.get("requirement_id")
                req_text = item.get("text") or item.get("original_text")
                if not isinstance(req_text, str):
                    raise ValueError(
                        f"Requirement dictionary missing text/original_text string: {item}"
                    )
                results.append(
                    self.classify(req_text, requirement_id=req_id, threshold=threshold)
                )
            else:
                raise TypeError(f"Invalid requirement item type: {type(item).__name__}")
        return results

    def format_contract_defects(
        self,
        result: ClassificationResult,
        *,
        threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Format verified named outputs without claiming localized span evidence.

        The result's recorded threshold is authoritative. Reclassification is
        required to change it; formatting cannot silently apply another cutoff.
        """
        effective_threshold = _validate_threshold(result.threshold_applied)
        if threshold is not None and _validate_threshold(threshold) != effective_threshold:
            raise ValueError("format threshold must match classification threshold")
        if (result.mapping_status != "VERIFIED" or not self._identity_verified
                or self.semantic_labels != EXPERIMENT2_LABELS
                or result.mapping_provenance != self.mapping_provenance
                or result.checkpoint_sha256 != EXPERIMENT2_FILES["model.safetensors"]):
            return []
        if effective_threshold is None:
            return []
        if tuple(result.scores) != self.semantic_labels:
            raise ValueError("result semantic labels do not match classifier")
        defects: list[dict[str, Any]] = []
        for label, score in result.scores.items():
            if (isinstance(score, bool) or not isinstance(score, Real)
                    or not math.isfinite(score) or not 0 <= score <= 1):
                raise ValueError("result scores must be finite probabilities")
            if score >= effective_threshold:
                defects.append({
                    "type": CONTRACT_LABEL_MAP[label], "detector": "ml",
                    "explanation": (
                        f"Experimental sentence-level prediction '{label}' with model score "
                        f"{score:.4f} (threshold: {effective_threshold}); "
                        "cutoff is not calibrated and localized evidence is unavailable."
                    ),
                    "confidence": score,
                })
        return defects
