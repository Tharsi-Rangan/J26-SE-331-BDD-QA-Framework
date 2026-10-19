"""Groq integration tests with mocked transport only; no live quota usage."""
import copy
import io
import json
import socket
import urllib.error
from types import SimpleNamespace

import pytest

from c1_requirement_quality.groq_generator import GroqGeneratorBackend, GroqGenerationError
from c1_requirement_quality.rewrite_generator import GeneratorBackend, generate_candidate_suggestions, generate_candidates_run
from c1_requirement_quality.cli import build_parser, main
from test_rewrite_generator import _minimal_artifact, _req

MODEL = "qwen/qwen3.8-27b"
KEY = "unit-test-secret"


def envelope(**updates):
    proposal = {"ambiguity": "Quickly is unmeasured.", "clarification_question": "What response time is required?",
                "measurable_rewrite": "The system shall respond within [RESPONSE_TIME]."}
    proposal.update(updates)
    return {"model": MODEL, "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal)}}]}


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Live network forbidden in automated tests")
    monkeypatch.setattr(socket.socket, "connect", deny)


@pytest.fixture
def transport(monkeypatch):
    state = {"calls": [], "body": envelope(), "error": None}
    class Response(io.BytesIO):
        status = 200
    def open_request(request, timeout):
        state["calls"].append((request, timeout))
        if state["error"]:
            raise state["error"]
        raw = state["body"]
        return Response(raw if isinstance(raw, bytes) else json.dumps(raw).encode())
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: SimpleNamespace(open=open_request))
    return state


def test_backend_protocol_and_structured_proposal(transport):
    backend: GeneratorBackend = GroqGeneratorBackend(KEY, MODEL)
    proposals = backend.generate("The system should respond quickly.", [], [], [])
    assert len(proposals) == 1 and "[RESPONSE_TIME]" in proposals[0]["text"]
    assert proposals[0]["source_evidence"]["human_review_required"] is True
    assert proposals[0]["source_evidence"]["source"] == "groq"
    request, timeout = transport["calls"][0]
    assert request.full_url == "https://api.groq.com/openai/v1/chat/completions"
    assert json.loads(request.data)["model"] == MODEL
    assert timeout == 30 and len(transport["calls"]) == 1


@pytest.mark.parametrize("status", [403, 429, 500, 502, 503])
def test_http_errors_sanitized_without_retry(transport, status):
    transport["error"] = urllib.error.HTTPError("https://api.groq.com", status, KEY, {}, io.BytesIO(KEY.encode()))
    with pytest.raises(GroqGenerationError) as error:
        GroqGeneratorBackend(KEY, MODEL).generate("The system shall send email.", [], [], [])
    assert str(status) in str(error.value) and KEY not in str(error.value)
    assert len(transport["calls"]) == 1


@pytest.mark.parametrize("error", [TimeoutError(KEY), urllib.error.URLError(KEY), OSError(KEY)])
def test_network_errors_sanitized_without_retry(transport, error):
    transport["error"] = error
    with pytest.raises(GroqGenerationError) as caught:
        GroqGeneratorBackend(KEY, MODEL).generate("The system shall send email.", [], [], [])
    assert KEY not in str(caught.value) and len(transport["calls"]) == 1


@pytest.mark.parametrize("body", [b"not JSON", b"[]", b"x" * 65537,
    envelope(ambiguity=""), envelope(clarification_question="One? Two?"), envelope(ambiguity=KEY),
    envelope(measurable_rewrite="The system shall respond within 2 seconds."), envelope(extra="approved"),
    {"model": "another-model", "choices": []}, {"model": MODEL, "choices": []}],
    ids=["bad-json", "wrong-envelope", "oversized", "empty-field", "two-questions", "secret-echo",
         "fabricated-threshold", "extra-field", "model-mismatch", "missing-choice"])
