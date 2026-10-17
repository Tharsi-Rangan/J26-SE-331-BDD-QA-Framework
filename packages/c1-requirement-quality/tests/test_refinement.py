from __future__ import annotations

import json
import copy

import pytest

from c1_requirement_quality.cli import main
from c1_requirement_quality.refinement import (
    can_mark_bdd_ready,
    clarification_questions_for,
    process_refinement_actions,
    stable_candidate_id,
)
from c1_requirement_quality.source_integrity import seal_source, snapshot_source

REQ_ID = "REQ-EX-201"
ORIGINAL = "The system shall respond quickly."
SRS_TEXT = (
    "The system shall respond quickly.\n"
    "The system shall respond within 2 seconds.\n"
)
CANDIDATE = "The system shall respond within 2 seconds."


def _artifact(original_text: str = ORIGINAL) -> dict:
    return {
        "contract": "c1.validated-requirements",
        "schema_version": "1.0.0",
        "producer": {"component": "C1", "tool_version": "0.1.0"},
        "run_id": "RUN-20261011-101010-ab12",
        "generated_at": "2026-10-11T10:10:10+00:00",
        "source_document": {
            "name": "sample.md",
            "project_code": "EX",
            "path": "sample.md",
            "redaction_applied": False,
        },
        "requirements": [{
            "requirement_id": REQ_ID,
            "source": {"section": "Performance", "line": 1},
            "original_text": original_text,
            "defects": [],
            "tier": "TIER_3_ESCALATE",
            "grounding": {"status": "supported", "evidence": []},
            "consistency": {
                "status": "potential_conflict",
                "related_requirement_ids": [],
                "conflicts": [],
            },
            "validation": {
                "status": "needs_review",
                "checks": {
                    "quality": "pass",
                    "grounding": "pass",
                    "consistency": "skipped",
                    "bdd_readiness": "skipped",
                },
            },
            "human_decision": "pending",
            "final_text": original_text,
            "bdd_ready": False,
        }],
    }


def _requirement(output: dict) -> dict:
    return output["requirements"][0]


def test_candidate_ids_are_stable_and_scoped_to_requirement_and_text():
    candidate_id = stable_candidate_id(REQ_ID, CANDIDATE)

    assert candidate_id == stable_candidate_id(REQ_ID, CANDIDATE)
    assert candidate_id != stable_candidate_id("REQ-EX-202", CANDIDATE)
    assert candidate_id != stable_candidate_id(REQ_ID, CANDIDATE + " ")


def test_explicit_placeholders_create_questions_but_never_answers():
    assert clarification_questions_for("Use [timeout] after TBC.") == [
        "What value or rule should replace [timeout]?",
        "What information should replace TBC?",
    ]
    assert clarification_questions_for("The system shall use a suitable timeout.") == []


def test_pending_candidate_preserves_original_and_keeps_answers_out_of_contract():
    question = "What duration should replace [timeout]?"
    artifact = _artifact("The system shall wait for [timeout].")
    output, diagnostics = process_refinement_actions(
        artifact,
        {
            "requirements": [{
                "requirement_id": REQ_ID,
            "clarification_questions": [question],
                "clarification_answers": [{"question": question, "answer": "2 seconds"}],
                "candidate_texts": ["The system shall wait for 2 seconds."],
                "human_decision": "pending",
            }]
        },
        "The system shall wait for [timeout].\n",
    )

    requirement = _requirement(output)
    assert requirement["original_text"] == artifact["requirements"][0]["original_text"]
    assert requirement["final_text"] == requirement["original_text"]
    assert requirement["human_decision"] == "pending"
    assert len(requirement["candidates"]) == 1
    assert requirement["clarification_questions"] == [
        "What value or rule should replace [timeout]?", question,
    ]
    assert "clarification_answers" not in requirement
    assert diagnostics[0]["clarification_answers"][0]["answer"] == "2 seconds"
    assert requirement["bdd_ready"] is False


def test_missing_clarification_answer_remains_an_open_question():
    output, diagnostics = process_refinement_actions(
        _artifact("The system shall wait for [timeout]."),
        {"requirements": [{"requirement_id": REQ_ID}]},
        "The system shall wait for [timeout].\n",
    )

    requirement = _requirement(output)
    assert requirement["clarification_questions"] == [
        "What value or rule should replace [timeout]?"
    ]
    assert diagnostics[0]["clarification_answers"] == []
    assert requirement["final_text"] == "The system shall wait for [timeout]."


