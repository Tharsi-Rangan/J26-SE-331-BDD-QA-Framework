import pytest

from c1_requirement_quality.quality_analyser import (
    analyse_requirement,
    analyse_requirements,
)


@pytest.mark.parametrize(
    ("defect_type", "text", "evidence"),
    [
        ("vague", "The system shall accept a suitable identifier.", "suitable identifier"),
        ("ambiguous", "The system may send an email.", "may"),
        ("incomplete", "The system shall respond within [time].", "[time]"),
        ("non_measurable", "The system shall respond quickly.", "quickly"),
        ("non_verifiable", "The system shall provide a secure service.", "secure"),
    ],
)
def test_each_rule_reports_exact_contract_finding(defect_type, text, evidence):
    findings = analyse_requirement(text)

    finding = next(item for item in findings if item["type"] == defect_type)
    assert finding == {
        "type": defect_type,
        "detector": "rule",
        "evidence_span": evidence,
        "explanation": finding["explanation"],
    }
    assert "confidence" not in finding


def test_overlapping_findings_are_preserved():
    findings = analyse_requirement(
        "The system shall be user-friendly and respond quickly."
    )

    assert [(item["type"], item["evidence_span"]) for item in findings] == [
        ("vague", "user-friendly"),
        ("vague", "quickly"),
        ("non_measurable", "quickly"),
        ("non_verifiable", "user-friendly"),
    ]


def test_requirement_without_detected_signals_returns_empty_findings():
    assert analyse_requirement(
        "The system shall reject an invalid password with a validation error."
    ) == []


def test_lexical_quality_rule_can_have_false_positive():
    findings = analyse_requirement(
        "The system shall use secure TLS connections with certificate validation."
    )

    assert [(item["type"], item["evidence_span"]) for item in findings] == [
        ("non_verifiable", "secure")
    ]


@pytest.mark.parametrize(
    "text",
    [
        "The system shall be reliable with 99.9% monthly availability.",
        "The system shall be reliable; reliability of at least 99.9%.",
    ],
)
def test_reliable_is_suppressed_by_explicit_quantitative_criterion(text):
    assert analyse_requirement(text) == []


@pytest.mark.parametrize(
    ("text", "evidence"),
    [
        ("The system may send an email after a password reset.", "may"),
        ("The system could export records to CSV.", "could"),
        ("The system shall provide secure TLS connections.", "secure"),
        ("The system shall be reliable under normal load.", "reliable"),
    ],
)
def test_context_does_not_suppress_unresolved_quality_signals(text, evidence):
    findings = analyse_requirement(text)

    assert evidence in [item["evidence_span"] for item in findings]


def test_reliable_without_quantitative_criterion_remains_non_verifiable():
    findings = analyse_requirement("The system shall provide a reliable service.")

    assert [(item["type"], item["evidence_span"]) for item in findings] == [
        ("non_verifiable", "reliable")
    ]


def test_multiple_requirements_preserve_order_and_independent_findings():
    assert analyse_requirements(
        [
            "The system shall respond quickly.",
            "The system shall reject an invalid password.",
        ]
    ) == [
        [
            {
                "type": "vague",
                "detector": "rule",
                "evidence_span": "quickly",
                "explanation": "The wording uses a subjective or underspecified qualifier.",
            },
            {
                "type": "non_measurable",
                "detector": "rule",
                "evidence_span": "quickly",
                "explanation": "The wording states a qualitative target without a measurable threshold.",
            },
        ],
        [],
    ]


def test_empty_requirement_text_is_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        analyse_requirement(" ")
