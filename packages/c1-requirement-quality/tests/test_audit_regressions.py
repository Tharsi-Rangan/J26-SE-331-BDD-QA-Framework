"""Controlled audit regressions: synthetic inputs, mocked models, no network."""
import copy
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from c1_requirement_quality import cli, contract, effective_consistency, wizard
from c1_requirement_quality.analysis.consistency_analyser import analyse_consistency
from c1_requirement_quality.rag.fact_extractor import Fact
from c1_requirement_quality.rag.verifier import verify_symbolically, VerificationOutcome
from c1_requirement_quality.rewrite_generator import generate_candidate_suggestions, generate_candidates_run
from test_rewrite_generator import _minimal_artifact, _req


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("Network forbidden"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf/hub"))
    monkeypatch.setenv("C1_MODELS_DIR", str(tmp_path / "models"))


@pytest.mark.parametrize("left,right", [("<", ">"), ("<=", ">="), ("=", "!="), ("≤", "≥")])
def test_numeric_identity_is_operator_sensitive(left, right):
    a = f"The system shall respond in {left} 2 seconds."
    b = f"The system shall respond in {right} 2 seconds."
    result = analyse_consistency([{"requirement_id": "A", "text": a}, {"requirement_id": "B", "text": b}])
    if left == "<=":  # inclusive bounds overlap at exactly 2
        assert result["pairs"][0]["classification"] == "consistent"
    else:
        assert result["pairs"][0]["classification"] != "consistent"
    assert verify_symbolically(Fact(b), a, "source").outcome != VerificationOutcome.SUPPORTED
    assert verify_symbolically(Fact(a), a, "source").outcome == VerificationOutcome.SUPPORTED


def test_selected_generation_never_transmits_peer_context(verified_legacy):
    a = _req("REQ-EX-001", "The system shall send email.")
    b = _req("REQ-EX-002", "The system shall store secret records.")
    a["grounding"]["evidence"][0]["text"] += " " + b["original_text"]
    backend = SimpleNamespace(generate=Mock(return_value=[]))
    artifact = _minimal_artifact([a, b])
    before = copy.deepcopy(artifact)
    answers = [{"requirement_id": a["requirement_id"], "clarification_answers": []},
               {"requirement_id": b["requirement_id"], "clarification_answers": [{"question": "Secret?", "answer": "private-answer"}]}]
    report = generate_candidate_suggestions(artifact, a["original_text"] + "\n" + b["original_text"],
        backend=backend, requirement_ids=[a["requirement_id"]], clarification_answers=answers, workflow_context=verified_legacy(artifact, a["original_text"] + "\n" + b["original_text"]))
    assert backend.generate.call_count == 1
    payload = repr(backend.generate.call_args)
    assert a["original_text"] in payload
    assert b["original_text"] not in payload and "private-answer" not in payload
    assert [r["requirement_id"] for r in report["requirements"]] == [a["requirement_id"]]
    assert artifact == before and not any(r["bdd_ready"] for r in artifact["requirements"])
    backend.generate.reset_mock()
    with pytest.raises(ValueError, match="active artifact"):
        generate_candidate_suggestions(artifact, "", backend=backend, requirement_ids=["unknown"], workflow_context=verified_legacy(artifact, ""))
    backend.generate.assert_not_called()


def test_wizard_cloud_selection_and_denial(tmp_path, monkeypatch):
    import c1_requirement_quality.rewrite_generator as generator
    calls = []
    def generate(*args, **kwargs):
        calls.append(kwargs)
        args[2].parent.mkdir(parents=True, exist_ok=True)
        args[2].write_text('{"requirements": []}')
    monkeypatch.setattr(generator, "generate_candidates_run", generate)
    session = SimpleNamespace(workspace=tmp_path, current=tmp_path / "artifact", source=tmp_path / "source",
                              candidates=lambda path: [])
    ui = wizard.Wizard(tmp_path, ask=lambda prompt: "2", tell=lambda text: None, groq_backend=object())
    assert ui.generate_candidates_groq(session, "REQ-EX-001") == []
    assert calls == []
    ui.ask = lambda prompt: "1"
    ui.generate_candidates_groq(session, "REQ-EX-001")
    assert len(calls) == 1 and calls[0]["requirement_ids"] == ["REQ-EX-001"]


def test_external_schema_configuration_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setenv("C1_CONTRACT_SCHEMA_DIR", str(tmp_path / "missing"))
    with pytest.raises(FileNotFoundError, match="C1_CONTRACT_SCHEMA_DIR"):
        contract.get_schema_dir()
    monkeypatch.setenv("C1_CONTRACT_SCHEMA_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="standalone installations"):
        contract.validate_contract_artifact({})


def test_candidate_cli_advertises_only_supported_grounding():
    args = ["generate-candidates", "--in", "input.json", "--srs", "source.md", "--out", "output.json"]
    assert cli.build_parser().parse_args(args).grounding_mode == "lexical"
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([*args, "--grounding-mode", "rag"])


def test_default_and_explicit_loaders_use_offline_paths(tmp_path, monkeypatch):
    from c1_requirement_quality.rag import retriever, verifier
    embedding = Mock(return_value=object())
    pipeline = Mock(return_value=object())
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=embedding))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(pipeline=pipeline))
    monkeypatch.setattr(retriever, "get_minilm_cache_dir", lambda: tmp_path / "minilm")
    monkeypatch.setattr(verifier, "get_deberta_nli_cache_dir", lambda: tmp_path / "deberta")
    retriever.SentenceTransformersEmbedder()._load_model()
    verifier.LocalNLI()._load()
    assert embedding.call_args.args == (str(tmp_path / "minilm"),)
    assert pipeline.call_args.kwargs["model"] == str(tmp_path / "deberta")
    assert embedding.call_args.kwargs["local_files_only"] is True
    assert pipeline.call_args.kwargs["local_files_only"] is True
    retriever.SentenceTransformersEmbedder("explicit-embedding")._load_model()
    verifier.LocalNLI("explicit-nli")._load()
    assert embedding.call_args.args == ("explicit-embedding",)
    assert pipeline.call_args.kwargs["model"] == "explicit-nli"


