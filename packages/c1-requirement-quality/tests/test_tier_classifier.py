from c1_requirement_quality.tier_classifier import (
    TIER_1,
    TIER_2,
    TIER_3,
    classify_tier,
)


def _grounding(status="supported", evidence=True, **extra):
    return {
        "status": status,
        "evidence": (
            evidence if isinstance(evidence, list)
            else ([{"chunk_id": "SRS-L0001-L0001", "text": "Source evidence."}] if evidence else [])
        ),
        **extra,
    }


def _consistency(status="consistent", pairs=None, check="pass"):
    pair_rows = pairs if pairs is not None else [{
        "requirement_ids": ["REQ-EX-001", "REQ-EX-002"],
        "classification": status,
        "analysis_state": "analyzed",
        "explanation": "Pair result.",
        "evidence": [],
    }]
    return {
        "status": status,
        "check": check,
        "requirements_analyzed": 1 if not pair_rows else 2,
        "pairs_unassessed": sum(row.get("analysis_state") == "unassessed" for row in pair_rows),
        "pairs": pair_rows,
    }


def test_tier_one_requires_supported_evidence_no_quality_findings_and_no_conflict():
    result = classify_tier([], _grounding(), _consistency())

    assert result["tier"] == TIER_1
    assert result["analysis_status"] == "assessed"
    assert "meaning-preserving" in result["explanation"]
    assert result["reasons"][0]["grounding_evidence"]


def test_single_requirement_can_be_tier_one_when_there_is_no_peer_pair():
    result = classify_tier(
        [], _grounding(), _consistency("potential_conflict", pairs=[], check="skipped")
    )
    assert result["tier"] == TIER_1


def test_tier_one_candidate_must_preserve_exact_content_except_whitespace():
    grounding = _grounding()
    consistency = _consistency("potential_conflict", pairs=[], check="skipped")
    structural = classify_tier(
        [], grounding, consistency,
        original_text="The system shall allow users to register.",
        candidate_text="The system  shall allow users to register.",
    )
    content_change = classify_tier(
        [], grounding, consistency,
        original_text="The system shall allow users to register.",
        candidate_text="The system shall allow users to register within 2 seconds.",
    )
    assert structural["tier"] == TIER_1
    assert content_change["tier"] == TIER_2
    assert content_change["reasons"][0]["kind"] == "candidate_changes_requirement_content"


def test_quality_defect_needing_clarification_is_tier_two_not_severity_driven():
    result = classify_tier(
        [{"type": "ambiguous", "explanation": "Could has open interpretation.", "evidence_span": "could"}],
        _grounding(), _consistency(),
    )
    assert result["tier"] == TIER_2
    assert result["reasons"][0]["kind"] == "quality_defect"


def test_unsupported_facts_and_missing_grounding_are_tier_two():
    result = classify_tier(
        [], _grounding("unsupported", evidence=False, unsupported_claims=["Use a 2 second timeout."]),
        _consistency(),
    )
    assert result["tier"] == TIER_2
    assert any(reason["kind"] == "grounding_insufficient" for reason in result["reasons"])


def test_potential_or_unassessed_peer_relationship_requires_tier_two_review():
    pair = {
        "requirement_ids": ["REQ-EX-001", "REQ-EX-002"],
        "classification": "unassessed",
        "analysis_state": "unassessed",
        "explanation": "Different conditions.",
        "evidence": [],
    }
    result = classify_tier([], _grounding(), _consistency("potential_conflict", [pair], "skipped"))
    assert result["tier"] == TIER_2
    assert any(reason["kind"] == "consistency_unresolved" for reason in result["reasons"])


def test_confirmed_requirement_conflict_is_tier_three_with_both_ids_and_evidence():
    pair = {
        "requirement_ids": ["REQ-EX-001", "REQ-EX-002"],
        "classification": "conflict",
        "analysis_state": "analyzed",
        "explanation": "Opposing obligations.",
        "evidence": [
            {"requirement_id": "REQ-EX-001", "start_offset": 0, "end_offset": 12, "text": "shall allow"},
            {"requirement_id": "REQ-EX-002", "start_offset": 0, "end_offset": 16, "text": "shall not allow"},
        ],
    }
    result = classify_tier([], _grounding(), _consistency("conflict", [pair], "fail"))
    assert result["tier"] == TIER_3
    assert result["reasons"][0]["requirement_ids"] == ["REQ-EX-001", "REQ-EX-002"]
    assert len(result["reasons"][0]["evidence"]) == 2


