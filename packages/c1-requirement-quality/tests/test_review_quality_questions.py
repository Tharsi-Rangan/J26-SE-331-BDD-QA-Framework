"""Offline question generation uses injected evidence and grants no authority."""
import pytest
from test_candidate_validation import context
from test_grounded_review_intents import review
from c1_requirement_quality.demo_workflow import DemoSession
from c1_requirement_quality.cli import main


@pytest.mark.parametrize('review', [('The system shall notify students quickly.',
    ['The system shall notify students quickly.'])], indirect=True)
def test_rule_question_cli_is_idempotent_and_never_answers_or_approves(review):
    session, rid, _, _, factory = review
    assert main(['generate-review-questions', '--session', str(session.workspace),
                 '--requirement-id', rid]) == 0
    restarted = DemoSession(session.workspace, analyser_factory=factory)
    record = restarted.review_read()[3]['requirements'][rid]
    assert len(record['questions']) == 1
    assert 'quickly' in next(iter(record['questions'].values()))['text']
    assert not record['answers']
    assert not restarted.approval_intents()
    assert restarted.generate_review_questions([rid]) == []
    assert not restarted.read()[0]['requirements'][0]['bdd_ready']


def test_unknown_question_target_does_not_record_events(review):
    session = review[0]
    before = len(session.events)
    with pytest.raises(ValueError, match='Unknown clarification'):
        session.generate_review_questions(['REQ-NOT-001'])
    assert len(DemoSession(session.workspace, analyser_factory=review[4]).events) == before
