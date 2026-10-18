"""Default wizard RAG integration; all models are injected offline test doubles."""
import hashlib
import json
import socket
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from c1_requirement_quality import cli, wizard
from c1_requirement_quality.demo_workflow import DemoSession
from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser
from c1_requirement_quality.rag.verifier import FactVerifier
from c1_requirement_quality.rag.retriever import RetrievalResult
from c1_requirement_quality.ml.ml_defect_classifier import EXPERIMENT2_LABELS, EXPERIMENT2_FILES


class Classifier:
    model_name = "distilbert-requirement-defects"

    def validate_checkpoint(self):
        return {"mapping_status": "VERIFIED", "checkpoint_sha256": EXPERIMENT2_FILES["model.safetensors"],
                "mapping_provenance": "Injected test classifier; no real inference"}

    def classify(self, text, *, requirement_id):
        return SimpleNamespace(to_dict=lambda: {**self.validate_checkpoint(), "requirement_id": requirement_id,
            "text": text, "scores": dict.fromkeys(EXPERIMENT2_LABELS, 0.2), "threshold_applied": None})


@pytest.fixture
def app(tmp_path, monkeypatch):
    from c1_requirement_quality.ml import ml_diagnostics
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("Network forbidden"))
    monkeypatch.setattr(ml_diagnostics, "available_memory_bytes", lambda: 4 * 1024**3)
    control = {"label": "entailment", "calls": [], "preflight_error": None}

    class Embedder:
        def encode(self, texts):
            return [[1.0, float(len(text))] for text in texts]

    class NLI:
        def classify(self, premise, hypothesis):
            if control["label"] == "error":
                raise RuntimeError("local NLI inference failed")
            if control["label"] == "error_empty":
                raise RuntimeError()
            return control["label"]

    class InitialRAG(RAGGroundingAnalyser):
        def __init__(self, text, **kwargs):
            if control.get("constructor_error"):
                raise RuntimeError("RAG index initialization failed")
            super().__init__(text, embedder=Embedder(), verifier=FactVerifier(NLI()), use_spacy=False)
            # Isolate applicable NLI evidence from exact self-matches for these
            # outcome-mapping tests; both passages exist in the fixture source.
            self.retriever.retrieve = lambda query, *a: [RetrievalResult(
                "SRS-L0002" if "retain" in query else "SRS-L0004",
                "The system must retain logs." if "retain" in query else "The system must allow login.",
                "Evidence", 0.9, 2 if "retain" in query else 4, 2 if "retain" in query else 4)]
            if control.get("mixed"):
                self.retriever.retrieve = lambda *a: [
                    RetrievalResult("support", "The system shall retain logs.", "Policy", 0.9, 1, 1),
                    RetrievalResult("conflict", "The system shall not retain logs.", "Policy", 0.8, 2, 2)]

        def model_provenance(self):
            if control["preflight_error"]:
                raise FileNotFoundError(control["preflight_error"])
            return {"test_double": True, "local_files_only": True, "models": ["injected MiniLM", "injected NLI"]}

        def analyse(self, text):
            control["calls"].append(text)
            return super().analyse(text)

    monkeypatch.setattr(cli, "RAGGroundingAnalyser", InitialRAG)
    source = tmp_path / "srs.md"
    source.write_text("# Evidence\nThe system must retain logs.\n\nThe system must allow login.\n\n# Requirements\n1. The system shall retain logs.\n2. The system shall allow login.\n")
    messages = []
    ui = wizard.Wizard(tmp_path / "sessions", tell=messages.append, classifier=Classifier())
    return ui, source, control, messages


