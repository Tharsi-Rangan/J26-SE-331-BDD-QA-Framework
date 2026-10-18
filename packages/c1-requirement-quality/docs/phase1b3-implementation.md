# Phase 1B.3 — Tier Transition, Validation Lifecycle and BDD Readiness

Implemented only the approved Phase 1B.3 scope. The research architecture,
source-integrity/identity safeguards, cumulative workflow and frozen C1-to-C2
v1.0.0 schema remain intact. Phase 1B.4 and ML/LLM integration were not started.

## Pre-implementation findings and exact modified files

The required audit was recorded **before implementation** in
[phase1b3-validation-audit.md](phase1b3-validation-audit.md). It identified:

1. Readiness received all historical question texts instead of unresolved active
   questions.
2. Semantic rewrites always remained Tier 2 because classification required
   whitespace-only equivalence even after explicit human review.
3. Rejection/pending/not-required transitions could restore original text while
   retaining the approved candidate's defects, grounding and quality check.
4. Refinement ignored clarification facts, while generation could retain human
   proposals despite SRS-only grounding failure.
5. Generation read classifier key `classification` instead of `tier` and did not
   consistently pass actual question/tier state into validation.
6. Workflow statuses alone treated non-empty answers as answered and CLOSED as
   no longer unanswered, without separate validation of relevance/resolution.
7. No explicit immutable original assessment or validation-input signature
   distinguished historical classification from the current requirement.

All changed paths below are relative to `packages/c1-requirement-quality/`.
Earlier working-tree changes were retained.

| File | Phase 1B.3 change |
|---|---|
| `src/c1_requirement_quality/validation_lifecycle.py` (new) | Original assessment capture, active answer resolution, explicit clarification grounding, separate evidence categories, transient generation inputs and deterministic validation signatures |
| `src/c1_requirement_quality/tier_classifier.py` | Explicitly reviewed semantic current rewrites can qualify after independent gates; unresolved clarification blocks Tier 1; contradiction precedence remains unchanged |
| `src/c1_requirement_quality/bdd_readiness.py` | Explicit active-escalation blocker; clarify that question input means validation-unresolved questions. Existing BDD element policy remains |
| `src/c1_requirement_quality/refinement.py` | Recompute every final-text-dependent field; use current active evidence/questions; prevent changed edited text from inheriting approval; recheck candidates against final peers and retain pre-action assessments |
| `src/c1_requirement_quality/workflow_persistence.py` | Preserve original assessments/root references, current validation/signatures, explicit span bindings and closure kinds; invalidate inherited approval on new answer versions; verify signature/artifact agreement and original history |
| `src/c1_requirement_quality/rewrite_generator.py` | Use the same grounding/resolution path as refinement, correct tier key propagation, reject unsupported human proposals, retain human/SRS provenance and proposal-only approval boundaries |
| `tests/test_validation_lifecycle.py` (new) | 38 executed new regression cases covering requested transitions, fact coverage, peer invalidation, provenance and metadata integrity |
| `tests/test_refinement.py` | Update post-resolution success expectations and correct four eligible fixture tiers that previously used an unrelated generic Tier 3 seed |
| `tests/test_workflow_persistence.py` | Expect separately attributed valid human grounding; allow the stronger signature validator to reject corrupted question history before the parent-prefix validator |
| `README.md` | Document current policy, closure/span fields, original/current distinction and readiness behavior; replace superseded validation descriptions |
| `docs/phase1b3-validation-audit.md` (new) | Required findings recorded before source edits |
| `docs/phase1b3-implementation.md` (new) | This implementation report |

No Phase 1B.3 source changes were made to CLI shape, source archival,
requirement registry, ingestion, lexical quality/grounding/consistency algorithms,
shared schemas, other components, models or dependencies.

## Updated validation decision logic

Every refinement round evaluates current final text independently, including
requirements without explicit actions. The lifecycle is:

1. Verify the source bundle and complete snapshot chain; preserve original
   requirement text, defects, tier and evidence in `original_assessment`, with
   `original_snapshot_id` pointing to the verified root.
