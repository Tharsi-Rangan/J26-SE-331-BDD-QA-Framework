# Phase 1B.2 — Human Clarification and Workflow Persistence

Implemented scope: cumulative question/answer/decision persistence, internal
snapshot lineage, explicit awaiting-human states and safe continuation through
action JSON. Phase 1B.3/1B.4, ML integration, LLM rewriting, other components
and BDD-readiness policy changes remain outside this implementation.

## Exact files modified

All paths are relative to `packages/c1-requirement-quality/`. Earlier working
tree changes, including Phase 1B.1, were retained.

| File | Phase 1B.2 change |
|---|---|
| `src/c1_requirement_quality/workflow_persistence.py` (new) | Question identities/statuses, append-only answer/event history, candidate dispositions, action translation, workflow states, hash/parent-chain/history verification |
| `src/c1_requirement_quality/source_integrity.py` | Bind the workflow SHA256 in the internal source manifest, verify it, and copy/seal the new workflow with the original source bundle |
| `src/c1_requirement_quality/cli.py` | Persist initial workflow state; load and verify parents for refinement; apply cumulative actions; stage/seal new snapshots; reverify the parent before publication; print awaiting-human states |
| `src/c1_requirement_quality/refinement.py` | Retain existing custom questions; preserve previously explicit edited/not-required decisions across rounds; prevent new selections from inheriting an edited approval |
| `src/c1_requirement_quality/rewrite_generator.py` | Verify snapshot lineage, consume saved active answers when no answer file is supplied, respect active escalations and recorded human rejections; deterministic rewrite strategies remain unchanged |
| `tests/test_workflow_persistence.py` (new) | 42 executed regression cases covering multi-round continuity, source/lineage corruption, approval boundaries and candidate-generation continuity |
| `tests/test_refinement.py` | Update the existing legacy Tier 3 CLI fixture to supply an explicit escalation resolution before approval |
| `README.md` | Document internal state, action JSON extensions, actor/time provenance, generation continuity, legacy adoption and unchanged readiness policy |
| `docs/phase1b2-implementation.md` (new) | This implementation report |

No Phase 1B.2 edits were made to requirement-registry code/history,
`bdd_readiness.py`, `tier_classifier.py`, quality/grounding/consistency rules,
ingestion, shared schemas, dependencies, ML modules or model checkpoints.

## Persistence and workflow design

Each new run/refinement snapshot stores a read-only internal file:

```text
c1/internal/workflow_snapshot.json
```

The existing source manifest adds an internal `workflow_sha256` binding. The
snapshot binds its own `artifact_sha256` to the validated contract JSON. Source
document ID, original-byte SHA256 and normalized-ingestion SHA256 are unchanged
through refinement. No workflow fields enter the frozen shared v1.0.0 schema.

The workflow ledger contains:

- A unique persisted snapshot ID, round number, parent reference and source
  identity. Parent references include relative artifact path, snapshot ID,
  artifact hash and workflow hash.
- Requirement-scoped question dictionaries. Question IDs are SHA256 values
  derived from requirement ID plus whitespace-normalized question text.
  Duplicate observations do not create new questions. Exact observed text
  variants, original text, origins and creation event remain available.
- Cumulative answer versions. Each retains answer/question/requirement IDs,
  answer text, explicitly supplied provenance, actor, snapshot/event references
  and resolution state at submission. Changing an answer appends a version;
  earlier versions remain byte-for-byte in subsequent history.
- Cumulative events for explicit human actions and decisions, answer submissions,
  question status changes, reconsideration and escalation resolution. Existing
  candidates, selected IDs and decisions are carried forward.
- Current question statuses and answer pointers; candidate dispositions;
  `unanswered_question_ids`; escalation/request flags and internal workflow state.

The statuses are `OPEN`, `ANSWERED`, `REOPENED`, `CLOSED`. Answering makes a
question `ANSWERED`; reopening clears its active-answer pointer and returns it
to the unanswered index without removing any prior answer. Closing is an
explicit human action and may record a deferral without inventing an answer.
Historical answer `resolution_state` means state at submission; the question's
status/current-answer pointer identifies the current resolution, and events
preserve intervening transitions.

