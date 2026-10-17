from __future__ import annotations

import json

from c1_requirement_quality.cli import main


def test_srs_run_clarification_candidate_and_readiness_gate_end_to_end(tmp_path):
    srs = tmp_path / "performance.md"
    original = "The system shall respond within [timeout]."
    candidate = "The system shall respond within 2 seconds."
    srs.write_text(
        "# Performance\n"
        f"1. {original}\n"
        f"{candidate}\n",
        encoding="utf-8",
    )
    run = tmp_path / "initial-run"
    run_id = "RUN-20261011-130000-ab12"

    assert main([
        "run", "--srs", str(srs), "--out", str(run), "--run-id", run_id,
        "--registry", str(tmp_path / "registry.json"),
    ]) == 0
    initial_path = run / "c1" / "validated_requirements.json"
    initial = json.loads(initial_path.read_text(encoding="utf-8"))
    original_requirement = initial["requirements"][0]
    requirement_id = original_requirement["requirement_id"]
    assert original_requirement["original_text"] == original
    assert original_requirement["tier"] == "TIER_2_CLARIFY"
    assert original_requirement["validation"]["checks"]["grounding"] == "pass"
    assert original_requirement["bdd_ready"] is False

    question = "What value or rule should replace [timeout]?"
    actions = tmp_path / "actions.json"
    actions.write_text(json.dumps({"requirements": [{
        "requirement_id": requirement_id,
        "clarification_answers": [{"question": question, "answer": "2 seconds"}],
        "candidate_texts": [candidate],
        "selected_candidate_text": candidate,
        "human_decision": "approved",
    }]}), encoding="utf-8")
    refined_run = tmp_path / "refined-run"

    assert main([
        "refine", "--in", str(initial_path), "--srs", str(srs),
        "--actions", str(actions), "--out", str(refined_run),
    ]) == 0
    refined_path = refined_run / "c1" / "validated_requirements.json"
    refined = json.loads(refined_path.read_text(encoding="utf-8"))
    diagnostics = json.loads(
        (refined_run / "c1" / "refinement_diagnostics.json").read_text(encoding="utf-8")
    )
    final = refined["requirements"][0]

    assert final["requirement_id"] == requirement_id
    assert final["original_text"] == original
    assert final["final_text"] == candidate
    assert final["human_decision"] == "approved"
    assert final["validation"]["checks"]["quality"] == "pass"
    assert final["validation"]["checks"]["grounding"] == "pass"
    assert final["validation"]["checks"]["consistency"] == "skipped"
    assert final["validation"]["checks"]["bdd_readiness"] == "skipped"
    assert final["validation"]["status"] == "needs_review"
    assert final["bdd_ready"] is False
    assert final["tier"] == "TIER_2_CLARIFY"
    assert diagnostics[0]["clarification_answers"] == [
        {"question": question, "answer": "2 seconds"}
    ]
    candidate_readiness = diagnostics[0]["candidates"][0]["bdd_readiness"]
    assert candidate_readiness["check"] == "skipped"
    assert candidate_readiness["bdd_ready"] is False
    assert diagnostics[0]["bdd_readiness"]["check"] == "skipped"
    assert "clarification_answers" not in final
    assert final["grounding"]["evidence"][0]["text"] == candidate
