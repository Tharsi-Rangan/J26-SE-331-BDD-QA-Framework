"""Offline mechanics tests only: fake vectors do not validate semantic quality."""
import copy
import json
import sys
from types import SimpleNamespace

import pytest

from c1_requirement_quality.requirement_similarity import requirement_pair_diagnostics
from c1_requirement_quality.rag.retriever import SentenceTransformersEmbedder


class FakeEmbedder:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return [self.vectors[text] for text in texts]


def rows(*texts):
    return [{"requirement_id": f"REQ-EX-{i:03}", "original_text": text}
            for i, text in enumerate(texts, 1)]


@pytest.fixture(autouse=True)
def prohibit_real_loading(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Real model loading is forbidden in Phase 2B.1 tests")
    monkeypatch.setattr(SentenceTransformersEmbedder, "_load_model", fail)


def test_unique_sorted_pairs_preserve_inputs_and_decisions():
    records = rows(" A ", "B", "C")
    records[0].update(tier="TIER_2_CLARIFY", bdd_ready=False, human_decision="pending")
    original = copy.deepcopy(records)
    encoder = FakeEmbedder({" A ": [1, 0], "B": [1, 0], "C": [0, 1]})
    report = requirement_pair_diagnostics(list(reversed(records)), embedder=encoder, threshold=1, batch_size=2)
    assert records == original
    assert [p["requirement_ids"] for p in report["pairs"]] == [
        ["REQ-EX-001", "REQ-EX-002"], ["REQ-EX-001", "REQ-EX-003"], ["REQ-EX-002", "REQ-EX-003"]]
    assert [p["possible_duplicate"] for p in report["pairs"]] == [True, False, False]
    assert encoder.calls == [[" A ", "B"], ["C"]]
    assert report["requirements"][0]["original_text"] == " A "
    assert report["advisory_only"] and report["human_review_required"]
    assert report["status"] == "experimental" and report["loaded_model"] is None
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("threshold,expected", [(None, None), (0, True), (0.5, True), (1, False)])
def test_threshold_boundary_without_display_rounding(threshold, expected):
    fake = FakeEmbedder({"A": [1, 0], "B": [0.5, 3 ** 0.5 / 2]})
    report = requirement_pair_diagnostics(rows("A", "B"), embedder=fake, threshold=threshold)
    assert report["pairs"][0]["similarity"] == pytest.approx(0.5)
    assert report["pairs"][0]["possible_duplicate"] is expected


def test_cutoff_does_not_round_a_near_boundary_score_up():
    fake = FakeEmbedder({"A": [1, 0], "B": [0.49999, (1 - 0.49999 ** 2) ** 0.5]})
    pair = requirement_pair_diagnostics(rows("A", "B"), embedder=fake, threshold=0.5)["pairs"][0]
    assert pair["similarity"] < 0.5 and pair["possible_duplicate"] is False


@pytest.mark.parametrize("threshold", [True, "0.5", float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_thresholds_rejected_before_encoding(threshold):
    with pytest.raises((ValueError, TypeError)):
        requirement_pair_diagnostics(rows("A", "B"), threshold=threshold)


@pytest.mark.parametrize("vector", [[], [0, 0], [float("nan"), 1], [float("inf"), 1], [True, 1], ["1", 0], [1, 0, 0]])
def test_invalid_vectors_rejected_across_batches(vector):
    with pytest.raises(ValueError):
        requirement_pair_diagnostics(rows("A", "B"), embedder=FakeEmbedder({"A": [1, 0], "B": vector}), batch_size=1)


def test_extreme_finite_vectors_and_negative_cosine():
    for magnitude in [1e300, 1e-300]:
        report = requirement_pair_diagnostics(rows("A", "B"), embedder=FakeEmbedder({
            "A": [magnitude, 0], "B": [-magnitude, 0]}))
        assert report["pairs"][0]["similarity"] == 0


@pytest.mark.parametrize("records", [[], rows("A")])
def test_no_model_needed_without_a_pair(records):
    report = requirement_pair_diagnostics(records)
    assert report["pairs"] == [] and report["loaded_model"] is None


def test_pair_budget_rejected_before_loading():
    with pytest.raises(ValueError, match="max_pairs"):
        requirement_pair_diagnostics(rows("A", "B", "C"), max_pairs=2)


@pytest.mark.parametrize("options", [{"batch_size": 0}, {"batch_size": True}, {"max_pairs": 0}])
def test_invalid_resource_limits(options):
    with pytest.raises(ValueError):
        requirement_pair_diagnostics([], **options)


@pytest.mark.parametrize("records", [[{}], rows(""), [{"requirement_id": " ", "original_text": "A"}],
                                     [rows("A")[0], rows("B")[0]], [None]])
def test_invalid_requirement_records(records):
    with pytest.raises(ValueError):
        requirement_pair_diagnostics(records)


def test_embedding_count_mismatch():
    with pytest.raises(ValueError, match="count"):
        requirement_pair_diagnostics(rows("A", "B"), embedder=SimpleNamespace(encode=lambda texts: [[1, 0]]))


def test_injected_truncation_is_unknown():
    report = requirement_pair_diagnostics(rows("A", "B"), embedder=FakeEmbedder({"A": [1], "B": [1]}))
    assert all(row["embedding_diagnostics"]["truncated"] is None for row in report["requirements"])


def test_existing_adapter_batches_and_reports_truncation_using_fake_model(monkeypatch, tmp_path):
    calls, constructors = [], []
    class FakeModel:
        max_seq_length = 3
        tokenizer = SimpleNamespace(encode=lambda text, **kwargs: list(range(len(text.split()) + 2)))

        def __init__(self, name, **kwargs):
            constructors.append((name, kwargs))

        def encode(self, texts, **kwargs):
            calls.append((list(texts), kwargs))
            return [[1.0, 0.0] for _ in texts]

    # Exercise the real local-only loader with a fake library, never real weights.
    monkeypatch.undo()
    snapshot = tmp_path / "hf-cache" / "snapshots" / "fake-local-revision"
    snapshot.mkdir(parents=True)
    monkeypatch.setattr("c1_requirement_quality.rag.retriever.get_minilm_cache_dir", lambda: snapshot)
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=FakeModel))
    encoder = SentenceTransformersEmbedder()
    report = requirement_pair_diagnostics(rows("A", "B C", "D"), embedder=encoder, batch_size=2)
    assert constructors == [(str(snapshot), {"local_files_only": True, "device": "cpu"})]
    assert [len(batch) for batch, _ in calls] == [2, 1]
    assert all(kwargs["batch_size"] == 2 for _, kwargs in calls)
    assert [r["embedding_diagnostics"]["truncated"] for r in report["requirements"]] == [False, True, False]
    assert report["embedding_dimension"] == 2
