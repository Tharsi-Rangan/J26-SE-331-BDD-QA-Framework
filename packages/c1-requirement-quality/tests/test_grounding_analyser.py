from c1_requirement_quality.grounding_analyser import analyse_grounding


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
