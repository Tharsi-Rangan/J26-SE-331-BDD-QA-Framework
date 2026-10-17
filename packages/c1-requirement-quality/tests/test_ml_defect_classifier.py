"""Unit tests for the DistilBERT requirement defect classifier."""

from __future__ import annotations

import pytest
import json
import struct
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

from c1_requirement_quality.ml_defect_classifier import (
    DEFECT_LABELS,
    LABEL_INDEX_MAP,
    CONTRACT_LABEL_MAP,
    DistilBertDefectClassifier,
    DistilBertModelLoadError,
    ClassificationResult,
    EXPERIMENT2_FILES, EXPERIMENT2_LABELS, EXPERIMENT2_PROVENANCE, TRAINING_MAX_LENGTH,
)


def _create_mock_classifier(logits_list: list[float], threshold: float | None = None, *, verified=True) -> DistilBertDefectClassifier:
    """Helper creating a classifier with a mocked tokenizer and model returning specified logits."""
    mock_tokenizer = MagicMock()
    mock_tokenizer.return_value = {"input_ids": [101, 102], "attention_mask": [1, 1]}

    mock_outputs = MagicMock()
    mock_outputs.logits = [logits_list]

    mock_model = MagicMock()
    mock_model.return_value = mock_outputs

    classifier = DistilBertDefectClassifier(
        tokenizer=mock_tokenizer,
        model=mock_model,
        threshold=threshold,
        semantic_labels=DEFECT_LABELS if verified else None,
        mapping_provenance="Synthetic unit-test label order; not actual checkpoint evidence" if verified else None,
    )
    if verified:
        # Simulate an authenticated load for numerical unit tests only.
        # Production injection never grants checkpoint provenance.
        classifier.semantic_labels = EXPERIMENT2_LABELS
        classifier.mapping_provenance = EXPERIMENT2_PROVENANCE
        classifier._identity_verified = True
    return classifier


def test_supported_label_vocabulary_is_not_checkpoint_provenance():
    """Vocabulary constants do not authenticate a training label order."""
    assert DEFECT_LABELS == (
        "VAGUE",
        "AMBIGUOUS",
        "INCOMPLETE",
        "NON_MEASURABLE",
        "NON_VERIFIABLE",
    )
    assert LABEL_INDEX_MAP[0] == "VAGUE"
    assert LABEL_INDEX_MAP[1] == "AMBIGUOUS"
    assert LABEL_INDEX_MAP[2] == "INCOMPLETE"
    assert LABEL_INDEX_MAP[3] == "NON_MEASURABLE"
    assert LABEL_INDEX_MAP[4] == "NON_VERIFIABLE"

    # Verify no generic LABEL_0 is present
    for label in DEFECT_LABELS:
        assert not label.startswith("LABEL_")


def test_contract_label_mapping():
    """Verify mapping from uppercase model labels to contract enum values."""
    assert CONTRACT_LABEL_MAP["VAGUE"] == "vague"
    assert CONTRACT_LABEL_MAP["AMBIGUOUS"] == "ambiguous"
    assert CONTRACT_LABEL_MAP["INCOMPLETE"] == "incomplete"
    assert CONTRACT_LABEL_MAP["NON_MEASURABLE"] == "non_measurable"
    assert CONTRACT_LABEL_MAP["NON_VERIFIABLE"] == "non_verifiable"


def test_predict_scores_returns_five_scores_per_requirement():
    """Verify that every prediction returns exactly 5 scores corresponding to the 5 defect labels."""
    # Logits: [0.0, 2.0, -2.0, 1.0, -1.0]
    # Sigmoid(0) = 0.5, Sigmoid(2) â‰ˆ 0.8808, Sigmoid(-2) â‰ˆ 0.1192, Sigmoid(1) â‰ˆ 0.7311, Sigmoid(-1) â‰ˆ 0.2689
    classifier = _create_mock_classifier([0.0, 2.0, -2.0, 1.0, -1.0])
    scores = classifier.predict_scores("The system shall process requests promptly.")

    assert len(scores) == 5
    assert set(scores.keys()) == set(DEFECT_LABELS)
    assert scores["VAGUE"] == 0.5
    assert scores["AMBIGUOUS"] == pytest.approx(0.8807970779)
    assert scores["INCOMPLETE"] == pytest.approx(0.1192029220)
    assert scores["NON_MEASURABLE"] == pytest.approx(0.7310585786)
    assert scores["NON_VERIFIABLE"] == pytest.approx(0.2689414214)


