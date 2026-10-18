"""Mocked CLI diagnostics only: no checkpoint weights or inference are loaded."""
import copy
import json
from types import SimpleNamespace

import pytest

from c1_requirement_quality import cli, ml_diagnostics as diagnostics
from c1_requirement_quality.ml_defect_classifier import (
    DistilBertDefectClassifier, EXPERIMENT2_LABELS, EXPERIMENT2_FILES,
)


@pytest.fixture(autouse=True)
def forbid_real_inference(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real model inference forbidden in diagnostic CLI tests")
    monkeypatch.setattr(DistilBertDefectClassifier, "_ensure_loaded", forbidden)


@pytest.fixture
def validated(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Requirements\n1. The system shall respond quickly.\n2. The system shall store logs.\n", encoding="utf-8")
    cli.run(source, tmp_path / "run", "RUN-20261015-220000-ml01", registry_path=tmp_path / "registry.json")
    return tmp_path / "run/c1/validated_requirements.json"


@pytest.fixture
def fake_adapter(monkeypatch):
    calls = []
    class FakeClassifier(DistilBertDefectClassifier):
        def validate_checkpoint(self):
            return {"mapping_status": "VERIFIED", "checkpoint_sha256": EXPERIMENT2_FILES["model.safetensors"],
                    "mapping_provenance": "MOCKED checkpoint validation; not real inference"}
        def classify(self, text, *, requirement_id):
            calls.append(requirement_id)
            scores = {label: 0.2 for label in EXPERIMENT2_LABELS}
            scores["VAGUE"] = 0.8
            result = {"requirement_id": requirement_id, "text": text, "model_name": self.model_name,
                "mapping_status": "VERIFIED", "checkpoint_sha256": EXPERIMENT2_FILES["model.safetensors"],
                "mapping_provenance": "MOCKED", "scores": scores,
                "predicted_defects": [k for k, v in scores.items() if self.threshold is not None and v >= self.threshold],
                "threshold_applied": self.threshold, "input_tokens": 12, "truncated": False, "token_limit": 128}
            return SimpleNamespace(to_dict=lambda: copy.deepcopy(result))
    monkeypatch.setattr(diagnostics, "DistilBertDefectClassifier", FakeClassifier)
    monkeypatch.setattr(diagnostics, "available_memory_bytes", lambda: 4 * 1024 ** 3)
    return calls


@pytest.mark.parametrize("cutoff,predictions", [(None, []), (0.8, ["VAGUE"])])
def test_mocked_cli_demonstration_preserves_every_input(validated, tmp_path, fake_adapter, cutoff, predictions, capsys):
    before = {p: p.read_bytes() for p in validated.parent.rglob("*") if p.is_file()}
    output = tmp_path / "diagnostics.json"
    args = ["diagnose-defects", "--in", str(validated), "--out", str(output)]
    if cutoff is not None:
        args += ["--threshold", str(cutoff)]
    assert cli.main(args) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    original = json.loads(validated.read_text(encoding="utf-8"))
    assert len(report["requirements"]) == len(fake_adapter) == 2
    assert report["advisory_only"] and report["human_review_required"] and report["decision_effect"] == "none"
    assert report["model"]["label_order"] == list(EXPERIMENT2_LABELS)
    assert "MOCKED" in report["model"]["checkpoint"]["mapping_provenance"]
    for row, source in zip(report["requirements"], original["requirements"]):
        assert row["requirement_id"] == source["requirement_id"] and row["text"] == source["original_text"]
        assert row["predicted_defects"] == predictions
        assert row["scores"]["VAGUE"] == 0.8
        assert row["status"] == "experimental" and row["human_review_required"]
        assert row["token_limit"] == 128
    assert all(p.read_bytes() == content for p, content in before.items())
    cli._validate_contract_artifact(json.loads(validated.read_text(encoding="utf-8")))
    assert "no C1 decisions changed" in capsys.readouterr().out


def test_low_memory_refuses_before_model_validation(validated, tmp_path, fake_adapter, monkeypatch, capsys):
    monkeypatch.setattr(diagnostics, "available_memory_bytes", lambda: 2 * 1024 ** 3)
    monkeypatch.setattr(diagnostics.DistilBertDefectClassifier, "validate_checkpoint", lambda self: pytest.fail("Must not access checkpoint"))
    output = tmp_path / "no.json"
    assert cli.main(["diagnose-defects", "--in", str(validated), "--out", str(output)]) == 1
    assert "at least 3 GiB required" in capsys.readouterr().err
    assert not output.exists() and fake_adapter == []


def test_checkpoint_revalidated_before_publication(validated, tmp_path, fake_adapter, monkeypatch):
    original = diagnostics.DistilBertDefectClassifier.validate_checkpoint
    calls = []
    def validation(self):
        report = original(self)
        calls.append(True)
        return report if len(calls) == 1 else {**report, "checkpoint_sha256": "changed"}
    monkeypatch.setattr(diagnostics.DistilBertDefectClassifier, "validate_checkpoint", validation)
    output = tmp_path / "changed.json"
    assert cli.main(["diagnose-defects", "--in", str(validated), "--out", str(output)]) == 1
    assert len(calls) == 2 and not output.exists()


def test_missing_checkpoint_is_clear_and_does_not_infer(validated, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(diagnostics, "available_memory_bytes", lambda: 4 * 1024 ** 3)
    output = tmp_path / "no.json"
    assert cli.main(["diagnose-defects", "--in", str(validated), "--out", str(output),
                     "--model-dir", str(tmp_path / "missing")]) == 1
    assert "directory does not exist" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize("cutoff", ["nan", "inf", "-0.1", "1.1"])
def test_invalid_threshold_before_inference(validated, tmp_path, fake_adapter, cutoff):
    output = tmp_path / "no.json"
    assert cli.main(["diagnose-defects", "--in", str(validated), "--out", str(output), "--threshold", cutoff]) == 1
    assert not output.exists() and fake_adapter == []


def test_existing_output_is_preserved(validated, tmp_path, fake_adapter):
    output = tmp_path / "existing.json"
    output.write_text("preserve")
    assert cli.main(["diagnose-defects", "--in", str(validated), "--out", str(output)]) == 1
    assert output.read_text() == "preserve" and fake_adapter == []


def test_out_of_memory_never_publishes_partial_results(validated, tmp_path, fake_adapter, monkeypatch, capsys):
    def fail(self, *args, **kwargs):
        raise MemoryError()
    monkeypatch.setattr(diagnostics.DistilBertDefectClassifier, "classify", fail)
    output = tmp_path / "no.json"
    assert cli.main(["diagnose-defects", "--in", str(validated), "--out", str(output)]) == 1
    assert "Insufficient memory during DistilBERT inference" in capsys.readouterr().err
    assert not output.exists()


def test_memory_measurement_failure_is_closed(validated, tmp_path, fake_adapter, monkeypatch):
    def fail():
        raise RuntimeError("Cannot determine available RAM")
    monkeypatch.setattr(diagnostics, "available_memory_bytes", fail)
    output = tmp_path / "no.json"
    assert cli.main(["diagnose-defects", "--in", str(validated), "--out", str(output)]) == 1
    assert not output.exists() and fake_adapter == []


def test_unverified_mapping_refused_before_classification(validated, tmp_path, fake_adapter, monkeypatch):
    monkeypatch.setattr(diagnostics.DistilBertDefectClassifier, "validate_checkpoint", lambda self: {"mapping_status": "UNVERIFIED"})
    output = tmp_path / "no.json"
    assert cli.main(["diagnose-defects", "--in", str(validated), "--out", str(output)]) == 1
    assert not output.exists() and fake_adapter == []


def test_input_change_during_inference_prevents_publication(validated, tmp_path, fake_adapter, monkeypatch):
    original_method = diagnostics.DistilBertDefectClassifier.classify
    def changed(self, *args, **kwargs):
        result = original_method(self, *args, **kwargs)
        with validated.open("a") as stream:
            stream.write(" ")
        return result
    monkeypatch.setattr(diagnostics.DistilBertDefectClassifier, "classify", changed)
    output = tmp_path / "no.json"
    assert cli.main(["diagnose-defects", "--in", str(validated), "--out", str(output)]) == 1
    assert not output.exists()