def test_candidate_selection_without_decision_does_not_approve_it():
    output, _ = process_refinement_actions(
        _artifact(),
        {"requirements": [{
            "requirement_id": REQ_ID,
            "selected_candidate_text": CANDIDATE,
        }]},
        SRS_TEXT,
    )

    requirement = _requirement(output)
    assert requirement["human_decision"] == "pending"
    assert requirement["final_text"] == ORIGINAL
    assert requirement["bdd_ready"] is False


def test_new_selection_does_not_inherit_approval_of_another_candidate():
    artifact = _artifact()
    old_text = "The system shall respond within 3 seconds."
    old_id = stable_candidate_id(REQ_ID, old_text)
    requirement = artifact["requirements"][0]
    requirement["candidates"] = [{"candidate_id": old_id, "text": old_text}]
    requirement["selected_candidate_id"] = old_id
    requirement["human_decision"] = "approved"
    requirement["final_text"] = old_text

    output, _ = process_refinement_actions(
        artifact,
        {"requirements": [{
            "requirement_id": REQ_ID,
            "selected_candidate_text": CANDIDATE,
        }]},
        SRS_TEXT,
    )

    updated = _requirement(output)
    assert updated["selected_candidate_id"] != old_id
    assert updated["human_decision"] == "pending"
    assert updated["final_text"] == ORIGINAL
    assert updated["bdd_ready"] is False


@pytest.mark.parametrize("decision", ["pending", "rejected"])
def test_pending_or_rejected_candidate_retains_original_text(decision):
    output, _ = process_refinement_actions(
        _artifact(),
        {"requirements": [{
            "requirement_id": REQ_ID,
            "candidate_texts": [CANDIDATE],
            "selected_candidate_text": CANDIDATE,
            "human_decision": decision,
        }]},
        SRS_TEXT,
    )

    requirement = _requirement(output)
    assert requirement["selected_candidate_id"].startswith("CAND-")
    assert requirement["final_text"] == ORIGINAL
    assert requirement["human_decision"] == decision
    assert requirement["bdd_ready"] is False


def test_approved_supported_candidate_is_selected_but_consistency_blocks_readiness():
    output, diagnostics = process_refinement_actions(
        _artifact(),
        {"requirements": [{
            "requirement_id": REQ_ID,
            "candidate_texts": [CANDIDATE],
            "selected_candidate_text": CANDIDATE,
            "human_decision": "approved",
        }]},
        SRS_TEXT,
    )

    requirement = _requirement(output)
    assert requirement["original_text"] == ORIGINAL
    assert requirement["final_text"] == CANDIDATE
    assert requirement["human_decision"] == "approved"
    assert requirement["validation"]["checks"] == {
        "quality": "pass",
        "grounding": "pass",
        "consistency": "skipped",
        "bdd_readiness": "skipped",
    }
    assert requirement["validation"]["status"] == "needs_review"
    assert requirement["bdd_ready"] is False
    assert requirement["grounding"]["evidence"][0]["text"] == CANDIDATE
    assert diagnostics[0]["readiness_blockers"] == ["consistency", "bdd_readiness"]


def test_refinement_detects_conflict_with_another_requirement_and_keeps_readiness_closed():
    artifact = _artifact("The system shall allow account deletion.")
    other = copy.deepcopy(artifact["requirements"][0])
    other["requirement_id"] = "REQ-EX-202"
    other["original_text"] = "The system shall allow account deletion."
    other["final_text"] = other["original_text"]
    artifact["requirements"].append(other)
    candidate = "The system shall not allow account deletion."

    baseline, _ = process_refinement_actions(
        artifact, {"requirements": []}, "The system shall allow account deletion.\n"
    )
    assert all(item["tier"] == "TIER_1_AUTO_REFINE" for item in baseline["requirements"])

    output, diagnostics = process_refinement_actions(
        artifact,
        {"requirements": [{
            "requirement_id": REQ_ID,
            "selected_candidate_text": candidate,
            "human_decision": "approved",
        }]},
        "The system shall allow account deletion.\n",
    )

    first, second = output["requirements"]
    assert first["human_decision"] == "approved"
    assert first["tier"] == second["tier"] == "TIER_3_ESCALATE"
    assert first["consistency"]["status"] == second["consistency"]["status"] == "conflict"
    assert first["validation"]["checks"]["consistency"] == "fail"
    assert first["validation"]["status"] == "failed"
    assert first["bdd_ready"] is second["bdd_ready"] is False
    assert diagnostics[0]["consistency"]["pairs"][0]["classification"] == "conflict"
    candidate_diagnostic = diagnostics[0]["candidates"][0]
    assert candidate_diagnostic["consistency"]["check"] == "fail"
    assert candidate_diagnostic["tier"]["tier"] == "TIER_3_ESCALATE"


