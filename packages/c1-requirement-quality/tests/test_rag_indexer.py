"""Unit tests for the SRS chunking and indexer module."""

import pytest

from c1_requirement_quality.rag.indexer import SRSChunk, SRSIndexer, index_srs


def test_chunk_empty_document_returns_empty_list():
    assert index_srs("") == []
    assert index_srs("   \n  \n") == []


def test_chunk_document_without_headings_has_none_section():
    srs = (
        "The system shall allow users to log in.\n"
        "\n"
        "The system shall allow users to reset passwords.\n"
    )
    chunks = index_srs(srs)

    assert len(chunks) == 2
    assert chunks[0].chunk_id == "SRS-L0001-L0001"
    assert chunks[0].text == "The system shall allow users to log in."
    assert chunks[0].section is None
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 1

    assert chunks[1].chunk_id == "SRS-L0003-L0003"
    assert chunks[1].text == "The system shall allow users to reset passwords."
    assert chunks[1].section is None
    assert chunks[1].start_line == 3
    assert chunks[1].end_line == 3


def test_chunk_document_with_hierarchical_headings_builds_breadcrumbs():
    srs = (
        "# Account Management\n"
        "## Registration\n"
        "Members must be between 18 and 65 years old.\n"
        "Email verification is mandatory.\n"
        "\n"
        "## Password Policy\n"
        "Passwords must contain at least 8 characters.\n"
        "\n"
        "# Security Auditing\n"
        "Failed log in attempts must be logged.\n"
    )

    chunks = index_srs(srs)

    assert len(chunks) == 3

    assert chunks[0].chunk_id == "SRS-L0003-L0004"
    assert chunks[0].section == "Account Management > Registration"
    assert "Members must be between 18" in chunks[0].text
    assert chunks[0].start_line == 3
    assert chunks[0].end_line == 4

    assert chunks[1].chunk_id == "SRS-L0007-L0007"
    assert chunks[1].section == "Account Management > Password Policy"
    assert chunks[1].start_line == 7
    assert chunks[1].end_line == 7

    assert chunks[2].chunk_id == "SRS-L0010-L0010"
    assert chunks[2].section == "Security Auditing"
    assert chunks[2].start_line == 10
    assert chunks[2].end_line == 10


def test_srs_chunk_to_dict_conversion():
    chunk = SRSChunk(
        chunk_id="SRS-L0001-L0002",
        text="Sample text",
        section="Section 1",
        start_line=1,
        end_line=2,
    )
    data = chunk.to_dict()

    assert data == {
        "chunk_id": "SRS-L0001-L0002",
        "text": "Sample text",
        "section": "Section 1",
        "start_line": 1,
        "end_line": 2,
    }


def test_srs_indexer_type_error():
    with pytest.raises(TypeError):
        SRSIndexer(123)  # type: ignore[arg-type]


def test_compute_embeddings_placeholder():
    indexer = SRSIndexer("Sample text.\n")
    chunks = indexer.compute_embeddings()
    assert len(chunks) == 1
    assert chunks[0].embedding is None