@pytest.mark.parametrize("label,status,outcome", [
    ("entailment", "supported", "SUPPORTED"),
    ("contradiction", "unsupported", "CONTRADICTED"),
    ("neutral", "unsupported", "INCONCLUSIVE"),
])
def test_default_wizard_runs_rag_and_seals_results(app, label, status, outcome):
    ui, source, control, messages = app
    control["label"] = label
    session = ui.create(source)
    rows = session.read()[0]["requirements"]
    assert control["calls"] == [r["original_text"] for r in rows]
    assert all(r["grounding"]["status"] == status for r in rows)
    assert all(r["human_decision"] == "pending" and not r["bdd_ready"] for r in rows)
    diagnostics = json.loads((session.current.parent / "rag_diagnostics.json").read_text())
    assert [d["requirement_id"] for d in diagnostics] == [r["requirement_id"] for r in rows]
    assert all(d["diagnostics"][0]["outcome"] == outcome for d in diagnostics)
    metadata = json.loads((session.current.parent / "internal/rag_provenance.json").read_text())
    assert metadata["input_sha256"] == hashlib.sha256(session.current.read_bytes()).hexdigest()
    assert metadata["models"]["test_double"] is True
    assert metadata["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert any(m.startswith("[COMPLETED] RAG grounding") for m in messages)
    cli._validate_contract_artifact(session.read()[0])
    before = session.current.read_bytes()
    with patch.object(cli, "RAGGroundingAnalyser", side_effect=AssertionError("Resume must reuse saved RAG")):
        assert DemoSession(session.workspace).read()[0] == session.read()[0]
    assert session.current.read_bytes() == before


def test_mixed_evidence_cannot_promote_grounding(app):
    ui, source, control, _ = app
    control["mixed"] = True
    session = ui.create(source)
    first = session.read()[0]["requirements"][0]
    assert first["grounding"]["status"] == "unsupported"
    assert {e["chunk_id"] for e in first["grounding"]["evidence"]} == {"support", "conflict"}
    assert first["bdd_ready"] is False


@pytest.mark.parametrize("failure", ["missing", "inference", "empty_error", "constructor"])
def test_rag_failure_is_incomplete_and_does_not_publish(app, failure):
    ui, source, control, messages = app
    if failure == "missing":
        control["preflight_error"] = "DeBERTa checkpoint missing"
    elif failure == "inference":
        control["label"] = "error"
    elif failure == "empty_error":
        control["label"] = "error_empty"
    else:
        control["constructor_error"] = True
    with pytest.raises(ValueError, match="Mandatory RAG grounding incomplete"):
        ui.create(source)
    workspace = next(ui.root.glob("session-*"))
    assert not (workspace / "initial/c1/validated_requirements.json").exists()
    assert not (workspace / "registry.json").exists()
    assert json.loads((workspace / "rag_failure.json").read_text())["status"] == "incomplete"
    assert not any(m.startswith("[COMPLETED] RAG grounding") for m in messages)
    with pytest.raises(ValueError, match="no inference replayed"):
        DemoSession(workspace)


def test_saved_diagnostics_tampering_is_rejected(app):
    ui, source, _, _ = app
    session = ui.create(source)
    (session.current.parent / "rag_diagnostics.json").write_text("[]")
    with pytest.raises(ValueError, match="RAG provenance or diagnostics hash mismatch"):
        DemoSession(session.workspace)


def test_initial_rag_cannot_be_downgraded_to_lexical_refinement(app, tmp_path):
    from c1_requirement_quality.rewrite_generator import generate_candidates_run
    ui, source, _, _ = app
    session = ui.create(source)
    original = session.current.read_bytes()
    rid = session.read()[0]["requirements"][0]["requirement_id"]
    # Explicit approval or unsupported factual text cannot bypass pending RAG
    # refinement integration. No pending receipt or child snapshot is created.
    with pytest.raises(ValueError, match="RAG refinement integration is pending"):
        session.apply({"requirement_id": rid, "selected_candidate_text":
            "The system shall retain logs for 99 years.", "human_decision": "approved"}, "Reviewer", True)
    assert not list((session.workspace / "events").glob("*.json"))
    actions = tmp_path / "actions.json"
    actions.write_text(json.dumps({"requirements": [{"requirement_id": rid, "human_decision": "not_required"}]}))
    with pytest.raises(ValueError, match="RAG refinement integration is pending"):
        cli.refine_run(session.current, source, actions, tmp_path / "child")
    with pytest.raises(ValueError, match="RAG refinement integration is pending"):
        generate_candidates_run(session.current, source, tmp_path / "candidates.json")
    assert not (tmp_path / "child").exists() and not (tmp_path / "candidates.json").exists()
    assert session.current.read_bytes() == original


def test_rag_failure_menu_pause_retains_incomplete_status(app):
    ui, source, control, messages = app
    control["preflight_error"] = "MiniLM assets missing"
    answers = iter(["1", "2", str(source), "1", "pause"])
    ui.ask = lambda prompt: next(answers)
    assert ui.run() == 0
    workspace = next(ui.root.glob("session-*"))
    assert (workspace / "rag_failure.json").is_file()
    assert not (workspace / "initial/c1/validated_requirements.json").exists()
    assert any("Paused safely" in message for message in messages)


@pytest.mark.parametrize("invalid", [None, "missing", "labels"])
def test_local_nli_provenance_checks_assets_and_label_mapping(tmp_path, monkeypatch, invalid):
    from c1_requirement_quality import model_paths
    from c1_requirement_quality.ml import similarity_diagnostics
    monkeypatch.setattr(similarity_diagnostics, "checkpoint_provenance",
        lambda directory: {"test_double": True, "local_files_only": True})
    monkeypatch.setattr(model_paths, "get_deberta_nli_cache_dir", lambda: tmp_path)
    config = {"model_type": "deberta-v2", "architectures": ["DebertaV2ForSequenceClassification"],
        "id2label": {"0": "contradiction", "1": "entailment", "2": "neutral"}}
    if invalid == "labels":
        config["id2label"]["0"] = "LABEL_0"
    (tmp_path / "config.json").write_text(json.dumps(config))
    for name in ("tokenizer.json", "tokenizer_config.json", "model.safetensors"):
        if invalid != "missing" or name != "model.safetensors":
            (tmp_path / name).write_text("synthetic test asset; not a real checkpoint")
    analyser = RAGGroundingAnalyser("Source", use_spacy=False)
    if invalid:
        with pytest.raises((FileNotFoundError, ValueError)):
            analyser.model_provenance()
    else:
        metadata = analyser.model_provenance()["nli"]
        assert metadata["local_files_only"] is True
        assert metadata["asset_sha256"]["model.safetensors"] == hashlib.sha256(
            (tmp_path / "model.safetensors").read_bytes()).hexdigest()
        assert metadata["label_mapping"] == config["id2label"]


@pytest.mark.parametrize("recovered", [True, False])
def test_rag_release_precedes_ml_and_does_not_bypass_memory_guard(app, monkeypatch, recovered):
    from c1_requirement_quality.ml import ml_diagnostics
    ui, source, control, _ = app
    events = []
    original_release = RAGGroundingAnalyser.release
    original_classify = Classifier.classify
    def release(self):
        count = original_release(self)
        events.append("release")
        return count
    def classify(self, *args, **kwargs):
        assert "release" in events
        events.append("ml")
        return original_classify(self, *args, **kwargs)
    monkeypatch.setattr(RAGGroundingAnalyser, "release", release)
    monkeypatch.setattr(Classifier, "classify", classify)
    monkeypatch.setattr(ml_diagnostics, "available_memory_bytes",
        lambda: (2 if not recovered and "release" in events else 4) * 1024**3)
    if recovered:
        session = ui.create(source)
        metadata = json.loads((session.current.parent / "internal/rag_provenance.json").read_text())
        assert metadata["memory"]["after_release_bytes"] == 4 * 1024**3
        assert events == ["release", "ml", "ml"]
    else:
        with pytest.raises(ValueError, match="at least 3 GiB required"):
            ui.create(source)
        assert events == ["release"]
        workspace = next(ui.root.glob("session-*"))
        assert json.loads((workspace / "ml_failure.json").read_text())["status"] == "incomplete"
        assert not (workspace / "ml_analysis.json").exists()
