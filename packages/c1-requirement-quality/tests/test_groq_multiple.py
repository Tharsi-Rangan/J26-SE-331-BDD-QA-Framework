"""Bounded genuine multi-proposal protocol; transport is mocked, never live."""
import copy
import json

import pytest

from test_groq_generator import transport, MODEL, KEY, no_live_network
from c1_requirement_quality.groq_generator import GroqGeneratorBackend, GroqGenerationError


def body(texts):
    return {"model": MODEL, "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
        "candidates": [{"ambiguity": "Review intended wording.", "clarification_question": "What wording is intended?",
            "measurable_rewrite": text} for text in texts]})}}]}


def test_multiple_proposals_are_real_distinct_provider_outputs(transport):
    texts = ["The system shall record audit events.", "The system shall record audit events"]
    transport["body"] = body(texts)
    output = GroqGeneratorBackend(KEY, MODEL).generate_multiple(texts[0], [], [], [])
    assert [c["text"] for c in output] == texts
    assert all(c["source_evidence"]["human_review_required"] for c in output)
    assert len(transport["calls"]) == 1


@pytest.mark.parametrize("texts", [["One"], ["One", "One"], ["One", "Two", "Three", "Four"],
    ["The system shall wait 99 seconds.", "The system shall wait 100 seconds."]])
def test_bad_counts_duplicates_and_fabricated_values_fail(transport, texts):
    transport["body"] = body(texts)
    with pytest.raises(GroqGenerationError):
        GroqGeneratorBackend(KEY, MODEL).generate_multiple("The system shall record events.", [], [], [])
    assert len(transport["calls"]) == 1


def test_explicit_model_abstention_is_not_padded(transport):
    transport["body"] = body([])
    assert GroqGeneratorBackend(KEY, MODEL).generate_multiple("The system shall record events.", [], [], []) == []


@pytest.mark.parametrize("available", [True, False])
def test_model_availability_checks_exact_configured_model(transport, available):
    transport["body"] = {"data": [{"id": MODEL if available else "another-model", "active": True}]}
    backend = GroqGeneratorBackend(KEY, MODEL)
    if available:
        backend.verify_availability()
    else:
        with pytest.raises(GroqGenerationError, match="unavailable"):
            backend.verify_availability()
    request, _ = transport["calls"][0]
    assert request.get_method() == "GET" and request.data is None
    assert request.full_url.endswith("/models") and len(transport["calls"]) == 1
