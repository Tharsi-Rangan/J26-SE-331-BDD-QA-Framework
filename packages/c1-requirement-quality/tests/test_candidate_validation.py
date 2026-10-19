"""Candidate evidence records exercise the real verifier without model weights."""
import copy
import json
import socket

import pytest

from c1_requirement_quality import cli
from c1_requirement_quality.rag import candidate_validation as service
from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser
from c1_requirement_quality.rag.retriever import RetrievalResult
from c1_requirement_quality.rag.verifier import FactVerifier
from c1_requirement_quality.source_integrity import require_refinement_grounding


@pytest.fixture
def context(tmp_path, monkeypatch):
    from c1_requirement_quality.ml import ml_diagnostics
    monkeypatch.setattr(ml_diagnostics, "available_memory_bytes", lambda: 4 * 1024**3)
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("Network forbidden"))
    monkeypatch.setattr(service, "_require_memory", lambda: 4 * 1024**3)
    source = tmp_path / "srs.md"
    source.write_text(
        "# Requirements\n1. The system shall retain logs.\n\n# Evidence\n"
        "The system must retain logs.\n\nThe system shall not retain logs.\n\n"
        "The user shall view reports.\n", encoding="utf-8")
    cli.run(source, tmp_path / "initial", "RUN-20261018-120000-abcd", registry_path=tmp_path / "registry.json")
    artifact = tmp_path / "initial/c1/validated_requirements.json"
    rid = json.loads(artifact.read_text())["requirements"][0]["requirement_id"]
    control = {"label": "entailment", "passages": ["The system must retain logs."],
               "instances": [], "models": {"embedding": {"identifier": "injected MiniLM",
               "asset_sha256": {"weights": "test-mini"}, "local_files_only": True},
               "nli": {"identifier": "injected NLI", "asset_sha256": {"weights": "test-nli"},
                       "local_files_only": True}}}

    class Embedder:
        def encode(self, texts):
            return [[1.0, 0.0] for _ in texts]

    class NLI:
        def classify(self, premise, hypothesis):
            control.setdefault("nli_calls", []).append((premise, hypothesis))
            if control.get("raise"):
                raise RuntimeError("injected offline inference failure")
            return control["label"]

    class Analyser(RAGGroundingAnalyser):
        def __init__(self, text, **kwargs):
            nli = NLI()
            if "pipeline_prediction" in control:
                from c1_requirement_quality.rag.verifier import LocalNLI
                nli = LocalNLI()
                nli._pipeline = lambda *a, **k: [control["pipeline_prediction"]]
            super().__init__(text, embedder=Embedder(), verifier=FactVerifier(nli), **kwargs)
            control["instances"].append(self)
            self.released = False
            if not control.get("dense"):
                self.retriever.retrieve = lambda *a: [RetrievalResult(
                    "E-" + str(i), passage, "Evidence", 0.9, 1, 1)
                    for i, passage in enumerate(control["passages"])]

        def model_provenance(self):
            if control.get("provenance_error"):
                raise FileNotFoundError("missing local checkpoint")
            return copy.deepcopy(control["models"])

        def analyse(self, text):
            control["analyses"] = control.get("analyses", 0) + 1
            if control.get("empty_claims"):
                return {"diagnostics": [], "evidence": [], "errors": []}
            if control.get("outer_error"):
                raise RuntimeError("analyser failed")
            result = super().analyse(text)
            if control.get("after_analysis"):
                control["after_analysis"]()
            if control.get("changed_models"):
                control["models"]["nli"]["asset_sha256"]["weights"] = "changed"
            return result

        def release(self):
            self.released = True
            return super().release()

    return artifact, source, rid, tmp_path / "candidate-validation.json", control, Analyser


def publish(context, text="The system shall retain logs."):
    artifact, source, rid, out, _, factory = context
    return service.validate_candidate_run(artifact, source, rid, text, out, analyser_factory=factory)


