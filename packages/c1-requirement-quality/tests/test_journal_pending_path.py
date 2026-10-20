"""A publishable path must not overflow solely due to its staging filename."""
import json
import os

import pytest

from c1_requirement_quality.demo_workflow import _write


@pytest.mark.skipif(os.name != 'nt', reason='Windows MAX_PATH regression')
def test_long_candidate_reference_staging_retains_exclusive_publication(tmp_path):
    # A 225-character final reference is valid; the previous suffix made 266.
    extra = 225 - len(str(tmp_path)) - len('/reference.json') - 1
    assert extra > 0
    target = tmp_path / ('x' * extra) / 'reference.json'
    _write(target, {'receipt': 'verified'})
    assert json.loads(target.read_text()) == {'receipt': 'verified'}
    with pytest.raises(FileExistsError):
        _write(target, {'receipt': 'replacement'})
    assert json.loads(target.read_text()) == {'receipt': 'verified'}