def test_multi_label_prediction_with_configured_threshold():
    """Verify that multi-label output is supported when configured with a threshold."""
    # VAGUE (0.0 -> 0.5), AMBIGUOUS (2.0 -> 0.8808), INCOMPLETE (-2.0 -> 0.1192),
    # NON_MEASURABLE (1.5 -> 0.8176), NON_VERIFIABLE (-1.0 -> 0.2689)
    classifier = _create_mock_classifier([0.0, 2.0, -2.0, 1.5, -1.0])

    result = classifier.classify(
        "The system may respond quickly as needed.",
        requirement_id="REQ-TEST-001",
        threshold=0.6,
    )

    assert isinstance(result, ClassificationResult)
    assert result.requirement_id == "REQ-TEST-001"
    assert result.status == "experimental"
    assert result.threshold_applied == 0.6

    # Multiple defects should be flagged (AMBIGUOUS and NON_MEASURABLE > 0.6)
    assert result.predicted_defects == ["AMBIGUOUS", "NON_MEASURABLE"]

    labels_by_name = {l.label: l for l in result.labels}
    assert labels_by_name["AMBIGUOUS"].status == "predicted"
    assert labels_by_name["NON_MEASURABLE"].status == "predicted"
    assert labels_by_name["VAGUE"].status == "not_predicted"
    assert labels_by_name["INCOMPLETE"].status == "not_predicted"
    assert labels_by_name["NON_VERIFIABLE"].status == "not_predicted"


def test_default_policy_without_threshold_marks_experimental():
    """Verify that predictions without validated threshold are marked experimental / requires_review."""
    classifier = _create_mock_classifier([0.5, 0.8, -0.2, 0.3, 0.1], threshold=None)
    result = classifier.classify("The system shall be user-friendly.")

    assert result.status == "experimental"
    assert result.threshold_applied is None
    assert result.predicted_defects == []

    # All individual labels must indicate requires_review
    for item in result.labels:
        assert item.status == "requires_review"
        assert 0.0 <= item.score <= 1.0


def test_empty_or_invalid_input_handling():
    """Verify that empty strings or invalid types fail clearly."""
    classifier = _create_mock_classifier([0.0, 0.0, 0.0, 0.0, 0.0])

    with pytest.raises(ValueError, match="Requirement text must not be empty"):
        classifier.classify("")

    with pytest.raises(ValueError, match="Requirement text must not be empty"):
        classifier.classify("   \n\t  ")

    with pytest.raises(TypeError, match="Requirement text must be a string"):
        classifier.classify(None)  # type: ignore

    with pytest.raises(TypeError, match="Requirement text must be a string"):
        classifier.classify(12345)  # type: ignore


def test_missing_checkpoint_directory_raises_clear_error(tmp_path):
    """Verify that non-existent checkpoint path raises DistilBertModelLoadError."""
    nonexistent = tmp_path / "does_not_exist"
    classifier = DistilBertDefectClassifier(model_dir=nonexistent)

    with pytest.raises(DistilBertModelLoadError) as exc_info:
        classifier.classify("The system shall do X.")

    assert "does not exist or is not a directory" in str(exc_info.value)
    assert str(nonexistent) in str(exc_info.value)