Human actions use supplied `actor_id` only when present, otherwise `unknown`.
Automatic placeholder-question creation uses `system`. Events record the actual
system UTC `recorded_at`, labeled `timestamp_basis: system_recorded_at`.
`human_timestamp` is retained only when supplied; it is a claimed human time,
not inferred or authenticated. Answer provenance is `human_provided` from an
action JSON source, separately from original-SRS evidence.

Workflow states are `AWAITING_CLARIFICATION`, `AWAITING_ESCALATION`,
`REVIEW_PENDING`, `REJECTED`, `VALIDATED`. The CLI reports each requirement's
state and unanswered count. Tier 2 can remain awaiting human review even if
all recorded questions are answered because the existing analysis gates remain
unresolved. An explicit request without a placeholder also persists a wait.

## Action JSON and approval boundaries

Existing fields such as `candidate_texts`, `selected_candidate_id`,
`selected_candidate_text`, `edited_text`, `human_decision`,
`clarification_questions` and `clarification_answers` remain supported.

New internal action fields:

| Field | Behavior |
|---|---|
| `actor_id`, `human_timestamp` | Optional explicit actor/claimed time; also accepted per answer |
| `workflow_action` | `approve`, `reject`, `request_clarification`, `escalate`, `reopen`, `resolve_escalation` |
| `resolution` | Required non-empty human statement for `resolve_escalation`; not SRS evidence |
| `reason` | Optional explanation retained in the event |
| `question_actions` | Requirement-scoped question-ID operations with `REOPENED` or `CLOSED` status and optional reason |
| `reconsider_candidate_ids` | Explicitly reopens review of rejected candidates, without approving them |

Answers can identify a question using its existing text or its stable internal
`question_id`. If both are supplied, they must agree. A foreign requirement's
question is rejected. Optional per-answer `requirement_id` must match the action.
No question text or answer is generated from an inferred human intent.

`approve` and `reject` map to existing contract decisions. Internal request,
escalation and reopen actions do not introduce new shared enum values. Approval
is still explicit. Selecting a new candidate does not inherit approval. A
rejected candidate cannot be selected or approved again without explicit
`reconsider_candidate_ids`; reconsidering the selected candidate alone resets
the decision to pending. An unrelated later round leaves rejection intact.
Reopening revokes current requirement approval and retains earlier decision
events. Candidate disposition is not independent permission to promote a
requirement: the current contract human decision and all gates remain required.

Active escalation requires explicit human resolution before accepting a
requirement. Resolution is recorded, then the existing candidate/final-set
checks rerun. If Tier 3 contradiction remains, escalation becomes active again
and BDD readiness stays false. A resolution statement alone cannot override
contradiction, grounding or other validation failures.

The CLI remains:

```powershell
c1 refine --in <parent>/c1/validated_requirements.json --srs <original-byte-identical-source> --actions <actions.json> --out <new-snapshot-folder>
```

**BDD-readiness promotion rules are unchanged.** Historical question text is
retained in the existing contract `clarification_questions` array, while only
open/reopened IDs appear as unanswered internally. The existing evaluator
still conservatively blocks on its question/tier/check inputs. Answering or
closing a question does not authorize promotion. No human answer is added to
the original SRS or used as original-SRS grounding evidence.

Candidate generation loads and verifies lineage, then reuses current recorded
answers if no explicit answer file is supplied. Reopened/superseded answers are
excluded. Prior human rejections are retained as `persisted_human_rejection`
and active escalation blocks generation as `workflow_escalation`. Generation
does not mutate the parent or create approvals. Explicit answer files retain
their existing generation-only behavior; use refinement to persist them.

## Three consecutive refinement rounds

This is an **executed synthetic regression fixture**, not collected research
data or evidence of a real person's answers/identity. The test explicitly
supplies the shown answer/actor values as simulated action JSON inputs.

Original requirement: `The system shall wait for [timeout].`

- Q1: `What value or rule should replace [timeout]?` (automatic)
- Q2: `Who confirms the timeout?` (custom)