def load(context, receipt, text="The system shall retain logs."):
    artifact, source, rid, out, _, factory = context
    return service.load_candidate_validation(out, artifact, source, rid, text,
        expected_sha256=receipt, analyser_factory=factory)


@pytest.mark.parametrize("passages,label,verdict", [
    (["The system must retain logs."], "entailment", "SUPPORTED"),
    (["The system shall not retain logs."], "entailment", "CONTRADICTED"),
    (["The system must retain logs.", "The system shall not retain logs."], "entailment", "CONTRADICTED"),
    (["The system must retain logs."], "neutral", "INCONCLUSIVE"),
    (["The user shall view reports."], "contradiction", "INCONCLUSIVE"),
    ([], "entailment", "INCONCLUSIVE"),
])
def test_verdicts_and_passage_provenance(context, passages, label, verdict):
    artifact, source, rid, out, control, _ = context
    before = artifact.read_bytes()
    control.update(passages=passages, label=label)
    record = load(context, publish(context))
    assert record["verdict"] == verdict
    assert record["completion_status"] == "completed"
    assert record["binding"]["candidate_id"] == service.stable_candidate_id(rid, record["candidate_text"])
    assert record["binding"]["source_sha256"] == service.sha256(source.read_bytes())
    assert record["models"] == control["models"]
    assert len(record["grounding"]["diagnostics"][0]["retrieved_evidence"]) == len(passages)
    assert all(instance.released for instance in control["instances"])
    assert control["analyses"] == 1  # Loading verifies metadata, never repeats inference.
    assert artifact.read_bytes() == before


@pytest.mark.parametrize("text", ["The system shall respond within [timeout].", "The system shall use TBD."])
def test_placeholders_never_supported(context, text):
    context[4]["passages"] = [text]
    record = load(context, publish(context, text), text)
    assert record["verdict"] == "INCONCLUSIVE"
    assert not context[4].get("nli_calls")


def test_no_claims_is_inconclusive(context):
    context[4]["empty_claims"] = True
    assert load(context, publish(context))["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_candidate_rejected_before_models(context, text):
    with pytest.raises(ValueError, match="nonempty"):
        publish(context, text)
    assert not context[3].exists() and not context[4]["instances"]


@pytest.mark.parametrize("failure", ["raise", "outer_error"])
def test_inference_error_is_incomplete_and_releases(context, failure):
    context[4][failure] = True
    record = load(context, publish(context))
    assert record["verdict"] == "ERROR" and record["completion_status"] == "incomplete"
    assert record["grounding"]["errors"]
    assert all(instance.released for instance in context[4]["instances"])


def test_candidate_tampering_and_wrong_receipt(context):
    receipt = publish(context)
    with pytest.raises(ValueError, match="binding"):
        load(context, receipt, "The system shall delete logs.")
    record = json.loads(context[3].read_bytes())
    record["verdict"] = "CONTRADICTED"
    context[3].write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="receipt"):
        load(context, receipt)


def test_source_tampering(context):
    receipt = publish(context)
    context[1].write_text("changed source", encoding="utf-8")
    with pytest.raises(ValueError, match="SRS hash mismatch"):
        load(context, receipt)


def test_changed_model_provenance(context):
    receipt = publish(context)
    context[4]["models"]["nli"]["asset_sha256"]["weights"] = "new-model"
    with pytest.raises(ValueError, match="model provenance"):
        load(context, receipt)
    assert all(i.released for i in context[4]["instances"])


@pytest.mark.parametrize("failure", ["provenance_error", "changed_models"])
def test_preflight_or_midrun_model_change_never_publishes(context, failure):
    context[4][failure] = True
    with pytest.raises((ValueError, FileNotFoundError)):
        publish(context)
    assert not context[3].exists()
    assert all(i.released for i in context[4]["instances"])