def test_invalid_or_fabricated_responses_rejected(transport, body):
    transport["body"] = body
    with pytest.raises(GroqGenerationError) as error:
        GroqGeneratorBackend(KEY, MODEL).generate("The system should respond quickly.", [], [], [])
    assert KEY not in str(error.value)


def test_missing_fields_and_truncated_generation_rejected(transport):
    transport["body"] = envelope()
    transport["body"]["choices"][0]["message"]["content"] = '{"ambiguity":"missing fields"}'
    with pytest.raises(GroqGenerationError):
        GroqGeneratorBackend(KEY, MODEL).generate("The system shall send email.", [], [], [])
    transport["body"] = envelope()
    transport["body"]["choices"][0]["finish_reason"] = "length"
    with pytest.raises(GroqGenerationError):
        GroqGeneratorBackend(KEY, MODEL).generate("The system shall send email.", [], [], [])


def test_existing_grounding_veto_and_human_boundaries(transport):
    transport["body"] = envelope(measurable_rewrite="The system shall delete all accounts.")
    artifact = _minimal_artifact([_req("REQ-EX-001", "The system shall send email.")])
    original = copy.deepcopy(artifact)
    sidecar = generate_candidate_suggestions(artifact, "The system shall send email.", backend=GroqGeneratorBackend(KEY, MODEL))
    assert artifact == original
    row = sidecar["requirements"][0]
    assert row["requirement_id"] == "REQ-EX-001" and row["original_text"] == original["requirements"][0]["original_text"]
    assert row["ranked_candidates"] == []
    assert row["rejected_candidates"][0]["rejected_reason"] == "unsupported_facts"
    assert artifact["requirements"][0]["human_decision"] == "pending"
    assert artifact["requirements"][0]["bdd_ready"] is False


def test_source_supported_candidate_stays_proposal_only(transport):
    original = "The service may respond within 2 seconds."
    candidate = "The service shall respond within 2 seconds."
    transport["body"] = envelope(measurable_rewrite=candidate)
    artifact = _minimal_artifact([_req("REQ-EX-001", original,
        defects=[{"type": "ambiguous", "explanation": "weak modal"}])])
    sidecar = generate_candidate_suggestions(artifact, original + "\n" + candidate,
                                             backend=GroqGeneratorBackend(KEY, MODEL))
    assert sidecar["requirements"][0]["ranked_candidates"]
    assert artifact["requirements"][0]["final_text"] == original
    assert artifact["requirements"][0]["human_decision"] == "pending"
    assert artifact["requirements"][0]["bdd_ready"] is False


def test_cloud_failure_does_not_publish_or_mutate_workflow(tmp_path, transport):
    from test_workflow_persistence import initial
    path, source, _ = initial(tmp_path, "The system shall send email.")
    before = {p: p.read_bytes() for p in path.parent.rglob('*') if p.is_file()}
    transport["error"] = urllib.error.URLError(KEY)
    output = tmp_path / "suggestions.json"
    with pytest.raises(GroqGenerationError):
        generate_candidates_run(path, source, output, backend=GroqGeneratorBackend(KEY, MODEL))
    assert not output.exists()
    assert all(p.read_bytes() == content for p, content in before.items())


def test_configuration_does_not_mutate_environment(tmp_path, monkeypatch):
    import os
    path = tmp_path / '.env'
    path.write_text(f"GROQ_API_KEY={KEY}\nGROQ_MODEL={MODEL}\n")
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    monkeypatch.delenv('GROQ_MODEL', raising=False)
    backend = GroqGeneratorBackend.from_environment(path)
    assert backend.model == MODEL and 'GROQ_API_KEY' not in os.environ
    assert KEY not in repr(backend)
    monkeypatch.setenv('GROQ_MODEL', 'qwen/explicit-override')
    assert GroqGeneratorBackend.from_environment(path).model == 'qwen/explicit-override'