def test_missing_model_files_raises_clear_error(tmp_path):
    """Verify that missing model.safetensors or config.json raises DistilBertModelLoadError."""
    incomplete_dir = tmp_path / "incomplete_model"
    incomplete_dir.mkdir()
    (incomplete_dir / "config.json").write_text("{}", encoding="utf-8")
    # model.safetensors is missing!

    classifier = DistilBertDefectClassifier(model_dir=incomplete_dir)

    with pytest.raises(DistilBertModelLoadError) as exc_info:
        classifier.classify("The system shall do X.")

    assert "missing required checkpoint file: model.safetensors" in str(exc_info.value)


def test_batch_classification():
    """Verify batch classification across multiple requirement items."""
    classifier = _create_mock_classifier([0.1, 0.2, 0.3, 0.4, 0.5])
    items = [
        {"requirement_id": "REQ-01", "original_text": "The system shall log in."},
        {"requirement_id": "REQ-02", "text": "The system shall log out."},
        "The system shall display reports.",
    ]

    results = classifier.classify_batch(items)
    assert len(results) == 3
    assert results[0].requirement_id == "REQ-01"
    assert results[1].requirement_id == "REQ-02"
    assert results[2].requirement_id is None


def test_format_contract_defects():
    """Verify formatting of predictions into contract defect objects."""
    classifier = _create_mock_classifier([0.1, 2.0, -1.0, 1.8, -2.0], threshold=0.7)
    result = classifier.classify("The system might respond fast.", threshold=0.7)

    defects = classifier.format_contract_defects(result)
    assert len(defects) == 2

    types = [d["type"] for d in defects]
    assert "ambiguous" in types
    assert "non_measurable" in types

    for d in defects:
        assert d["detector"] == "ml"
        assert "evidence_span" not in d
        assert "confidence" in d
        assert d["confidence"] >= 0.7


def test_real_local_checkpoint_if_available():
    """Test inference with real local checkpoint files if they exist on disk."""
    default_dir = Path("packages/c1-requirement-quality/models/distilbert-requirement-defects")
    if not (default_dir / "model.safetensors").is_file():
        pytest.skip("Local model.safetensors not present in test environment")

    classifier = DistilBertDefectClassifier(model_dir=default_dir)
    result = classifier.classify(
        "The system shall provide a suitable user interface.",
        requirement_id="REQ-REAL-001",
    )

    assert result.requirement_id == "REQ-REAL-001"
    assert len(result.scores) == 5
    assert tuple(result.scores) == EXPERIMENT2_LABELS
    assert all(0 <= score <= 1 for score in result.scores.values())
    assert result.mapping_status == "VERIFIED"
    assert result.checkpoint_sha256 == EXPERIMENT2_FILES["model.safetensors"]
    assert result.token_limit == 128 and result.human_review_required
    assert result.predicted_defects == []
    assert classifier.format_contract_defects(result) == []
    assert result.truncated is False
    assert result.status == "experimental"
    print("REAL OFFLINE CHECKPOINT:", result.to_dict())
    long_result = classifier.classify("The system shall log events. " * 30, threshold=0.9)
    assert long_result.input_tokens > 128 and long_result.truncated is True
    assert long_result.token_limit == 128 and len(long_result.scores) == 5
    assert long_result.mapping_status == "VERIFIED"
    assert long_result.status == "experimental" and long_result.human_review_required
    print("REAL LONG INPUT:", {"input_tokens": long_result.input_tokens,
          "token_limit": long_result.token_limit, "truncated": long_result.truncated,
          "status": long_result.status})


@pytest.mark.parametrize("value", [True, False, "0.5", [], {}, complex(0.5)])
def test_non_numeric_thresholds_rejected(value):
    with pytest.raises(TypeError):
        _create_mock_classifier([0.0] * 5, threshold=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -0.1, 1.1])
def test_invalid_thresholds_rejected_at_all_entry_points(value):
    with pytest.raises(ValueError):
        _create_mock_classifier([0.0] * 5, threshold=value)
    classifier = _create_mock_classifier([0.0] * 5)
    with pytest.raises(ValueError):
        classifier.classify("The system shall log events.", threshold=value)
    with pytest.raises(ValueError):
        classifier.classify_batch([], threshold=value)
    result = classifier.classify("The system shall log events.")
    with pytest.raises(ValueError):
        classifier.format_contract_defects(result, threshold=value)


