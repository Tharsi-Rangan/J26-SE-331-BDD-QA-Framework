from c1_requirement_quality.severity_priority import assess_defects


def _finding(defect_type, evidence="word"):
    return {"type": defect_type, "evidence_span": evidence}


def test_each_existing_defect_category_has_documented_deterministic_assessment():
    expected = {
        "incomplete": ("high", "high"),
        "ambiguous": ("high", "high"),
        "vague": ("moderate", "normal"),
        "non_measurable": ("moderate", "normal"),
        "non_verifiable": ("moderate", "normal"),
    }
    for defect_type, (severity, priority) in expected.items():
        assessment = assess_defects([_finding(defect_type)])
        assert assessment["status"] == "assessed"
        assert (assessment["severity"], assessment["priority"]) == (severity, priority)


def test_multiple_findings_use_highest_severity_and_preserve_explanations():
    defects = [_finding("vague", "suitable"), _finding("ambiguous", "may")]
    assessment = assess_defects(defects)

    assert assessment["severity"] == "high"
    assert assessment["priority"] == "high"
    assert [item["evidence_span"] for item in assessment["findings"]] == ["suitable", "may"]
    assert all(item["explanation"] for item in assessment["findings"])


def test_unknown_type_and_missing_evidence_require_review():
    assessment = assess_defects([
        _finding("unsupported_type"),
        {"type": "vague"},
    ])

    assert assessment["status"] == "needs_review"
    assert assessment["severity"] == "moderate"
    assert assessment["priority"] == "needs_review"
    assert len(assessment["review_reasons"]) == 2
    assert assessment["findings"][0]["severity"] == "unknown"


def test_no_findings_is_unknown_instead_of_a_clean_bill_of_health():
    assessment = assess_defects([])

    assert assessment["status"] == "needs_review"
    assert assessment["severity"] == "unknown"
    assert assessment["priority"] == "needs_review"
    assert "not evidence" in assessment["explanation"]


def test_assessment_is_deterministic():
    defects = [_finding("incomplete", "TBD"), _finding("non_verifiable", "secure")]
    assert assess_defects(defects) == assess_defects(defects)
