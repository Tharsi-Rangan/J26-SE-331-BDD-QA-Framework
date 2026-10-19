"""Offline journal-backed review does not authorize contract publication."""
import copy
import json

import pytest

from test_candidate_validation import context
from c1_requirement_quality import cli, wizard
from c1_requirement_quality.demo_workflow import DemoSession
from c1_requirement_quality.refinement import stable_candidate_id, process_refinement_actions
from c1_requirement_quality.source_integrity import VerifiedWorkflowContext, require_refinement_grounding


@pytest.fixture
def review(context, tmp_path, monkeypatch, request):
    _, source, _, _, control, factory = context
    original, passages = getattr(request, 'param', ('The system shall retain logs.', ['The system must retain logs.']))
    control['passages'] = passages
    source.write_text('# Requirements\n1. ' + original + '\n', encoding='utf-8')
    monkeypatch.setattr(cli, 'RAGGroundingAnalyser', factory)
    cli.run(source, tmp_path / 'rag', 'RUN-20261019-120000-abcd',
            registry_path=tmp_path / 'rag-registry.json', grounding_mode='rag', mandatory_rag=True)
    artifact = tmp_path / 'rag/c1/validated_requirements.json'
    session = DemoSession.create(tmp_path / 'review', artifact=artifact, source=source)
    session = DemoSession(session.workspace, analyser_factory=factory)
    row = session.read()[0]['requirements'][0]
    return session, row['requirement_id'], row['original_text'].rstrip('.'), control, factory


def select(review, text=None):
    session, rid, candidate, _, _ = review
    candidate = text or candidate
    session.review_action({'requirement_id': rid, 'selected_candidate_text': candidate}, 'Reviewer', True)
    return candidate


def approve(review):
    session, rid, _, _, _ = review
    session.review_action({'requirement_id': rid, 'human_decision': 'approved'}, 'Reviewer', True)


def register(review, candidate=None):
    session, rid, text, _, factory = review
    session.validate_candidate_evidence(rid, candidate or text, analyser_factory=factory)


def test_approval_intent_restart_is_independent_and_never_publishes(review):
    session, rid, candidate, control, factory = review
    before = session.current.read_bytes()
    select(review)
    register(review)
    count = control['analyses']
    approve(review)
    intents = DemoSession(session.workspace, analyser_factory=factory).approval_intents()
    assert len(intents) == 1 and intents[0]['active']
    intent = intents[0]
    assert intent['reviewer'] == 'Reviewer'
    assert intent['eligibility']['candidate_id'] == stable_candidate_id(rid, candidate)
    assert intent['eligibility']['evaluation']['grounding']['meaning_preservation']['status'] == 'preserved'
    assert intent['eligibility']['tier']['tier'] == 'TIER_1_AUTO_REFINE'
    assert not intent['publication_authorized'] and not intent['bdd_ready_authorized']
    assert session.current.read_bytes() == before
    assert session.read()[0]['requirements'][0]['human_decision'] == 'pending'
    assert not session.read()[0]['requirements'][0]['bdd_ready']
    assert control['analyses'] == count
    assert session.pending is None
    assert not (session.workspace / 'snapshots').exists()


@pytest.mark.parametrize('change', ['selection', 'question', 'reopen', 'reject'])
def test_draft_changes_invalidate_intent_including_change_back(review, change):
    session, rid, candidate, _, factory = review
    select(review)
    register(review)
    approve(review)
    if change == 'selection':
        select(review, candidate + '.')
        select(review)
    elif change == 'question':
        session.review_action({'requirement_id': rid, 'clarification_questions': ['Which logs are retained?']}, 'Other', True)
    elif change == 'reopen':
        session.review_action({'requirement_id': rid, 'workflow_action': 'request_clarification'}, 'Other', True)
    else:
        session.review_action({'requirement_id': rid, 'human_decision': 'rejected'}, 'Other', True)
    restarted = DemoSession(session.workspace, analyser_factory=factory)
    assert not restarted.approval_intents()[0]['active']
    assert not restarted.read()[0]['requirements'][0]['bdd_ready']


@pytest.mark.parametrize('passages,label', [
    (['The system shall not retain logs.'], 'entailment'),
    (['The system must retain logs.'], 'neutral'),
    ([], 'entailment'),
    (['The user shall view reports.'], 'contradiction'),
])
def test_ineligible_receipts_cannot_authorize_intent(review, passages, label):
    session, _, _, control, _ = review
    control.update(passages=passages, label=label)
    select(review)
    register(review)
    with pytest.raises(ValueError, match='not eligible'):
        approve(review)
    assert not session.approval_intents()


def test_erroneous_receipt_cannot_authorize_intent(review):
    session, _, _, control, _ = review
    control['raise'] = True
    select(review)
    register(review)
    with pytest.raises(ValueError, match='not eligible'):
        approve(review)
    assert not session.approval_intents()


