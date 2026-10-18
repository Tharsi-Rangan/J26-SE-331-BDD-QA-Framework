"""Applicability is an internal audit layer, never a decision-policy override."""
import copy
import json

import pytest

from c1_requirement_quality.consistency_analyser import analyse_consistency, consistency_for_requirement
from c1_requirement_quality.pair_applicability import build_review, load_review, write_review
from c1_requirement_quality.tier_classifier import classify_tier
from c1_requirement_quality.bdd_readiness import evaluate_bdd_readiness


def artifact(conflict=False):
    texts = ["The system shall allow access.",
             "The system shall deny access." if conflict else "The system shall send email."]
    return {"requirements": [{"requirement_id": f"REQ-EX-{i:03}", "original_text": text,
            "final_text": text, "source": {"section": "Security", "line": i}}
            for i, text in enumerate(texts, 1)]}


def decision(state="relevant", **overrides):
    return {"requirement_ids": ["REQ-EX-001", "REQ-EX-002"], "applicability": state,
            "reviewer": "researcher-A", "rationale": "Reviewed distinct obligations in the SRS.", **overrides}


def test_unknown_by_default_and_immutable_exhaustive_outcomes():
    data = artifact()
    original = copy.deepcopy(data)
    review = build_review(data, "DOC")
    expected = analyse_consistency([{"requirement_id": r["requirement_id"], "text": r["original_text"]} for r in data["requirements"]])
    assert [r["original_outcome"] for r in review["pairs"]] == expected["pairs"]
    assert review["pairs"][0]["applicability"] == "unknown"
    assert review["pairs"][0]["review_event"] is None
    assert review["events"] == [] and review["decision_effect"] == "none"
    assert data == original


@pytest.mark.parametrize("state", ["relevant", "not_applicable", "unknown"])
def test_explicit_review_roundtrip_and_prior_snapshot_preserved(tmp_path, state):
    first = build_review(artifact(), "DOC")
    path = tmp_path / "first.json"
    write_review(path, first)
    before = path.read_bytes()
    second = build_review(artifact(), "DOC", previous=load_review(path), decisions=[decision(state)])
    out = tmp_path / "second.json"
    write_review(out, second)
    loaded = load_review(out)
    assert loaded["pairs"][0]["applicability"] == state
    assert loaded["pairs"][0]["original_outcome"] == first["pairs"][0]["original_outcome"]
    assert loaded["events"][0]["reviewer"] == "researcher-A"
    assert loaded["events"][0]["rationale"]
    assert loaded["parent_sha256"] == first["snapshot_sha256"]
    assert path.read_bytes() == before
    with pytest.raises(FileExistsError):
        write_review(path, second)
    continued = build_review(artifact(), "DOC", previous=loaded)
    assert continued["events"] == loaded["events"]
    assert continued["pairs"][0]["applicability"] == state


@pytest.mark.parametrize("overrides", [{"reviewer": ""}, {"rationale": "  "}, {"rationale": None},
                                       {"applicability": "automatic"}])
def test_reviewer_and_rationale_required(overrides):
    with pytest.raises(ValueError):
        build_review(artifact(), "DOC", decisions=[decision(**overrides)])


def test_confirmed_contradiction_cannot_be_excluded():
    data = artifact(True)
    assert build_review(data, "DOC")["pairs"][0]["original_outcome"]["classification"] == "conflict"
    with pytest.raises(ValueError, match="Confirmed contradictions"):
        build_review(data, "DOC", decisions=[decision("not_applicable")])
    assert build_review(data, "DOC", decisions=[decision("relevant")])["pairs"][0]["original_outcome"]["classification"] == "conflict"


@pytest.mark.parametrize("change", ["original_text", "final_text", "section", "hierarchy"])
def test_text_or_context_change_invalidates_but_retains_history(change):
    data = artifact()
    sections = {r["requirement_id"]: ["Requirements", "Security"] for r in data["requirements"]}
    first = build_review(data, "DOC", decisions=[decision("not_applicable")], section_contexts=sections)
    changed = copy.deepcopy(data)
    if change in {"original_text", "final_text"}:
        changed["requirements"][1][change] += " after login."
    elif change == "section":
        changed["requirements"][1]["source"]["section"] = "Authentication"
    else:
        sections["REQ-EX-002"] = ["Different ancestor", "Security"]
    second = build_review(changed, "DOC", previous=first, section_contexts=sections)
    assert second["pairs"][0]["applicability"] == "unknown"
    assert second["pairs"][0]["review_event"] is None
    assert second["pairs"][0]["invalidation"]
    assert second["events"] == first["events"]