@pytest.mark.parametrize("threshold,expected", [(0.0, 5), (0.5, 5), (1.0, 0)])
def test_threshold_boundaries_and_formatting_use_result_cutoff(threshold, expected):
    classifier = _create_mock_classifier([0.0] * 5)
    result = classifier.classify("The system shall log events.", threshold=threshold)
    assert len(result.predicted_defects) == expected
    classifier.threshold = 0.99
    assert len(classifier.format_contract_defects(result)) == expected
    assert len(classifier.format_contract_defects(result, threshold=threshold)) == expected
    assert result.status == "experimental"


def test_formatting_cannot_change_classification_cutoff():
    classifier = _create_mock_classifier([0.0] * 5)
    result = classifier.classify("The system shall log events.", threshold=0.5)
    with pytest.raises(ValueError, match="must match"):
        classifier.format_contract_defects(result, threshold=0.7)
    assert classifier.format_contract_defects(classifier.classify("The system shall log events.")) == []


@pytest.mark.parametrize("values", [[float("nan")] * 5, [float("inf")] * 5,
                                    [-float("inf")] * 5, [True] * 5, ["0"] * 5])
def test_nonfinite_or_invalid_logits_rejected(values):
    with pytest.raises(RuntimeError, match="finite real"):
        _create_mock_classifier(values).classify("The system shall log events.")


@pytest.mark.parametrize("rows", [[], [0.0] * 5, [[0.0] * 4], [[0.0] * 6],
                                  [[0.0] * 5, [0.0] * 5], [[[0.0] * 5]]])
def test_wrong_output_shapes_rejected(rows):
    classifier = _create_mock_classifier([0.0] * 5)
    classifier.model.return_value.logits = rows
    with pytest.raises(RuntimeError):
        classifier.predict_scores("The system shall log events.")


def test_unverified_mapping_exposes_only_index_diagnostics():
    classifier = _create_mock_classifier([2.0] * 5, threshold=0.1, verified=False)
    result = classifier.classify("The system shall log events.")
    assert result.mapping_status == "UNVERIFIED"
    assert set(result.scores) == {f"INDEX_{i}" for i in range(5)}
    assert result.predicted_defects == []
    assert all(label.contract_type is None and label.status == "requires_review" for label in result.labels)
    assert classifier.format_contract_defects(result) == []
    assert not any(name in json.dumps(result.to_dict()) for name in DEFECT_LABELS)


def test_named_mapping_requires_explicit_training_provenance():
    with pytest.raises(ValueError, match="provenance"):
        DistilBertDefectClassifier(semantic_labels=DEFECT_LABELS)
    with pytest.raises(ValueError):
        DistilBertDefectClassifier(semantic_labels=["LABEL_0"] * 5, mapping_provenance="fixture")
    with pytest.raises(ValueError):
        DistilBertDefectClassifier(mapping_provenance="fixture")
    with pytest.raises(ValueError):
        DistilBertDefectClassifier(tokenizer=MagicMock())


def test_explicit_mapping_cannot_override_authenticated_order():
    with pytest.raises(ValueError, match="order disagrees"):
        DistilBertDefectClassifier(semantic_labels=tuple(reversed(DEFECT_LABELS)),
                                 mapping_provenance="caller assertion")


@pytest.mark.parametrize("count,truncated", [(127, False), (128, False), (129, True)])
def test_truncation_reported_without_sending_metadata_to_model(count, truncated):
    classifier = _create_mock_classifier([0.0] * 5)
    classifier.tokenizer.encode.return_value = [1] * count
    result = classifier.classify("The system shall log events.")
    assert result.input_tokens == count and result.truncated is truncated
    assert result.to_dict()["truncated"] is truncated
    assert classifier.model.call_args.kwargs == {"input_ids": [101, 102], "attention_mask": [1, 1]}


