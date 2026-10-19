from c1_requirement_quality.grounding_analyser import analyse_grounding
import pytest


def test_fully_supported_claim_returns_exact_traceable_evidence():
    srs = (
        "# Registration\n"
        "Members must be between 18 and 65 years old.\n"
    )

    result = analyse_grounding(
        "Members must be between 18 and 65 years old.",
        srs,
    )

    assert result["status"] == "supported"
    assert result["evidence"] == [
        {
            "chunk_id": "SRS-L0002-L0002",
            "text": "Members must be between 18 and 65 years old.",
            "section": "Registration",
        }
    ]
    assert result["unsupported_claims"] == []
    assert result["conflicts"] == []


def test_partial_support_reports_unsupported_additional_behavior():
    srs = "The system shall send a password reset email.\n"
    candidate = (
        "The system shall send a password reset email; "
        "the system shall send a password reset text message."
    )

    result = analyse_grounding(candidate, srs)

    assert result["status"] == "partially_supported"
    assert [item["text"] for item in result["evidence"]] == [
        "The system shall send a password reset email."
    ]
    assert result["unsupported_claims"] == [
        "the system shall send a password reset text message."
    ]


def test_unsupported_claim_has_no_fabricated_evidence():
    result = analyse_grounding(
        "The system shall verify users with a text message.",
        "The system shall allow users to register by email.\n",
    )

    assert result["status"] == "unsupported"
    assert result["evidence"] == []
    assert result["unsupported_claims"] == [
        "The system shall verify users with a text message."
    ]


def test_missing_threshold_is_not_inferred_from_age_verification():
    result = analyse_grounding(
        "The system shall reject users under 18.",
        "The system shall verify the user's age.\n",
    )

    assert result["status"] == "unsupported"
    assert result["evidence"] == []
    assert result["unsupported_claims"] == [
        "The system shall reject users under 18."
    ]


def test_conflicting_source_passages_are_both_preserved():
    srs = (
        "# Password policy\n"
        "The password must be at least 8 characters long.\n"
        "\n"
        "# Account security\n"
        "The password must be at least 12 characters long.\n"
    )

    result = analyse_grounding(
        "The password must be at least 8 characters long.",
        srs,
    )

    assert result["status"] == "partially_supported"
    assert [item["text"] for item in result["evidence"]] == [
        "The password must be at least 8 characters long.",
        "The password must be at least 12 characters long.",
    ]
    assert [item["section"] for item in result["evidence"]] == [
        "Password policy",
        "Account security",
    ]
    assert result["conflicts"] == [
        {
            "claim": "The password must be at least 8 characters long.",
            "evidence_chunk_ids": [
                "SRS-L0002-L0002",
                "SRS-L0005-L0005",
            ],
        }
    ]


def test_empty_candidate_is_not_applicable_and_empty_srs_is_unsupported():
    assert analyse_grounding(" \n ", "A source statement.\n")["status"] == (
        "not_applicable"
    )

    result = analyse_grounding("The system shall allow registration.", " \n ")
    assert result["status"] == "unsupported"
    assert result["evidence"] == []


def test_lexical_overlap_alone_does_not_establish_support():
    result = analyse_grounding(
        "The system shall allow registration using facial recognition.",
        "The system shall allow registration using email.\n",
    )

    assert result["status"] == "unsupported"
    assert result["evidence"] == []


def test_explicit_negation_conflict_is_distinguished_from_missing_support():
    result = analyse_grounding(
        "The system shall not allow registration.",
        "The system shall allow registration.\n",
    )

    assert result["status"] == "partially_supported"
    assert result["unsupported_claims"] == []
    assert result["conflicts"]
    assert result["evidence"][0]["text"] == (
        "The system shall allow registration."
    )


def test_results_are_stable_across_repeated_runs():
    candidate = "The system shall reject users under 18."
    srs = "# Eligibility\nThe system shall verify the user's age.\n"

    assert analyse_grounding(candidate, srs) == analyse_grounding(candidate, srs)


def test_docx_description_label_is_structural_only_in_complete_block():
    source = "Functional Requirement 1\n\nTITLE: Retention\n\nDESC: The system shall retain logs for 30 days."
    text = "The system shall retain logs for 30 days."
    result = analyse_grounding(text, source, source_format="docx")
    assert result["status"] == "supported"
    assert result["evidence"][0]["text"] == "DESC: " + text
    assert result["evidence"][0]["text"] in source
    assert analyse_grounding(text, source)["status"] == "unsupported"
    for unstructured in ["DESC: " + text, "TITLE: Retention\n\nDESC: " + text,
                         "Functional Requirement 1\n\nNOTE: Retention\n\nDESC: " + text]:
        assert analyse_grounding(text, unstructured, source_format="docx")["status"] == "unsupported"
    assert analyse_grounding("The system shall retain logs for 90 days.", source, source_format="docx")["status"] != "supported"
    assert analyse_grounding("The system shall not retain logs for 30 days.", source, source_format="docx")["status"] != "supported"


def test_docx_multisentence_description_preserves_all_quotes_and_claim_checks():
    text = "Users can register. The system shall send email."
    source = "Functional Requirement 1\n\nTITLE: Registration\n\nDESC: " + text
    result = analyse_grounding(text, source, source_format="docx")
    assert result["status"] == "supported"
    assert len(result["evidence"]) == 2
    assert all(e["text"] in source for e in result["evidence"])
    assert analyse_grounding(text + " The system shall charge a fee.", source, source_format="docx")["status"] == "partially_supported"
@pytest.mark.parametrize("left,right", [("<", ">"), ("<=", ">="), ("=", "!="), ("≤", "≥")])
def test_symbolic_comparisons_do_not_disappear(left, right):
    source = f"The system shall respond in {left} 2 seconds."
    candidate = f"The system shall respond in {right} 2 seconds."
    assert analyse_grounding(candidate, source)["status"] != "supported"
    assert analyse_grounding(source, source)["status"] == "supported"