def test_document_scope_and_checksum_fail_closed(tmp_path):
    first = build_review(artifact(), "DOC")
    with pytest.raises(ValueError, match="different document"):
        build_review(artifact(), "OTHER", previous=first)
    path = tmp_path / "review.json"
    write_review(path, first)
    value = json.loads(path.read_text())
    value["pairs"][0]["applicability"] = "not_applicable"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="checksum"):
        load_review(path)


def test_applicability_has_no_tier_or_bdd_effect():
    data = artifact()
    analysis = analyse_consistency([{"requirement_id": r["requirement_id"], "text": r["original_text"]} for r in data["requirements"]])
    before = copy.deepcopy(analysis)
    grounding = {"status": "supported", "evidence": [{"chunk_id": "SRS-1", "text": "Evidence"}]}
    consistency = consistency_for_requirement("REQ-EX-001", analysis)
    tier = classify_tier([], grounding, consistency)
    build_review(data, "DOC", decisions=[decision("not_applicable")])
    assert analysis == before
    assert classify_tier([], grounding, consistency) == tier
    assert tier["tier"] == "TIER_2_CLARIFY"


def test_cli_integrity_contract_and_gate_outputs_unchanged(tmp_path):
    from c1_requirement_quality import cli
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall allow access.\n2. The system shall send email.\n", encoding="utf-8")
    out = tmp_path / "run"
    cli.run(source, out, "RUN-20261015-210000-pair", registry_path=tmp_path / "registry.json")
    artifact_path = out / "c1/validated_requirements.json"
    before = {p: p.read_bytes() for p in (out / "c1").rglob("*") if p.is_file()}
    listing = tmp_path / "pairs.json"
    args = ["--in", str(artifact_path), "--srs", str(source)]
    assert cli.main(["list-pairs", *args, "--out", str(listing)]) == 0
    actions = tmp_path / "actions.json"
    value = json.loads(artifact_path.read_text())
    ids = [r["requirement_id"] for r in value["requirements"]]
    actions.write_text(json.dumps({"decisions": [decision("not_applicable", requirement_ids=ids)]}))
    reviewed = tmp_path / "reviewed.json"
    assert cli.main(["review-pairs", *args, "--out", str(reviewed), "--previous", str(listing), "--actions", str(actions)]) == 0
    assert load_review(reviewed)["pairs"][0]["applicability"] == "not_applicable"
    assert all(p.read_bytes() == content for p, content in before.items())
    cli._validate_contract_artifact(json.loads(artifact_path.read_text()))
    assert all(r["tier"] == "TIER_2_CLARIFY" and r["bdd_ready"] is False for r in value["requirements"])
    assert cli.main(["list-pairs", *args, "--out", str(listing)]) == 1


@pytest.mark.parametrize("scenario", ["consistent", "unknown", "conflict"])
def test_all_tier_and_bdd_results_unchanged_by_review(scenario):
    data = artifact(scenario == "conflict")
    if scenario == "consistent":
        data["requirements"][1]["original_text"] = data["requirements"][0]["original_text"]
        data["requirements"][1]["final_text"] = data["requirements"][0]["original_text"]
    def assess():
        analysis = analyse_consistency([{"requirement_id": r["requirement_id"], "text": r["original_text"]} for r in data["requirements"]])
        consistency = consistency_for_requirement("REQ-EX-001", analysis)
        tier = classify_tier([], {"status": "supported", "evidence": [{"text": "Evidence", "chunk_id": "SRS-1"}]}, consistency)
        bdd = evaluate_bdd_readiness(data["requirements"][0]["original_text"], quality_check="pass",
            grounding_check="pass", consistency_check=consistency["check"], consistency_result=consistency, tier=tier["tier"])
        return tier, bdd
    before = assess()
    review = build_review(data, "DOC", decisions=[decision("relevant" if scenario == "conflict" else "not_applicable")])
    assert review["decision_effect"] == "none"
    assert assess() == before
    expected = {"consistent": "TIER_1_AUTO_REFINE", "unknown": "TIER_2_CLARIFY", "conflict": "TIER_3_ESCALATE"}
    assert before[0]["tier"] == expected[scenario]