| Snapshot | Parent | Submitted action | Cumulative answers | Unanswered |
|---|---|---|---:|---|
| Initial | none | System detects Q1 | 0 | Q1 |
| Round 1 | Initial | Add Q2; answer Q1 “2 seconds”; request clarification; supplied actor `reviewer-A` | 1 | Q2 |
| Round 2 | Round 1 | Requirement-only action, with no replacement answers/questions | 1 | Q2 |
| Round 3 | Round 2 | Revise Q1 to “3 seconds”; answer Q2 “The requirement owner”; supplied actor `reviewer-B` | 3 | none |

Executed snapshot IDs in the final verification run:

```text
Initial: SNAPSHOT-9105d83cd02b4fc3940b82b23f090273
Round 1: SNAPSHOT-6098dc30ea9f49f8ad626d61ea386c48
Round 2: SNAPSHOT-231d7851304941f4a7fd5c03271aed8d
Round 3: SNAPSHOT-84d0c37115f4476ba1bffe22f76ae4c9
```

Event counts are 1, 5, 6, 9. Each child's event prefix equals its parent's;
answer counts are 0, 1, 1, 3. Q1's first answer remains in history after its
revision. Both question texts remain in the contract. The final human decision
is pending, original text remains final text, and `bdd_ready` stays false.

The fixture's full contracts, actions, manifests and workflow snapshots are in:

```text
C:/Users/HP/AppData/Local/Temp/c1-phase1b2-be8a4d3859924880b44fe2a32e89ef37/pytest-verified/test_three_rounds_preserve_cus0/
```

## Question/answer/decision history example

The ledger retains the causal sequence rather than replacing records:

```text
question_created(Q1, origin=system_placeholder, actor=system)
question_created(Q2, origin=human_question, actor=reviewer-A)
answer_recorded(Q1, "2 seconds", provenance="review meeting", Round 1)
request_clarification(actor=reviewer-A, Round 1)
human_action(requirement-only continuation, actor=unknown, Round 2)
answer_recorded(Q1, "3 seconds", actor=reviewer-B, Round 3)
answer_recorded(Q2, "The requirement owner", actor=reviewer-B, Round 3)
```

The recorded `human_action` events retain complete submitted action JSON in
addition to the semantic events. Q1's current-answer pointer selects the third
round answer; its first answer/event/snapshot reference remains present.

A separate executed regression fixture demonstrates explicit approval followed
by rejection, with actors supplied as `owner` then omitted/`unknown`. Another
demonstrates rejection, an unchanged round, and explicit reconsideration:

```text
human_decision(rejected, selected candidate C)
next snapshot: C remains REJECTED
attempt to select/approve C without reconsideration: rejected before publication
candidate_reconsidered(C): current review becomes PROPOSED/pending
earlier rejection event remains in cumulative history
```

No example value is treated as original-SRS evidence, and system recording
timestamps are not represented as human occurrence times.

## Lineage and source-integrity validation

Before continuation, the complete chain is checked for missing parents,
cycles/repeated snapshot IDs, parent artifact/ledger hash mismatch, source
identity mismatch, inconsistent round numbers, unknown event snapshot/requirement
references, invalid question/answer references, dropped question/answer/event
history, changed candidate text and rejection reversal without reconsideration.
New ledgers are structurally validated before writing. Source bundle hashes
remain checked by Phase 1B.1 verification. A parent is verified again before
the staged refinement is published. Existing snapshots cannot be overwritten.

Phase 1B.1 snapshots without a workflow file can be adopted prospectively into
a new child. Contract questions/candidates/decisions are imported. Available
old diagnostic answers are retained with provenance
`legacy_diagnostics_unsealed`, unknown original actor/time and a captured
diagnostics hash. The original parent is not rewritten. Parent references
also bind this captured legacy diagnostic hash. This preserves available data
without pretending an old unsealed sidecar was originally authenticated.

## Regression tests and exact results