def test_stale_workflow_basis(context, monkeypatch):
    receipt = publish(context)
    original = service._verify_snapshot
    def changed(*args):
        text, manifest, artifact, state = original(*args)
        state = copy.deepcopy(state)
        state["requirements"][context[2]]["clarification_requested"] = True
        return text, manifest, artifact, state
    monkeypatch.setattr(service, "_verify_snapshot", changed)
    with pytest.raises(ValueError, match="binding"):
        load(context, receipt)


def test_memory_guard_precedes_resources(context, monkeypatch):
    from c1_requirement_quality.ml import ml_diagnostics
    monkeypatch.setattr(service, "_require_memory", ml_diagnostics._require_memory)
    monkeypatch.setattr(ml_diagnostics, "available_memory_bytes", lambda: 2 * 1024**3)
    with pytest.raises(RuntimeError, match="at least 3 GiB"):
        publish(context)
    assert not context[3].exists() and not context[4]["instances"]


def test_memory_failure_after_preflight_releases(context, monkeypatch):
    checks = iter([4 * 1024**3, RuntimeError("Insufficient available RAM")])
    def guard():
        value = next(checks)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(service, "_require_memory", guard)
    with pytest.raises(RuntimeError, match="Insufficient"):
        publish(context)
    assert not context[3].exists() and context[4]["instances"][0].released


def test_real_dense_retrieval_with_injected_vectors_stays_offline(context):
    context[4]["dense"] = True
    record = load(context, publish(context))
    assert record["grounding"]["diagnostics"][0]["retrieved_evidence"]
    assert all(i.released for i in context[4]["instances"])


def test_existing_output_not_overwritten_and_refinement_still_blocked(context):
    receipt = publish(context)
    with pytest.raises(FileExistsError):
        publish(context)
    assert service.sha256(context[3].read_bytes()) == receipt
    with pytest.raises(ValueError, match="RAG refinement integration is pending"):
        require_refinement_grounding({"rag_policy": "c1-initial-rag-v1"})


def test_initial_rag_snapshot_can_validate_but_cannot_refine(context, monkeypatch, tmp_path):
    _, source, _, _, control, factory = context
    monkeypatch.setattr(cli, "RAGGroundingAnalyser", factory)
    cli.run(source, tmp_path / "rag", "RUN-20261018-120001-abcd",
            registry_path=tmp_path / "rag-registry.json", grounding_mode="rag", mandatory_rag=True)
    artifact = tmp_path / "rag/c1/validated_requirements.json"
    rid = json.loads(artifact.read_bytes())["requirements"][0]["requirement_id"]
    bound = (artifact, source, rid, tmp_path / "rag-validation.json", control, factory)
    before = artifact.read_bytes()
    assert load(bound, publish(bound))["verdict"] == "SUPPORTED"
    actions = tmp_path / "actions.json"
    actions.write_text(json.dumps({"requirements": [{"requirement_id": rid,
        "selected_candidate_text": "The system must retain logs.", "human_decision": "approved"}]}))
    with pytest.raises(ValueError, match="RAG refinement integration is pending"):
        cli.refine_run(artifact, source, actions, tmp_path / "forbidden-child")
    assert not (tmp_path / "forbidden-child").exists()
    assert artifact.read_bytes() == before


def test_all_claims_must_be_supported(context):
    context[4]["passages"] = ["The system must retain logs."]
    text = "The system shall retain logs. The user shall view reports."
    record = load(context, publish(context, text), text)
    assert len(record["grounding"]["diagnostics"]) == 2
    assert record["verdict"] == "INCONCLUSIVE"


def test_retrieval_configuration_is_bound(context):
    artifact, source, rid, out, _, factory = context
    receipt = publish(context)
    with pytest.raises(ValueError, match="binding"):
        service.load_candidate_validation(out, artifact, source, rid,
            "The system shall retain logs.", expected_sha256=receipt,
            top_k=3, analyser_factory=factory)