def test_explicit_grounding_contradiction_escalates_but_partial_support_alone_does_not():
    contradiction = classify_tier(
        [], _grounding("partially_supported", conflicts=[{
            "claim": "The system shall not allow exports.",
            "evidence_chunk_ids": ["SRS-L0004-L0004"],
        }], evidence=[{
            "chunk_id": "SRS-L0004-L0004",
            "text": "The system shall allow exports.",
        }]), _consistency(),
    )
    partial = classify_tier([], _grounding("partially_supported"), _consistency())
    assert contradiction["tier"] == TIER_3
    assert partial["tier"] == TIER_2


def test_grounding_numeric_difference_alone_does_not_escalate_tier_three():
    result = classify_tier(
        [], _grounding("partially_supported", conflicts=[{
            "claim": "The password must be at least 8 characters.",
            "evidence_chunk_ids": ["SRS-L0004-L0004"],
        }], evidence=[{
            "chunk_id": "SRS-L0004-L0004",
            "text": "The password must be at least 12 characters.",
        }]), _consistency(),
    )
    assert result["tier"] == TIER_2


def test_supported_status_without_traceable_evidence_requires_review():
    result = classify_tier([], _grounding(evidence=False), _consistency())
    assert result["tier"] == TIER_2
    assert result["analysis_status"] == "needs_review"


def test_semantic_rewrite_requires_explicit_human_review():
    options = {
        "original_text": "The system shall respond quickly.",
        "candidate_text": "The system shall respond within 2 seconds.",
    }
    unreviewed = classify_tier([], _grounding(), _consistency(), **options)
    reviewed = classify_tier(
        [], _grounding(), _consistency(), human_reviewed=True, **options,
    )
    assert unreviewed["tier"] == TIER_2
    assert any(r["kind"] == "candidate_changes_requirement_content" for r in unreviewed["reasons"])
    assert reviewed["tier"] == TIER_1
    assert reviewed["reasons"][0]["kind"] == "reviewed_current_rewrite"


def test_unresolved_clarification_blocks_reviewed_rewrite_promotion():
    result = classify_tier(
        [], _grounding(), _consistency(),
        original_text="The system shall respond quickly.",
        candidate_text="The system shall respond within 2 seconds.",
        human_reviewed=True, unresolved_clarification=True,
    )
    assert result["tier"] == TIER_2
    assert any(r["kind"] == "clarification_unresolved" for r in result["reasons"])


def test_human_review_does_not_override_independent_analysis_gates():
    options = {
        "original_text": "The system shall respond quickly.",
        "candidate_text": "The system shall respond within 2 seconds.",
        "human_reviewed": True,
    }
    quality = classify_tier(
        [{"type": "ambiguous", "explanation": "Open interpretation."}],
        _grounding(), _consistency(), **options,
    )
    unsupported = classify_tier([], _grounding("unsupported", evidence=False), _consistency(), **options)
    conflict = classify_tier(
        [], _grounding(), _consistency("conflict", check="fail"),
        unresolved_clarification=True, **options,
    )
    assert quality["tier"] == TIER_2
    assert any(r["kind"] == "quality_defect" for r in quality["reasons"])
    assert unsupported["tier"] == TIER_2
    assert any(r["kind"] == "grounding_insufficient" for r in unsupported["reasons"])
    assert conflict["tier"] == TIER_3
    assert conflict["reasons"][0]["kind"] == "confirmed_requirement_conflict"


def test_tier_explanations_distinguish_actual_blockers():
    unresolved = _consistency("potential_conflict", pairs=[{
        "requirement_ids": ["REQ-EX-001", "REQ-EX-002"],
        "classification": "unassessed", "analysis_state": "unassessed"}], check="skipped")
    result = classify_tier([], _grounding(), unresolved)
    assert result["tier"] == TIER_2
    assert "consistency" in result["explanation"] and "unassessed" in result["explanation"]
    assert "quality defect" not in result["explanation"].lower()
    assert "awaits" not in result["explanation"]
    missing = classify_tier([], _grounding("unsupported", evidence=False), _consistency())
    assert "Grounding" in missing["explanation"] and "quality defect" not in missing["explanation"]
    defect = classify_tier([{"type": "vague"}], _grounding(), _consistency())
    assert "quality defects" in defect["explanation"]
    waiting = classify_tier([], _grounding(), _consistency(), original_text="The system responds.", candidate_text="The system shall respond.")
    assert "explicit human review decision" in waiting["explanation"]
    question = classify_tier([], _grounding(), _consistency(), unresolved_clarification=True)
    assert "clarification questions" in question["explanation"]
    conflict = classify_tier([], _grounding(), _consistency("conflict", check="fail"))
    assert conflict["tier"] == TIER_3 and "supported contradiction" in conflict["explanation"]