def test_batch_consistency_matches_individual_and_rebuilds(monkeypatch):
    rows = [_req(f"REQ-EX-{i:03}", text) for i, text in enumerate([
        "The system shall send email.", "The system shall store records.", "The system shall log events."], 1)]
    expected = {r["requirement_id"]: effective_consistency.assess(r["requirement_id"], rows) for r in rows}
    analyse = Mock(wraps=effective_consistency.analyse_consistency)
    monkeypatch.setattr(effective_consistency, "analyse_consistency", analyse)
    assert effective_consistency.assess_all(rows) == expected
    assert analyse.call_count == 1
    rows[1]["final_text"] = "The system shall not send email."
    updated = effective_consistency.assess_all(rows)
    assert updated[rows[0]["requirement_id"]]["check"] == "fail"
    assert analyse.call_count == 2


def test_loaded_checkpoint_reuses_hashes_and_revalidates_changes(tmp_path, monkeypatch):
    from c1_requirement_quality.ml.ml_defect_classifier import DistilBertDefectClassifier, EXPERIMENT2_FILES, DistilBertModelLoadError
    for name in EXPERIMENT2_FILES:
        (tmp_path / name).write_text("synthetic")
    report = {"mapping_status": "UNVERIFIED", "mapping_provenance": None}
    validate = Mock(return_value=report)
    monkeypatch.setattr(DistilBertDefectClassifier, "validate_checkpoint", validate)
    model = SimpleNamespace(eval=lambda: None)
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=lambda *a, **k: object()),
        AutoModelForSequenceClassification=SimpleNamespace(from_pretrained=lambda *a, **k: model)))
    classifier = DistilBertDefectClassifier(model_dir=tmp_path)
    classifier._ensure_loaded()
    assert validate.call_count == 2
    classifier._ensure_loaded()
    assert validate.call_count == 2
    asset = tmp_path / next(iter(EXPERIMENT2_FILES))
    asset.write_text("changed-size")
    classifier._ensure_loaded()
    assert validate.call_count == 3
    asset.write_text("changed-size-again")
    validate.return_value = {**report, "checkpoint_sha256": "different"}
    with pytest.raises(DistilBertModelLoadError, match="changed after"):
        classifier._ensure_loaded()


def test_successful_publication_removes_only_owned_pending_names(tmp_path):
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall send email.\n")
    sentinel = tmp_path / ".c1-run-pending-preexisting"
    sentinel.mkdir()
    cli.run(source, tmp_path / "run", "RUN-20261017-220000-ab12", registry_path=tmp_path / "registry.json")
    assert list(tmp_path.glob(".c1-run-pending-*")) == [sentinel]
    output = tmp_path / "candidates.json"
    generate_candidates_run(tmp_path / "run/c1/validated_requirements.json", source, output)
    assert output.is_file() and not list(tmp_path.glob(".c1-candidates-pending-*"))
    assert sentinel.is_dir()


def test_existing_registry_lock_is_never_removed(tmp_path):
    from c1_requirement_quality.requirement_registry import RequirementRegistry
    path = tmp_path / "registry.json"
    lock = tmp_path / "registry.json.lock"
    lock.write_text("unknown owner")
    with pytest.raises(RuntimeError, match="ownership/inactivity"):
        with RequirementRegistry(path, "EX").publication_lock():
            pytest.fail("Existing lock must exclude publication")
    assert lock.read_text() == "unknown owner" and not path.exists()


def test_failed_run_preserves_its_staging(tmp_path):
    source = tmp_path / "empty.md"
    source.write_text("")
    with pytest.raises(RuntimeError, match="staging retained"):
        cli.run(source, tmp_path / "run", "RUN-20261017-220000-ab12", registry_path=tmp_path / "registry.json")
    assert len(list(tmp_path.glob(".c1-run-pending-*"))) == 1
    assert not (tmp_path / "run/c1").exists()


@pytest.mark.parametrize("component", ["minilm", "deberta"])
def test_canonical_cache_primary_and_repository_fallback(tmp_path, monkeypatch, component):
    from c1_requirement_quality import model_paths as paths
    package = tmp_path / "repo/packages/c1"
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setattr(paths, "get_package_root", lambda: package)
    revision = paths.MINILM_CACHED_REVISION if component == "minilm" else paths.DEBERTA_NLI_CACHED_REVISION
    name = "models--sentence-transformers--all-MiniLM-L6-v2" if component == "minilm" else "models--cross-encoder--nli-deberta-v3-small"
    resolve = paths.get_minilm_cache_dir if component == "minilm" else paths.get_deberta_nli_cache_dir
    relative = f"{name}/snapshots/{revision}"
    fallback = tmp_path / "repo/.pytest-tmp/hf-cache/hub" / relative
    fallback.mkdir(parents=True)
    assert resolve() == fallback
    primary = tmp_path / "hf/hub" / relative
    primary.mkdir(parents=True)
    assert resolve() == primary
