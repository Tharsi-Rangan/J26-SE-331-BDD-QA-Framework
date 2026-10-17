"""Integrity-aware setup for hand-authored CLI fixture artifacts."""
import pytest

from c1_requirement_quality.source_integrity import snapshot_source, seal_source


@pytest.fixture
def archive_test_source():
    def archive(input_path, source):
        _, manifest = snapshot_source(input_path.parent, source, "TEST-DOCUMENT")
        seal_source(input_path.parent, manifest)
    return archive