def test_cli_opt_in_and_error_sanitization(tmp_path, monkeypatch, capsys):
    args = ['generate-candidates', '--in', 'input.json', '--srs', 'source.md', '--out', str(tmp_path / 'out.json')]
    assert build_parser().parse_args(args).backend == 'deterministic'
    assert build_parser().parse_args(args + ['--backend', 'groq']).backend == 'groq'
    monkeypatch.setattr(GroqGeneratorBackend, 'from_environment', classmethod(lambda cls: (_ for _ in ()).throw(GroqGenerationError('Groq HTTP 403'))))
    assert main(args + ['--backend', 'groq']) == 1
    assert '403' in capsys.readouterr().err
    assert not (tmp_path / 'out.json').exists()


def test_mocked_live_cli_path_publishes_only_sidecar(tmp_path, transport, monkeypatch):
    from test_workflow_persistence import initial
    path, source, rid = initial(tmp_path, "The system shall send email.")
    before = {p: p.read_bytes() for p in path.parent.rglob('*') if p.is_file()}
    backend = GroqGeneratorBackend(KEY, MODEL)
    monkeypatch.setattr(GroqGeneratorBackend, 'from_environment', classmethod(lambda cls: backend))
    output = tmp_path / 'cloud-suggestions.json'
    assert main(['generate-candidates', '--in', str(path), '--srs', str(source),
                 '--out', str(output), '--backend', 'groq']) == 0
    report = json.loads(output.read_text())
    row = report['requirements'][0]
    assert row['requirement_id'] == rid and row['original_text'] == 'The system shall send email.'
    assert row['ranked_candidates'] == []
    assert row['rejected_candidates'][0]['source_evidence']['human_review_required'] is True
    assert all(p.read_bytes() == content for p, content in before.items())
    assert len(transport['calls']) == 1


def test_existing_output_prevents_cloud_request(tmp_path, transport):
    output = tmp_path / 'existing.json'
    output.write_text('preserve me')
    with pytest.raises(FileExistsError):
        generate_candidates_run(tmp_path / 'input.json', tmp_path / 'source.md', output,
                                backend=GroqGeneratorBackend(KEY, MODEL))
    assert output.read_text() == 'preserve me' and not transport['calls']


@pytest.mark.parametrize('content', ['{"ambiguity":"a","ambiguity":"b"}', 'NaN', '```json\n{}\n```'])
def test_strict_proposal_json(transport, content):
    transport['body'] = envelope()
    transport['body']['choices'][0]['message']['content'] = content
    with pytest.raises(GroqGenerationError):
        GroqGeneratorBackend(KEY, MODEL).generate('The system shall send email.', [], [], [])


@pytest.mark.parametrize('key,model,timeout', [('', MODEL, 30), (KEY, '', 30),
    (KEY, 'other/model', 30), (KEY, MODEL, 0), (KEY, MODEL, float('inf'))])
def test_invalid_configuration_fails_before_request(key, model, timeout):
    with pytest.raises(GroqGenerationError):
        GroqGeneratorBackend(key, model, timeout=timeout)


@pytest.mark.parametrize("limit", [True, 0, 128.5, 2049])
def test_invalid_output_token_limits(limit):
    with pytest.raises(GroqGenerationError):
        GroqGeneratorBackend(KEY, MODEL, max_output_tokens=limit)


def test_optional_environment_limits_preserve_explicit_model(tmp_path, monkeypatch):
    for name in ["GROQ_API_KEY", "GROQ_MODEL", "GROQ_TIMEOUT_SECONDS", "GROQ_MAX_OUTPUT_TOKENS"]:
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "mock-settings.env"
    path.write_text(f"GROQ_API_KEY={KEY}\nGROQ_MODEL={MODEL}\nGROQ_TIMEOUT_SECONDS=45\nGROQ_MAX_OUTPUT_TOKENS=1024\n")
    backend = GroqGeneratorBackend.from_environment(path)
    assert backend.model == MODEL and backend.timeout == 45 and backend.max_output_tokens == 1024