def test_unsupported_token_count_is_explicitly_unknown():
    classifier = _create_mock_classifier([0.0] * 5)
    classifier.tokenizer.encode = None
    result = classifier.classify("The system shall log events.")
    assert result.input_tokens is None and result.truncated is None


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1])
def test_formatting_rejects_corrupted_scores(score):
    classifier = _create_mock_classifier([0.0] * 5, threshold=0.5)
    result = classifier.classify("The system shall log events.")
    with pytest.raises(ValueError):
        classifier.format_contract_defects(replace(result, scores={**result.scores, "VAGUE": score}))


def _checkpoint(tmp_path):
    config = {"model_type": "distilbert", "architectures": ["DistilBertForSequenceClassification"],
              "problem_type": "multi_label_classification", "dim": 768,
              "id2label": {str(i): f"LABEL_{i}" for i in range(5)},
              "label2id": {f"LABEL_{i}": i for i in range(5)}}
    (tmp_path / "config.json").write_text(json.dumps(config))
    (tmp_path / "tokenizer.json").write_text("{}")
    (tmp_path / "tokenizer_config.json").write_text("{}")
    header = {"classifier.weight": {"dtype": "F32", "shape": [5, 768]},
              "classifier.bias": {"dtype": "F32", "shape": [5]}}
    encoded = json.dumps(header).encode()
    (tmp_path / "model.safetensors").write_bytes(struct.pack("<Q", len(encoded)) + encoded)
    return config, header


def test_checkpoint_metadata_validation_does_not_load_model(tmp_path):
    _checkpoint(tmp_path)
    report = DistilBertDefectClassifier(model_dir=tmp_path).validate_checkpoint()
    assert report["architecture"] == "DistilBertForSequenceClassification"
    assert report["output_dimension"] == 5 and report["mapping_status"] == "UNVERIFIED"


@pytest.mark.parametrize("field,value", [("model_type", "bert"), ("architectures", ["DistilBertModel"]),
                                         ("problem_type", "single_label_classification"),
                                         ("id2label", {"0": "LABEL_0"}), ("label2id", {}),
                                         ("num_labels", 4), ("dim", 100)])
def test_invalid_checkpoint_configuration_rejected(tmp_path, field, value):
    config, _ = _checkpoint(tmp_path)
    config[field] = value
    (tmp_path / "config.json").write_text(json.dumps(config))
    with pytest.raises(DistilBertModelLoadError):
        DistilBertDefectClassifier(model_dir=tmp_path).validate_checkpoint()


@pytest.mark.parametrize("name", ["tokenizer.json", "tokenizer_config.json"])
def test_missing_tokenizer_assets_rejected(tmp_path, name):
    _checkpoint(tmp_path)
    (tmp_path / name).unlink()
    with pytest.raises(DistilBertModelLoadError, match="missing required"):
        DistilBertDefectClassifier(model_dir=tmp_path).validate_checkpoint()


def test_wrong_checkpoint_head_dimension_rejected(tmp_path):
    _, header = _checkpoint(tmp_path)
    header["classifier.weight"]["shape"] = [4, 768]
    encoded = json.dumps(header).encode()
    (tmp_path / "model.safetensors").write_bytes(struct.pack("<Q", len(encoded)) + encoded)
    with pytest.raises(DistilBertModelLoadError, match="output dimension"):
        DistilBertDefectClassifier(model_dir=tmp_path).validate_checkpoint()


def test_named_config_is_not_automatically_trusted(tmp_path):
    config, _ = _checkpoint(tmp_path)
    config["id2label"] = {str(i): label for i, label in enumerate(DEFECT_LABELS)}
    config["label2id"] = {label: i for i, label in enumerate(DEFECT_LABELS)}
    (tmp_path / "config.json").write_text(json.dumps(config))
    assert DistilBertDefectClassifier(model_dir=tmp_path).validate_checkpoint()["mapping_status"] == "UNVERIFIED"
    wrong = DistilBertDefectClassifier(model_dir=tmp_path, semantic_labels=DEFECT_LABELS,
                                     mapping_provenance="caller assertion")
    with pytest.raises(DistilBertModelLoadError, match="identity mismatch"):
        wrong.validate_checkpoint()