def test_refinement_tier_one_candidate_allows_only_whitespace_normalization():
    original = "The system shall allow users to register."
    artifact = _artifact(original)
    candidate = "The system  shall allow users to register."
    output, diagnostics = process_refinement_actions(
        artifact,
        {"requirements": [{
            "requirement_id": REQ_ID,
            "selected_candidate_text": candidate,
            "human_decision": "approved",
        }]},
        original + "\n",
    )
    requirement = _requirement(output)
    assert requirement["original_text"] == original
    assert requirement["final_text"] == candidate
    assert requirement["tier"] == "TIER_1_AUTO_REFINE"
    assert diagnostics[0]["tier"]["tier"] == "TIER_1_AUTO_REFINE"
    assert requirement["bdd_ready"] is False


def test_unsupported_candidate_is_reported_and_cannot_become_bdd_ready():
    unsupported = "The system shall permit transfers up to 100000 dollars."
    output, diagnostics = process_refinement_actions(
        _artifact("The system shall permit transfers."),
        {"requirements": [{
            "requirement_id": REQ_ID,
            "selected_candidate_text": unsupported,
            "human_decision": "approved",
        }]},
        "The system shall permit transfers.\n",
    )

    requirement = _requirement(output)
    assert requirement["final_text"] == unsupported
    assert requirement["grounding"]["status"] == "unsupported"
    assert requirement["validation"]["checks"]["grounding"] == "fail"
    assert requirement["validation"]["status"] == "failed"
    assert requirement["bdd_ready"] is False
    candidate = diagnostics[0]["candidates"][0]
    assert candidate["grounding"]["unsupported_claims"] == [unsupported]


def test_edited_decision_creates_a_candidate_and_records_edited_text():
    output, _ = process_refinement_actions(
        _artifact(),
        {"requirements": [{
            "requirement_id": REQ_ID,
            "human_decision": "edited",
            "edited_text": CANDIDATE,
        }]},
        SRS_TEXT,
    )

    requirement = _requirement(output)
    assert requirement["human_decision"] == "edited"
    assert requirement["selected_candidate_id"] == stable_candidate_id(REQ_ID, CANDIDATE)
    assert requirement["candidates"] == [{
        "candidate_id": stable_candidate_id(REQ_ID, CANDIDATE),
        "text": CANDIDATE,
    }]
    assert requirement["final_text"] == CANDIDATE


def test_readiness_requires_approved_decision_and_every_gate_to_pass():
    all_pass = {
        "quality": "pass",
        "grounding": "pass",
        "consistency": "pass",
        "bdd_readiness": "pass",
    }
    assert can_mark_bdd_ready("passed", all_pass, "approved")
    assert can_mark_bdd_ready("passed", all_pass, "edited")
    assert not can_mark_bdd_ready("passed", all_pass, "pending")
    assert not can_mark_bdd_ready("needs_review", all_pass, "approved")
    assert not can_mark_bdd_ready("passed", {**all_pass, "consistency": "skipped"}, "approved")


@pytest.mark.parametrize(
    "actions, message",
    [
        ({"requirements": [{"requirement_id": REQ_ID, "candidate_texts": [""]}]}, "must not be empty"),
        ({"requirements": [{"requirement_id": REQ_ID, "human_decision": "auto"}]}, "invalid human_decision"),
        ({"requirements": [{"requirement_id": REQ_ID, "selected_candidate_id": "missing"}]}, "does not exist"),
        ({"requirements": [{"requirement_id": REQ_ID, "human_decision": "approved"}]}, "requires a selected candidate"),
        ({"requirements": [{"requirement_id": REQ_ID, "human_decision": "edited"}]}, "requires non-empty edited_text"),
        ({"requirements": [{"requirement_id": REQ_ID, "typo_decision": "approved"}]}, "unsupported refinement action fields"),
    ],
)
def test_invalid_actions_fail_clearly(actions, message):
    with pytest.raises(ValueError, match=message):
        process_refinement_actions(_artifact(), actions, SRS_TEXT)