def test_missing_receipt_and_meaning_changing_candidate_fail_closed(review):
    session, _, _, _, _ = review
    select(review)
    with pytest.raises(ValueError, match='journal-registered'):
        approve(review)
    changed = 'The user shall view reports.'
    select(review, changed)
    review[3]['passages'] = [changed]
    register(review, changed)
    with pytest.raises(ValueError, match='not eligible'):
        approve(review)


def test_human_answers_are_separate_and_deterministic_on_restart(review):
    session, rid, _, _, factory = review
    question = 'Which logs are retained?'
    session.review_action({'requirement_id': rid, 'clarification_questions': [question]}, 'Alice', True)
    session.review_action({'requirement_id': rid, 'clarification_answers': [
        {'question': question, 'answer': 'Audit logs are retained.'}]}, 'Bob', True)
    state = session.review_read()[3]
    answer = state['requirements'][rid]['answers'][-1]
    assert answer['actor_id'] == 'Bob'
    assert answer['provenance']['kind'] == 'human_provided'
    assert answer['provenance']['source'] == 'initial_rag_review_journal'
    assert DemoSession(session.workspace, analyser_factory=factory).review_read()[3] == state
    assert not session.read()[3]['requirements'][rid]['answers']
    select(review, 'The system shall retain audit logs.')
    review[3]['passages'] = ['The system must retain logs.']
    register(review, 'The system shall retain audit logs.')
    with pytest.raises(ValueError, match='not eligible'):
        approve(review)


@pytest.mark.parametrize('action', [
    {'requirement_id': 'wrong'},
    {'selected_candidate_id': 'forged'},
    {'selected_candidate_text': 'A', 'selected_candidate_id': 'forged'},
    {'human_decision': 'not_required'},
    {'eligible': True},
    {'workflow_action': 'resolve_escalation'},
    {'clarification_answers': [{'question': 'unrecorded', 'answer': 'fact'}]},
])
def test_direct_api_cannot_inject_policy_or_identity(review, action):
    session, rid, _, _, _ = review
    before = len(session.events)
    with pytest.raises((ValueError, KeyError)):
        session.review_action({'requirement_id': rid, **action}, 'Reviewer', True)
    assert len(session.events) == before


@pytest.mark.parametrize('reviewer,confirmed', [('', True), ('Reviewer', False), ('Reviewer', 1), (None, True)])
def test_explicit_human_confirmation_required(review, reviewer, confirmed):
    with pytest.raises(ValueError, match='reviewer'):
        review[0].review_action({'requirement_id': review[1]}, reviewer, confirmed)


def test_approval_cannot_be_replayed_as_new_intent(review):
    select(review)
    register(review)
    approve(review)
    with pytest.raises(ValueError, match='Repeated approval'):
        approve(review)


def test_later_registry_event_cannot_authorize_earlier_approval(review):
    session, _, _, _, factory = review
    select(review)
    register(review)
    approve(review)
    events = copy.deepcopy(session.events)
    registration = next(e for e in events if e['kind'] == 'candidate_evidence_registered')
    events.remove(registration)
    events.append(registration)
    previous = None
    from c1_requirement_quality.demo_workflow import _hash
    for index, event in enumerate(events, 1):
        event.pop('sha256')
        event.update(sequence=index, previous=previous)
        event['sha256'] = _hash(json.dumps(event, sort_keys=True).encode())
        previous = event['sha256']
        (session.workspace / 'events' / f'{index:06}.json').write_text(json.dumps(event), encoding='utf-8')
    with pytest.raises(ValueError, match='journal-registered'):
        DemoSession(session.workspace, analyser_factory=factory)


@pytest.mark.parametrize('part', ['eligibility', 'basis', 'reference', 'receipt', 'policy'])
def test_restart_reverifies_full_approval_chain(review, part, monkeypatch):
    session, _, _, _, factory = review
    select(review)
    register(review)
    approve(review)
    if part in {'eligibility', 'basis'}:
        # Even rehashed journal data must agree with recomputed independent checks.
        event = copy.deepcopy(session.events[-1])
        event.pop('sha256')
        event[part] = {}
        from c1_requirement_quality.demo_workflow import _hash
        event['sha256'] = _hash(json.dumps(event, sort_keys=True).encode())
        path = session.workspace / 'events' / f"{event['sequence']:06}.json"
        path.write_text(json.dumps(event), encoding='utf-8')
    elif part == 'policy':
        from c1_requirement_quality.rag import candidate_validation
        monkeypatch.setattr(candidate_validation, 'verification_policy', lambda: {'version': 'changed'})
    else:
        registration = next(e for e in session.events if e['kind'] == 'candidate_evidence_registered')
        path = session.workspace / registration['reference']
        if part == 'receipt':
            path = session.workspace / json.loads(path.read_bytes())['evidence']
        path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises((ValueError, OSError)):
        DemoSession(session.workspace, analyser_factory=factory)