2. Apply explicit question/answer/decision actions cumulatively. Preserve old
   questions/answers/events. Reopening revokes approval; newly submitted answers
   invalidate inherited approval unless explicitly reaffirmed.
3. Determine validation-unresolved questions using active status and current
   answer validity/relevance, independently of the historical contract text list.
4. Independently evaluate current quality and grounding. Preserve categories
   `srs_evidence`, `human_clarification_evidence`, unsupported claims and conflicts.
5. Recompute consistency for the complete final requirement set. Recompute every
   candidate assessment against these current final peers; retain its earlier
   pre-action assessment separately.
6. Classify current tier. Supported contradictions retain Tier 3 precedence;
   unresolved facts/questions/checks retain Tier 2. A semantic rewrite can leave
   Tier 2 only after explicit review and successful independent checks.
7. Evaluate the existing BDD elements and all applicable gates. Active escalation
   blocks readiness. Single-requirement no-peer consistency remains the existing
   explicitly verified exception, not a general permission to skip consistency.
8. Publish ready only when validation passed and the current explicit human
   decision is accepted. Approval or answer existence alone cannot pass gates.

Frozen representation remains:

```json
{
  "validation": { "status": "passed" },
  "human_decision": "approved",
  "bdd_ready": true
}
```

The supported existing accepted decisions also include `edited` and explicit
`not_required`, as before. No `BDD_READY` enum or new shared fields were added.
The frozen `TIER_1_AUTO_REFINE` enum is reused for an eligible reviewed current
assessment. It grants no permission for future autonomous semantic changes.
Unreviewed semantic proposals still route Tier 2.

### Question resolution

| State | Validation treatment |
|---|---|
| OPEN / REOPENED | Unresolved; no active answer support |
| ANSWERED | Resolved only if its current answer is valid and relevant |
| CLOSED, omitted closure kind | Defaults to DEFERRED; not successful resolution |
| CLOSED + DEFERRED / WAIVED | Retained as deliberate deferral/waiver; not counted as an answer and still blocks readiness |
| CLOSED + ANSWERED | Resolved only with an existing valid relevant current answer; the flag cannot manufacture one |

Historical text stays in `clarification_questions` and workflow history but is
not independently supplied as an unresolved readiness blocker. The original
workflow unanswered index retains its OPEN/REOPENED meaning. A separate
`validation_unresolved_question_ids` index includes invalid, deferred or waived
closures. This prevents an empty raw unanswered index from becoming readiness.

### Clarification evidence policy

Support is deliberately narrow and explicit:

- Named-placeholder substitution must preserve the original SRS-supported
  scaffold exactly after whitespace normalization. The active answer must
  supply the replacement value; unrelated new actors/conditions/obligations
  cannot be appended.
- A human answer can specify `replaces_span` for one exact, unique original
  span. The answer is the literal replacement; the rest of the obligation is
  preserved. This does not add a rewrite-generation strategy.
- A whole human obligation must exactly match the candidate and answer a
  requirement/rule/behavior statement question, with a shall/must obligation.
- Duration responses must be recognizable complete duration values. Unknown,
  placeholder, clearly wrong fact-type and composite unrelated-obligation
  replies remain invalid/unresolved. These are conservative typed checks,
  not general semantic answer interpretation.
- Existing SRS grounding conflicts are never cleared merely because an answer
  or approval exists. Unsupported paraphrases and uncovered changes fail.

The shared evidence array uses only existing allowed fields. Human items use
`HUMAN-` chunk IDs and section `Explicit human clarification (not original SRS)`.
The quoted text is the actual answer. Internal items additionally retain
question/answer/event/snapshot IDs, actor, supplied provenance and support method.
Human facts are never written into the original SRS or relabeled as SRS facts.

Deterministic generation uses this same grounding policy. Generation-only answer
files use explicitly labeled transient references, not fabricated persisted
human events/timestamps. Those inputs cannot authorize a published requirement;
record active answers through refinement before approval. Strategies remain
deterministic, without an LLM backend.

### Original/current assessment and invalidation