The 42 new executed cases cover all twelve requested regression categories:
multi-round/custom question retention; answer retention/revisions; answered
versus unanswered status; explicit closing/reopening; rejected candidates and
reconsideration; selection/approval separation; inherited edited/not-required
decisions; persistent manual/Tier 3 escalation; valid parent lineage and corrupted
references; source/NIR/parent corruption; frozen contract compatibility.

Additional cases verify duplicate question observations and historical text
variants, requirement-scoped answers, actor/claimed-time provenance, rejection
of invalid actions, generation with saved/reopened/rejected answers/candidates,
prospective legacy adoption, history-drop rejection, exclusive snapshots and
explicit clarification waits without placeholders.

Full final command (repository root, existing Python 3.12 virtualenv):

```powershell
packages/c1-requirement-quality/.venv/Scripts/python.exe -m pytest packages/c1-requirement-quality/tests -p no:cacheprovider --basetemp <verification-directory>/pytest-verified -q
```

Exact final result: **327 passed in 34.90s**; no failures or skips reported.
Environment: `PYTHONDONTWRITEBYTECODE=1`, `HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1`. Existing Phase 1B.1 and local-checkpoint smoke tests
remain included; no models or dependencies were downloaded.

An earlier integration check found that the existing CLI fixture's original
Tier 3 classification needed an explicit resolution under the newly required
boundary. Its action fixture was updated accordingly. All subsequent full
checks passed, including the final result above.

Shared contract validator:

```powershell
node packages/contracts/scripts/validate.mjs <152-generated-output-folders> packages/contracts/fixtures/golden/example-registration
```

**Exit code 0: “All contract checks passed.”** C1-only folders skip absent
downstream stages as designed; the golden fixture retains its existing link
checks. This verifies frozen-contract compatibility, not a newly implemented
C2 pipeline. Failed staging folders were excluded. `git diff --check` passed
with existing CRLF-normalization notices only.

Exact test/validator logs and test artifacts are isolated under:

```text
C:/Users/HP/AppData/Local/Temp/c1-phase1b2-be8a4d3859924880b44fe2a32e89ef37/
```

Logs: `pytest-verified.txt`, `contract-validation.txt`; historical registry
fingerprints: `historical-registry-hashes.json`. Earlier diagnostic test runs
were retained separately and were not deleted.

## Remaining limitations and restrictions

- Historical question text still blocks readiness under the unchanged evaluator.
  Zero unanswered questions does not mean BDD-ready. Post-answer readiness and
  approved semantic-rewrite Tier 2 promotion remain deferred.
- The earlier validation-field reversal issue and unrelated performance work
  remain outside Phase 1B.2. Workflow history does not redesign quality,
  grounding, consistency or readiness analysis.
- Parent snapshots must remain accessible at their relative references. Moving
  only a child breaks lineage; no automatic relocation/recovery is implemented.
- Cumulative JSON grows with rounds and the complete chain is verified during
  continuation. No database or unrelated optimization was introduced.
- Read-only files/hashes are a local integrity boundary, not protection against
  coordinated replacement of the entire chain by someone with filesystem access.
- Legacy unsealed diagnostics lack original authentication and can only be
  captured prospectively. Missing historical answers/actors/times are not inferred.
- Claimed actor IDs and human timestamps are recorded, not authenticated. The
  CLI does not add an identity provider or access-control service.
- Explicit generation-only answer files are not cumulative history until they
  are submitted through refinement.
- Crash-atomicity across run directory/registry, crash recovery and failed
  staging cleanup retain their Phase 1B.1 limitations.

Both historical registries remained SHA256-unchanged:
root `.c1-state/requirement-registry.json` and package
`.c1-state/requirement-registry.json`. Neither was modified, migrated or merged.
Only isolated synthetic test registries were used.

No shared schemas, C2/C3/C4 source, research datasets, models, dependencies,
SQLite or cloud infrastructure were changed. No LLM implementation, downloads,
training, deletion of existing artifacts, commits, pushes, resets or branch
changes occurred. No GUI or web application was built. The research architecture
and existing deterministic analysis/generation strategies remain intact.

Implementation stops at **Phase 1B.2**. Further phases require separate approval.