def test_publication_guards_remain_at_direct_entry_points(review, tmp_path):
    session, rid, _, _, _ = review
    data, text, manifest, _ = session.read()
    policy = VerifiedWorkflowContext(session.current, session.source)
    with pytest.raises(ValueError, match='integration is pending'):
        require_refinement_grounding(manifest)
    with pytest.raises(ValueError, match='integration is pending'):
        session.apply({'requirement_id': rid, 'human_decision': 'approved'}, 'Reviewer', True)
    with pytest.raises(ValueError, match='integration is pending'):
        process_refinement_actions(data, {'requirements': []}, text, workflow_context=policy)
    actions = tmp_path / 'actions.json'
    actions.write_text('{"requirements": []}', encoding='utf-8')
    with pytest.raises(ValueError, match='integration is pending'):
        cli.refine_run(session.current, session.source, actions, tmp_path / 'forbidden')
    assert not (tmp_path / 'forbidden').exists()


def test_generation_reuses_existing_services_and_registered_receipts(review):
    session, rid, candidate, control, _ = review
    class Backend:
        def generate(self, *args, **kwargs):
            return [{'text': candidate, 'strategy': 'injected-structural', 'source_evidence': {}}]
    result = session.generate_review_candidates([rid], backend=Backend())
    assert result['requirements'][0]['ranked_candidates']
    assert session.review_read()[0]['requirements'][0]['candidates'][0]['text'] == candidate
    count = control['analyses']
    session.generate_review_candidates([rid], backend=Backend())
    assert control['analyses'] == count
    assert not session.read()[0]['requirements'][0].get('candidates')


def test_default_generator_abstains_without_inventing_facts(review):
    session, rid, _, _, _ = review
    result = session.generate_review_candidates([rid])
    assert not result['requirements'][0]['ranked_candidates']
    assert result['requirements'][0]['zero_candidates_reason']


@pytest.mark.parametrize('review', [('The system shall retain logs', ['The system must retain logs.'])], indirect=True)
def test_default_generator_can_offer_a_verified_structural_alternative(review):
    session, rid, _, _, _ = review
    result = session.generate_review_candidates([rid])
    candidates = result['requirements'][0]['ranked_candidates']
    assert len(candidates) == 1
    assert candidates[0]['text'] == 'The system shall retain logs.'
    assert candidates[0]['strategy'] == 'terminal_punctuation'
    assert candidates[0]['grounding']['meaning_preservation']['status'] == 'preserved'
    session.review_action({'requirement_id': rid, 'selected_candidate_id': candidates[0]['candidate_id']}, 'Reviewer', True)
    approve(review)
    assert session.approval_intents()[0]['active']


def test_generation_caps_proposals_and_does_not_rank_meaning_changes(review):
    session, rid, candidate, control, _ = review
    class Backend:
        def generate(self, *args, **kwargs):
            assert kwargs['max_candidates'] == 3
            return [{'text': text, 'strategy': 'injected', 'source_evidence': {}}
                    for text in [candidate, 'The user shall view reports.', 'The system shall delete logs.',
                                 'The system shall invent a fourth obligation.']]
    count = control['analyses']
    result = session.generate_review_candidates([rid], backend=Backend())
    assert control['analyses'] - count == 3
    assert [c['text'] for c in result['requirements'][0]['ranked_candidates']] == [candidate]
    assert len(result['requirements'][0]['rejected_candidates']) == 2


def test_caller_modified_in_memory_review_is_not_trusted(review):
    session, rid, _, _, _ = review
    select(review)
    register(review)
    session._review_state['requirements'][rid]['selected_candidate_id'] = 'forged'
    # Fresh journal replay, rather than the caller's mutable object, owns policy.
    approve(review)
    assert session.approval_intents()[0]['active']


@pytest.mark.parametrize('review,expected', [
    (('The system shall respond within [timeout].', ['The system shall respond within [timeout].']), 'TIER_2_CLARIFY'),
    (('The system shall retain logs.', ['The system shall not retain logs.']), 'TIER_3_ESCALATE'),
], indirect=['review'])
def test_unresolved_and_escalated_tiers_cannot_approve(review, expected):
    session, rid, _, _, _ = review
    assert session.read()[0]['requirements'][0]['tier'] == expected
    select(review)
    register(review)
    with pytest.raises(ValueError, match='not eligible'):
        approve(review)
    result = session.generate_review_candidates([rid])
    assert not result['requirements'][0]['ranked_candidates']