def test_custom_tokenizer_without_encode_support_reports_unknown_truncation():
    classifier = _create_mock_classifier([0.0] * 5)
    classifier.tokenizer.encode.side_effect = NotImplementedError
    result = classifier.classify("The system shall log events.")
    assert result.truncated is None and result.input_tokens is None


def test_formatted_defects_fit_frozen_contract_without_invented_spans():
    from c1_requirement_quality.cli import _validate_contract_artifact
    root = Path(__file__).resolve().parents[2]
    artifact = json.loads((root / "contracts/fixtures/golden/example-registration/c1/validated_requirements.json").read_text())
    classifier = _create_mock_classifier([2.0] * 5, threshold=0.5)
    result = classifier.classify(artifact["requirements"][0]["original_text"])
    defects = classifier.format_contract_defects(result)
    assert len(defects) == 5
    assert all("evidence_span" not in defect for defect in defects)
    artifact["requirements"][0]["defects"] = defects
    _validate_contract_artifact(artifact)


def test_injected_model_cannot_borrow_checkpoint_identity():
    classifier = DistilBertDefectClassifier(
        tokenizer=MagicMock(), model=MagicMock(), semantic_labels=DEFECT_LABELS,
        mapping_provenance="caller assertion")
    classifier.tokenizer.return_value = {"input_ids": [101, 102]}
    classifier.model.return_value.logits = [[0.0] * 5]
    result = classifier.classify("The system shall log events.", threshold=0.1)
    assert result.mapping_status == "UNVERIFIED"
    assert result.predicted_defects == [] and result.checkpoint_sha256 is None
    assert classifier.format_contract_defects(result) == []


def test_unknown_checkpoint_cannot_be_named_by_caller_provenance(tmp_path):
    _checkpoint(tmp_path)
    classifier = DistilBertDefectClassifier(model_dir=tmp_path, semantic_labels=DEFECT_LABELS,
                                          mapping_provenance="claimed verified")
    with pytest.raises(DistilBertModelLoadError, match="identity mismatch"):
        classifier.validate_checkpoint()


@pytest.mark.parametrize("asset", list(EXPERIMENT2_FILES))
def test_any_changed_asset_invalidates_authenticated_identity(tmp_path, monkeypatch, asset):
    import hashlib
    import c1_requirement_quality.ml_defect_classifier as module
    _checkpoint(tmp_path)
    # Synthetic asset manifest exercises binding; it is not the real checkpoint.
    manifest = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
                for name in EXPERIMENT2_FILES}
    monkeypatch.setattr(module, "EXPERIMENT2_FILES", manifest)
    classifier = DistilBertDefectClassifier(model_dir=tmp_path)
    assert classifier.validate_checkpoint()["mapping_status"] == "VERIFIED"
    classifier._identity_verified = True
    with (tmp_path / asset).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(DistilBertModelLoadError, match="identity mismatch"):
        classifier.validate_checkpoint()


def test_default_tokenizer_call_matches_training_limit():
    classifier = _create_mock_classifier([0.0] * 5)
    classifier.classify("The system shall log events.")
    assert classifier.tokenizer.call_args.kwargs["max_length"] == TRAINING_MAX_LENGTH == 128
    assert classifier.tokenizer.call_args.kwargs["truncation"] is True


def test_result_from_another_checkpoint_cannot_be_formatted():
    classifier = _create_mock_classifier([2.0] * 5, threshold=0.5)
    result = classifier.classify("The system shall log events.")
    assert classifier.format_contract_defects(replace(result, checkpoint_sha256="0" * 64)) == []