def test_duplicate_actions_and_unknown_requirement_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate action"):
        process_refinement_actions(
            _artifact(),
            {"requirements": [
                {"requirement_id": REQ_ID},
                {"requirement_id": REQ_ID},
            ]},
            SRS_TEXT,
        )
    with pytest.raises(ValueError, match="unknown requirement_id"):
        process_refinement_actions(
            _artifact(), {"requirements": [{"requirement_id": "REQ-EX-999"}]}, SRS_TEXT
        )


def test_not_required_is_accepted_only_as_an_explicit_decision():
    output, _ = process_refinement_actions(
        _artifact(),
        {"requirements": [{"requirement_id": REQ_ID, "human_decision": "not_required"}]},
        SRS_TEXT,
    )

    requirement = _requirement(output)
    assert requirement["human_decision"] == "not_required"
    assert requirement["final_text"] == ORIGINAL
    assert requirement["bdd_ready"] is False


def test_cli_refine_validates_schema_writes_sidecar_and_never_overwrites(tmp_path):
    input_path = tmp_path / "input" / "c1" / "validated_requirements.json"
    input_path.parent.mkdir(parents=True)
    input_path.write_text(json.dumps(_artifact()), encoding="utf-8")
    srs = tmp_path / "sample.md"
    srs.write_text(SRS_TEXT, encoding="utf-8")
    _, manifest = snapshot_source(input_path.parent, srs, "DOC-EXAMPLE")
    seal_source(input_path.parent, manifest)
    actions = tmp_path / "actions.json"
    actions.write_text(json.dumps({"requirements": [{
        "requirement_id": REQ_ID,
        "selected_candidate_text": CANDIDATE,
        "human_decision": "approved",
    }]}), encoding="utf-8")
    out = tmp_path / "refined-run"

    assert main([
        "refine", "--in", str(input_path), "--srs", str(srs),
        "--actions", str(actions), "--out", str(out),
    ]) == 0
    c1_dir = out / "c1"
    refined_path = c1_dir / "validated_requirements.json"
    diagnostic_path = c1_dir / "refinement_diagnostics.json"
    refined = json.loads(refined_path.read_text(encoding="utf-8"))
    diagnostics = json.loads(diagnostic_path.read_text(encoding="utf-8"))

    assert refined["schema_version"] == "1.0.0"
    assert _requirement(refined)["final_text"] == CANDIDATE
    assert _requirement(refined)["bdd_ready"] is False
    assert _requirement(refined)["tier"] == "TIER_2_CLARIFY"
    assert diagnostics[0]["requirement_id"] == REQ_ID
    assert diagnostics[0]["tier"]["tier"] == "TIER_2_CLARIFY"
    assert diagnostics[0]["candidates"][0]["tier"]["tier"] == "TIER_2_CLARIFY"
    candidate_readiness = diagnostics[0]["candidates"][0]["bdd_readiness"]
    assert candidate_readiness["check"] == "skipped"
    assert candidate_readiness["bdd_ready"] is False
    assert "criteria are defined" in candidate_readiness["explanation"]
    assert diagnostics[0]["final_text_severity_priority"]["severity"] == "unknown"
    assert diagnostics[0]["final_text_severity_priority"]["priority"] == "needs_review"
    assert diagnostics[0]["candidates"][0]["severity_priority"]["severity"] == "unknown"
    assert "clarification_answers" not in _requirement(refined)
    assert main([
        "refine", "--in", str(input_path), "--srs", str(srs),
        "--actions", str(actions), "--out", str(out),
    ]) == 1


def test_cli_refine_rejects_srs_with_different_source_filename(tmp_path):
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(_artifact()), encoding="utf-8")
    srs = tmp_path / "different.md"
    srs.write_text(SRS_TEXT, encoding="utf-8")
    actions = tmp_path / "actions.json"
    actions.write_text(json.dumps({"requirements": []}), encoding="utf-8")

    assert main([
        "refine", "--in", str(input_path), "--srs", str(srs),
        "--actions", str(actions), "--out", str(tmp_path / "out"),
    ]) == 1
    assert not (tmp_path / "out").exists()
