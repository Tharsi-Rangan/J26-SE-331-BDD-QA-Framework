"""CLI mechanics with synthetic embeddings only; no semantic-quality claims."""
import hashlib
import json
from pathlib import Path

import pytest

from c1_requirement_quality import cli, similarity_diagnostics as diagnostics
from c1_requirement_quality.rag.retriever import SentenceTransformersEmbedder


@pytest.fixture(autouse=True)
def block_real_models(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real MiniLM loading forbidden")
    monkeypatch.setattr(SentenceTransformersEmbedder, "_load_model", forbidden)


@pytest.fixture
def model_directory(tmp_path):
    directory = tmp_path / "mock-minilm"
    (directory / "1_Pooling").mkdir(parents=True)
    config = {"model_type": "bert", "hidden_size": 384, "num_hidden_layers": 6}
    for name in ["modules.json", "sentence_bert_config.json", "tokenizer.json", "tokenizer_config.json", "1_Pooling/config.json"]:
        (directory / name).write_text("{}")
    (directory / "config.json").write_text(json.dumps(config))
    (directory / "model.safetensors").write_bytes(b"FAKE weights; never loaded")
    return directory


@pytest.fixture
def fake_embeddings(monkeypatch):
    calls = []
    def encode(self, texts, *, batch_size=8):
        calls.append(list(texts))
        vectors = []
        for text in texts:
            if "unrelated" in text:
                vectors.append([0, 0, 1])
            elif "related" in text:
                vectors.append([0.8, 0.6, 0])
            else:
                vectors.append([1, 0, 0])
        self._model = object()  # synthetic load metadata, not a loaded model
        return {"embeddings": vectors, "diagnostics": [
            {"input_tokens": 12, "token_limit": 256, "truncated": False} for _ in texts]}
    monkeypatch.setattr(SentenceTransformersEmbedder, "encode_with_diagnostics", encode)
    monkeypatch.setattr(diagnostics, "available_memory_bytes", lambda: 4 * 1024 ** 3)
    return calls


@pytest.fixture
def validated(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Requirements\n1. The system shall send email.\n2. The system shall send email after login.\n3. The system shall store related records.\n4. The system shall store unrelated records.\n", encoding="utf-8")
    out = tmp_path / "run"
    cli.run(source, out, "RUN-20261015-230000-sm01", registry_path=tmp_path / "registry.json")
    path = out / "c1/validated_requirements.json"
    # Unit fixture: identical original text tests pair identities independent of text equality.
    value = json.loads(path.read_text(encoding="utf-8"))
    value["requirements"][1]["original_text"] = value["requirements"][0]["original_text"]
    value["requirements"][1]["final_text"] = value["requirements"][0]["original_text"]
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def arguments(source, out, model, *extra):
    return ["diagnose-similarity", "--in", str(source), "--out", str(out), "--model-dir", str(model), *extra]


def test_mock_cli_identical_related_unrelated_threshold_equality(validated, tmp_path, model_directory, fake_embeddings):
    before = {p: p.read_bytes() for p in validated.parent.rglob("*") if p.is_file()}
    out = tmp_path / "similarity.json"
    assert cli.main(arguments(validated, out, model_directory, "--threshold", "0.8", "--batch-size", "2")) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert len(report["pairs"]) == 6
    ids = [r["requirement_id"] for r in report["requirements"]]
    assert [p["requirement_ids"] for p in report["pairs"]] == [[ids[i], ids[j]] for i in range(4) for j in range(i + 1, 4)]
    assert len({tuple(p["requirement_ids"]) for p in report["pairs"]}) == 6
    assert report["pairs"][0]["similarity"] == 1
    assert report["pairs"][1]["similarity"] == pytest.approx(0.8)
    assert report["pairs"][1]["selected_candidate"] is True
    assert report["pairs"][2]["similarity"] == 0
    assert report["pairs"][2]["selected_candidate"] is False
    assert all(0 <= p["similarity"] <= 1 for p in report["pairs"])
    assert all(len(batch) <= 2 for batch in fake_embeddings)
    assert report["status"] == "experimental" and report["advisory_only"] and report["human_review_required"]
    assert report["decision_effect"] == "none" and report["model"]["local_files_only"]
    assert report["model"]["cache_revision"] is None
    original = json.loads(validated.read_text(encoding="utf-8"))
    assert report["source_document"] == original["source_document"]
    assert [r["original_text"] for r in report["requirements"]] == [r["original_text"] for r in original["requirements"]]
    assert report["input_sha256"] == hashlib.sha256(validated.read_bytes()).hexdigest()
    assert all(p.read_bytes() == value for p, value in before.items())
    cli._validate_contract_artifact(original)


def test_threshold_unset_selects_nothing(validated, tmp_path, model_directory, fake_embeddings):
    out = tmp_path / "scores.json"
    assert cli.main(arguments(validated, out, model_directory)) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["selected_candidate_pairs"] == []
    assert all(p["selected_candidate"] is None for p in report["pairs"])


@pytest.mark.parametrize("extra", [["--threshold", "nan"], ["--threshold", "1.1"], ["--batch-size", "0"], ["--max-pairs", "2"]])
def test_invalid_options_fail_before_inference(validated, tmp_path, model_directory, fake_embeddings, extra):
    out = tmp_path / "no.json"
    assert cli.main(arguments(validated, out, model_directory, *extra)) == 1
    assert fake_embeddings == [] and not out.exists()


def test_existing_output_is_not_overwritten(validated, tmp_path, model_directory, fake_embeddings):
    out = tmp_path / "existing.json"
    out.write_text("keep")
    assert cli.main(arguments(validated, out, model_directory)) == 1
    assert out.read_text() == "keep" and fake_embeddings == []


def test_missing_cache_fails_without_loading(validated, tmp_path, fake_embeddings):
    out = tmp_path / "no.json"
    assert cli.main(arguments(validated, out, tmp_path / "missing")) == 1
    assert fake_embeddings == [] and not out.exists()


@pytest.mark.parametrize("mode", ["low", "unknown"])
def test_memory_refusal(validated, tmp_path, model_directory, fake_embeddings, monkeypatch, mode):
    def memory():
        if mode == "unknown":
            raise RuntimeError("Cannot measure available memory")
        return 1024 ** 3
    monkeypatch.setattr(diagnostics, "available_memory_bytes", memory)
    out = tmp_path / "no.json"
    assert cli.main(arguments(validated, out, model_directory)) == 1
    assert fake_embeddings == [] and not out.exists()


@pytest.mark.parametrize("error", [MemoryError(), RuntimeError("Model unavailable"), ValueError("bad dimensions")])
def test_model_failure_publishes_nothing(validated, tmp_path, model_directory, fake_embeddings, monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(SentenceTransformersEmbedder, "encode_with_diagnostics", fail)
    out = tmp_path / "no.json"
    assert cli.main(arguments(validated, out, model_directory)) == 1
    assert not out.exists()


def test_kinmail_mocked_cli_produces_210_pairs(tmp_path, model_directory, fake_embeddings):
    source = Path(__file__).resolve().parents[1] / "local-inference/kinmail-validated-requirements.json"
    if not source.is_file():
        pytest.skip("Local Kinmail case study not supplied")
    before = source.read_bytes()
    out = tmp_path / "kinmail-MOCKED-similarity.json"
    assert cli.main(arguments(source, out, model_directory)) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert len(report["requirements"]) == 21 and len(report["pairs"]) == 210
    assert len({tuple(p["requirement_ids"]) for p in report["pairs"]}) == 210
    assert source.read_bytes() == before
