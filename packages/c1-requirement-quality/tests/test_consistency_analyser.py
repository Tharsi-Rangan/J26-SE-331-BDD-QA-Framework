from c1_requirement_quality.consistency_analyser import (
    analyse_consistency,
    consistency_for_requirement,
)


def _req(number, text):
    return {"requirement_id": f"REQ-EX-{number:03d}", "text": text}


def _pair(analysis):
    return analysis["pairs"][0]


def test_explicit_opposing_obligations_are_a_conflict_with_exact_evidence():
    left = "The system shall allow account deletion."
    right = "The system shall not allow account deletion."
    pair = _pair(analyse_consistency([_req(1, left), _req(2, right)]))

    assert pair["classification"] == "conflict"
    assert pair["requirement_ids"] == ["REQ-EX-001", "REQ-EX-002"]
    assert [item["text"] for item in pair["evidence"]] == [left, right]
    for item, original in zip(pair["evidence"], (left, right), strict=True):
        assert original[item["start_offset"] : item["end_offset"]] == item["text"]


def test_supported_opposing_action_verbs_are_conflicts_only_for_identical_predicates():
    pair = _pair(analyse_consistency([
        _req(1, "The system shall allow account deletion."),
        _req(2, "The system shall prohibit account deletion."),
    ]))
    assert pair["classification"] == "conflict"


def test_conflicting_numeric_bounds_for_same_attribute_unit_and_condition():
    pair = _pair(analyse_consistency([
        _req(1, "The user age must be at least 18 years."),
        _req(2, "The user age must be at most 17 years."),
    ]))

    assert pair["classification"] == "conflict"
    assert "no overlapping value" in pair["explanation"]
    assert [item["text"] for item in pair["evidence"]] == ["at least 18 years", "at most 17 years"]


def test_overlapping_numeric_bounds_are_consistent():
    pair = _pair(analyse_consistency([
        _req(1, "The user age must be at least 18 years."),
        _req(2, "The user age must be at most 65 years."),
    ]))
    assert pair["classification"] == "consistent"


def test_numeric_bounds_with_unknown_or_different_units_are_only_potential():
    pair = _pair(analyse_consistency([
        _req(1, "The response time shall be at least 2 seconds."),
        _req(2, "The response time shall be at most 1 minutes."),
    ]))
    assert pair["classification"] == "potential_conflict"
    assert "units" in pair["explanation"]

    missing_units = _pair(analyse_consistency([
        _req(1, "The user age must be at least 18."),
        _req(2, "The user age must be at most 17."),
    ]))
    assert missing_units["classification"] == "potential_conflict"


def test_different_conditions_do_not_become_a_confirmed_conflict():
    pair = _pair(analyse_consistency([
        _req(1, "The system shall allow export when the user is an administrator."),
        _req(2, "The system shall not allow export when the user is a guest."),
    ]))
    assert pair["classification"] == "unassessed"
    assert pair["analysis_state"] == "unassessed"

    numeric_pair = _pair(analyse_consistency([
        _req(1, "The user age must be at least 18 years when the account is adult."),
        _req(2, "The user age must be at most 17 years when the account is juvenile."),
    ]))
    assert numeric_pair["classification"] == "unassessed"


def test_unrelated_requirements_and_missing_comparable_evidence_are_unassessed():
    analysis = analyse_consistency([
        _req(1, "The system shall encrypt stored data."),
        _req(2, "The system shall show the dashboard."),
    ])
    pair = _pair(analysis)
    assert pair["classification"] == "unassessed"
    assert pair["evidence"] == []
    assert analysis["pairs_unassessed"] == 1
    assert consistency_for_requirement("REQ-EX-001", analysis)["check"] == "skipped"


def test_pair_results_and_exact_offsets_are_deterministic():
    left = "  The system shall not permit transfers."
    right = "The system shall permit transfers."
    requirements = [_req(1, left), _req(2, right)]
    first = analyse_consistency(requirements)
    assert first == analyse_consistency(requirements)
    evidence = first["pairs"][0]["evidence"][0]
    assert left[evidence["start_offset"] : evidence["end_offset"]] == evidence["text"]


def test_requirement_aggregation_keeps_both_conflicting_ids_and_check_failure():
    analysis = analyse_consistency([
        _req(1, "The system shall allow account deletion."),
        _req(2, "The system shall not allow account deletion."),
    ])
    result = consistency_for_requirement("REQ-EX-001", analysis)
    assert result["status"] == "conflict"
    assert result["related_requirement_ids"] == ["REQ-EX-002"]
    assert result["conflicts"][0]["with_requirement_id"] == "REQ-EX-002"
    assert "Evidence:" in result["conflicts"][0]["explanation"]
    assert result["check"] == "fail"