@pytest.mark.parametrize('part', ['artifact', 'workflow', 'source', 'manifest', 'model'])
def test_modified_provenance_cannot_restore_intent(review, part):
    session, _, _, control, factory = review
    select(review)
    register(review)
    approve(review)
    if part == 'model':
        control['models']['nli']['asset_sha256']['weights'] = 'different'
    else:
        target = {'artifact': session.current, 'workflow': session.current.parent / 'internal/workflow_snapshot.json',
                  'source': session.source, 'manifest': session.current.parent / 'internal/source_manifest.json'}[part]
        target.chmod(0o644)
        if part == 'manifest':
            data = json.loads(target.read_bytes())
            data['workflow_sha256'] = '0' * 64
            target.write_text(json.dumps(data), encoding='utf-8')
        else:
            target.write_bytes(target.read_bytes() + b' ')
    with pytest.raises((ValueError, OSError)):
        DemoSession(session.workspace, analyser_factory=factory)


def test_receipt_from_another_session_is_not_an_approval_capability(review, tmp_path):
    session, rid, candidate, _, factory = review
    select(review)
    register(review)
    other = DemoSession.create(tmp_path / 'other', artifact=session.current, source=session.source)
    other = DemoSession(other.workspace, analyser_factory=factory)
    other.review_action({'requirement_id': rid, 'selected_candidate_text': candidate}, 'Other', True)
    with pytest.raises(ValueError, match='journal-registered'):
        other.review_action({'requirement_id': rid, 'human_decision': 'approved'}, 'Other', True)


def test_direct_unregistered_receipt_arguments_are_not_accepted(review, tmp_path):
    with pytest.raises(TypeError):
        review[0].review_action({'requirement_id': review[1]}, 'Reviewer', True,
                               receipt=tmp_path / 'forged.json', eligible=True)


def test_rejection_and_request_clarification_survive_restart(review):
    session, rid, candidate, _, factory = review
    select(review)
    session.review_action({'requirement_id': rid, 'human_decision': 'rejected'}, 'Reviewer', True)
    session.review_action({'requirement_id': rid, 'workflow_action': 'request_clarification',
                           'clarification_questions': ['Which logs should be retained?']}, 'Other', True)
    restarted = DemoSession(session.workspace, analyser_factory=factory)
    record = restarted.review_read()[3]['requirements'][rid]
    assert record['candidates'][stable_candidate_id(rid, candidate)]['status'] == 'REJECTED'
    assert record['clarification_requested']
    assert not restarted.approval_intents()


def test_legacy_review_overlay_leaves_published_behavior_unchanged(context, tmp_path):
    artifact, source, _, _, _, _ = context
    session = DemoSession.create(tmp_path / 'legacy-review', artifact=artifact, source=source)
    assert session.review_read() == session.read()
    with pytest.raises(ValueError, match='verified RAG provenance'):
        session.review_action({'requirement_id': context[2]}, 'Reviewer', True)


def test_wizard_selection_approval_and_resume_use_review_journal(review, tmp_path):
    session, rid, candidate, _, _ = review
    select(review)
    register(review)
    answers = iter(['Reviewer', 'yes'])
    output = []
    ui = wizard.Wizard(tmp_path / 'ui', ask=lambda _: next(answers), tell=output.append)
    assert ui.publish(session, {'requirement_id': rid, 'human_decision': 'approved'})
    assert session.approval_intents()[0]['active']
    assert any('publication and BDD readiness remain blocked' in line for line in output)


def test_wizard_approval_automatically_verifies_evidence_and_records_intent(review, tmp_path):
    session, rid, _, _, _ = review
    select(review)
    answers = iter(['1', 'Reviewer', 'yes'])
    output = []
    ui = wizard.Wizard(tmp_path / 'ui', ask=lambda _: next(answers), tell=output.append)
    ui.approval(session, rid)
    assert session.approval_intents()[0]['active']
    assert ui.next_action(session, session.review_read()[0]['requirements'][0], session.review_read()[3]) == 'intent_recorded'


def test_wizard_clarification_answers_resume_with_human_provenance(review, tmp_path):
    session, rid, _, _, factory = review
    session.review_action({'requirement_id': rid, 'clarification_questions': ['Which logs are retained?']}, 'Alice', True)
    answers = iter(['1', 'Audit logs are retained.', '', '1', 'Bob', 'yes'])
    ui = wizard.Wizard(tmp_path / 'ui', ask=lambda _: next(answers), tell=lambda _: None)
    ui.questions(session, rid)
    restarted = DemoSession(session.workspace, analyser_factory=factory)
    answer = restarted.review_read()[3]['requirements'][rid]['answers'][-1]
    assert answer['actor_id'] == 'Bob'
    assert answer['answer'] == 'Audit logs are retained.'
    assert answer['provenance']['kind'] == 'human_provided'