@pytest.mark.parametrize("prediction", [
    {"label": "entailment", "score": float("nan")},
    {"label": "entailment", "score": float("inf")},
    {"label": "contradiction", "score": float("-inf")},
    {"label": "entailment"},
    {"label": "entailment", "score": "0.9"},
])
def test_invalid_actual_nli_output_blocks_candidate_even_with_support(context, prediction):
    context[4].update(pipeline_prediction=prediction, passages=[
        "The system shall retain logs.", "The system must retain logs."])
    record = load(context, publish(context))
    assert record["verdict"] == "ERROR"
    assert record["completion_status"] == "incomplete"
    outcomes = record["grounding"]["diagnostics"][0]["evidence_outcomes"]
    assert {e["outcome"] for e in outcomes} == {"SUPPORTED", "ERROR"}
    assert record["grounding"]["errors"]
    assert all(i.released for i in context[4]["instances"])


def test_valid_actual_nli_output_supports_candidate(context):
    context[4]["pipeline_prediction"] = {"label": "entailment", "score": 0.9}
    assert load(context, publish(context))["verdict"] == "SUPPORTED"


def test_source_mutation_during_validation_prevents_publication(context):
    context[4]["after_analysis"] = lambda: context[1].write_text("changed source", encoding="utf-8")
    with pytest.raises(ValueError, match="SRS hash mismatch"):
        publish(context)
    assert not context[3].exists()
    assert all(i.released for i in context[4]["instances"])


def test_concurrent_sidecar_creation_cannot_overwrite(context, monkeypatch):
    original = service.os.link
    def racing_link(src, dst):
        context[3].write_bytes(b"another writer")
        return original(src, dst)
    monkeypatch.setattr(service.os, "link", racing_link)
    with pytest.raises(FileExistsError):
        publish(context)
    assert context[3].read_bytes() == b"another writer"


def test_incorrect_requirement_binding_rejected(context):
    artifact, source, _, out, _, factory = context
    receipt = publish(context)
    with pytest.raises(ValueError, match="Requirement ID"):
        service.load_candidate_validation(out, artifact, source, "REQ-UNKNOWN",
            "The system shall retain logs.", expected_sha256=receipt, analyser_factory=factory)


def test_parent_snapshot_binding_rejected(context, monkeypatch):
    receipt = publish(context)
    original = service._verify_snapshot
    def changed(*args):
        text, manifest, artifact, state = original(*args)
        state = copy.deepcopy(state)
        state["snapshot_id"] = "SNAPSHOT-OTHER"
        return text, manifest, artifact, state
    monkeypatch.setattr(service, "_verify_snapshot", changed)
    with pytest.raises(ValueError, match="binding"):
        load(context, receipt)


def test_workflow_mutation_during_validation_prevents_publication(context, monkeypatch):
    original = service._verify_snapshot
    changed = []
    context[4]["after_analysis"] = lambda: changed.append(True)
    def current(*args):
        text, manifest, artifact, state = original(*args)
        if changed:
            state = copy.deepcopy(state)
            state["requirements"][context[2]]["clarification_requested"] = True
        return text, manifest, artifact, state
    monkeypatch.setattr(service, "_verify_snapshot", current)
    with pytest.raises(ValueError, match="context changed"):
        publish(context)
    assert not context[3].exists()
    assert all(i.released for i in context[4]["instances"])


@pytest.mark.parametrize("diagnostics", [[None], [{"outcome": "UNKNOWN"}]])
def test_malformed_diagnostics_cannot_publish_support(context, monkeypatch, diagnostics):
    monkeypatch.setattr(context[5], "analyse", lambda *a: {
        "diagnostics": diagnostics, "errors": [], "evidence": []})
    if diagnostics == [None]:
        with pytest.raises(AttributeError):
            publish(context)
        assert not context[3].exists()
    else:
        record = load(context, publish(context))
        assert record["verdict"] == "ERROR" and record["completion_status"] == "incomplete"
    assert all(i.released for i in context[4]["instances"])