The ledger preserves immutable original text/defects/tier/evidence and the
verified root reference. For older ledgers lacking this metadata, it is adopted
prospectively from the verified root without modifying old files. If only an
already-rewritten legacy artifact is available, original analysis is explicitly
labeled `recomputed_original_baseline_not_historical_observation`; missing old
model/policy assessments are not fabricated.

`current_validation` stores current text, tier, checks, attributed evidence,
clarification resolution, final-peer candidate assessments, readiness and an
input signature. `c1-validation-1b3-v1` signatures include current text,
selection/decision, source text, final peer texts, questions/answers and
escalation/request state. Relevant changes alter the signature; all dependent
fields are always recomputed. A matching signature is not a cached proof.
Stored signature/check/text/tier/readiness disagreement is rejected on loading.
Original assessment changes or incorrect original-root references are rejected.

## Synthetic successful transition and rejection example

These are **executed synthetic regression examples**, not real stakeholder
answers, research datasets or evaluated model results. Action JSON simulates
human input; no real identity or answer provenance is asserted.

Original: `The system shall respond within [timeout].`

Automatically recorded question:
`What value or rule should replace [timeout]?`

Successful test action:

```json
{
  "requirements": [{
    "requirement_id": "REQ-EX-001",
    "clarification_answers": [{
      "question": "What value or rule should replace [timeout]?",
      "answer": "2 seconds"
    }],
    "selected_candidate_text": "The system shall respond within 2 seconds.",
    "human_decision": "approved"
  }]
}
```

| Snapshot | Current tier | Decision | Quality | Grounding | Consistency | BDD check | Ready |
|---|---|---|---|---|---|---|---|
| Initial | Tier 2 | pending | fail | pass against original SRS | skipped, no peers | skipped initial run | false |
| Clarified, rewritten and approved | Tier 1 current | approved | pass | pass using SRS scaffold + attributed active answer | skipped, verified no peers | pass | true |
| Candidate rejected next round | Tier 2 | rejected | fail on restored placeholder text | pass against original SRS | skipped, no peers | fail | false |

Rejection restores original final text, incomplete defect findings and original
grounding evidence. It does not keep the clean candidate's quality result or
human evidence as if those applied to the original text. Original Tier 2
assessment and all answer/approval/rejection history remain available.

Actual fixture directory:

```text
C:/Users/HP/AppData/Local/Temp/c1-phase1b3-6a4ea017f0724b8fbea9fbc526ec4f57/pytest-verified/test_rejection_recomputes_orig0/
```

Another multi-round test changes the answer to `3 seconds`. Inherited approval
is revoked; the old `2 seconds` candidate loses grounding support. Selecting and
explicitly approving the exact `3 seconds` candidate can become ready after all
checks rerun. Both answers and the original Tier 2 assessment remain intact.

## Tier 3 safety demonstration

Synthetic source:

```text
1. The system shall allow deletion.
2. The system shall not allow deletion.
```

An explicit `resolve_escalation` statement saying the owner reviewed the
conflict, with `not_required`, leaves actual texts unchanged. Pair verification
still reports `conflict`, consistency fails, current tier remains Tier 3,
escalation remains active, and readiness is false. Subsequent empty rounds do
not clear it. The resolution event is preserved but never used as proof.

A separate test supplies an exact whole conditional obligation as an active
answer for **both** requirements, explicitly resolves both escalations, selects
the corresponding rewrites and approves them:

```text
The system shall allow deletion when the administrator confirms ownership.
```

The final peer set is independently rechecked and is consistent under the
existing identical-obligation rule. Active human answers supply the new actor
condition explicitly; it is not claimed to originate in the SRS. Current
requirements can become ready, while both original Tier 3 assessments, original
contradiction evidence and both resolution events remain in history. This is
explicit resolution plus validated facts/texts, not an automatic downgrade.

Actual fixture directories are `test_tier3_resolution_statemen0` and
`test_actual_tier3_rewrites_rer0` under the final verification base directory.

## Regression and contract results

The new test module executes **38 cases**, covering all sixteen requested
categories: unanswered, answered-without-rewrite, unsupported rewrite,
unapproved supported proposal, approved validated rewrite, historical answered
questions, reopening, closed-but-unanswered states, rejection, replacement,
answer revision, unresolved/resolved-but-conflicting Tier 3, original history,
frozen contract and multi-round integrity.

Additional cases cover unsupported numbers/actors/conditions/obligations/modal
changes, wrong answer types, malicious composite duration replies, explicit
span grounding, source-only semantic support, actual final-peer Tier 3
resolution, peer-change invalidation, generator/refinement agreement,
original-root reference integrity and corrupted current signatures.

Existing tests were retained. Eligible single/consistent/whitespace fixtures
that used a generic unrelated Tier 3 seed now declare their actual eligible
tier; unresolved legacy Tier 3 still blocks readiness. Three superseded
Phase 1B.2 assertions were updated for the explicitly authorized new behavior,
not relaxed to allow approval-only promotion.

Full final command, repository root, existing Python 3.12 virtualenv:

```powershell
packages/c1-requirement-quality/.venv/Scripts/python.exe -m pytest packages/c1-requirement-quality/tests -p no:cacheprovider --basetemp <verification-directory>/pytest-verified -q
```

**365 passed in 38.73s**, no failures or skips reported. Environment:
`PYTHONDONTWRITEBYTECODE=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`.
Existing ingestion, registry, source integrity, workflow, rule, RAG/mock and
local-checkpoint smoke tests remain included. No models or dependencies were
downloaded. Earlier diagnostic runs were retained separately.

Shared validator:

```powershell
node packages/contracts/scripts/validate.mjs <244-generated-output-folders> packages/contracts/fixtures/golden/example-registration
```

**Exit code 0: “All contract checks passed.”** C1-only folders skip absent
downstream artifacts; the existing golden fixture validates its cross-stage
links. Failed staging folders were excluded. Node schema validation does not
authenticate the internal bundles; intentional integrity corruption is covered
by the Python rejection tests. No new C2 pipeline functionality is claimed.
`git diff --check` passed, with existing CRLF normalization notices only.

Exact logs, synthetic actions/documents/outputs and fingerprint records:

```text
C:/Users/HP/AppData/Local/Temp/c1-phase1b3-6a4ea017f0724b8fbea9fbc526ec4f57/
```

Logs: `pytest-verified.txt`, `contract-validation.txt`. Historical registry
fingerprints: `historical-registry-hashes.json`.

## Remaining limitations and restrictions

- Exact scaffold/span/whole-statement support is conservative. General
  paraphrase entailment, unit conversion and arbitrary semantic answer
  interpretation are not implemented. Untyped custom questions have limited
  relevance heuristics; domain review remains necessary.
- Deferred and waived closures remain blockers without a valid answered closure.
  No automatic waiver exemption is inferred from a status label.
- Quality and consistency use their existing narrow rule coverage. Passing
  those rules is not proof of global defect absence or full semantic consistency.
- BDD elements remain the current project's actor/obligation/action and upstream
  gate policy; no full Given/When/Then completeness requirement is invented.
- Proposal diagnostic `bdd_ready` remains false because proposal assessment is
  not final human authorization. Final requirement validation is authoritative.
- Older missing historical assessments are reconstructed only when possible and
  labeled as reconstruction. Earlier unsealed diagnostic provenance retains its
  Phase 1B.2 limits; actor IDs/claimed times are not authenticated.
- Parent availability, local trust, cumulative JSON growth, crash recovery and
  cross-file crash-atomicity retain their earlier documented limitations.
- Generator research counters are not a new empirical model evaluation. All
  examples above are synthetic tests; no performance or research-quality claims
  are inferred from them.

Root and package historical registries are SHA256-unchanged. Neither was
modified, merged or migrated. No shared schemas, C2/C3/C4 source, datasets,
models, dependencies, SQLite, cloud services or GUI were changed. No LLM
rewriting, training/downloads, deletion of existing outputs, commits, pushes,
resets or branch changes occurred. Only isolated test state was used.

Implementation stops at **Phase 1B.3**. Phase 1B.4 requires separate approval.
