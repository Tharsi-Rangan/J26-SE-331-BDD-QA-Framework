# Phase 1B.3 pre-implementation validation findings

Recorded before implementation. Inspected tier classification, BDD policy,
refinement, deterministic generation, workflow persistence, grounding,
consistency, CLI and the frozen v1.0.0 schema.

| Cause | Source evidence | Consequence |
|---|---|---|
| Historical questions passed as open questions | `refinement.py` final reconciliation passes the entire `clarification_questions` array to `bdd_check_from_validation`; `workflow_persistence.py` populates that array with every historical question | Answered/closed history independently prevents readiness |
| Semantic edits always route Tier 2 | `tier_classifier.py:134` requires whitespace-only equivalence even after explicit approval; `bdd_readiness.py:177` blocks Tier 2 | Clean, source-supported approved semantic candidates cannot reach readiness |
| Quality/grounding not replaced on every final-text transition | `refinement.py` updates them only in approved/edited branches; final pass recalculates them for tier but does not store them | Rejection/pending/not-required paths can expose stale candidate defects/evidence/checks for original text |
| Human answers ignored by refinement grounding | `_evaluate_candidate` and final grounding use only `analyse_grounding(text, srs_text)` | Explicit active clarification cannot ground a resolved placeholder |
| Inconsistent generator tier/grounding treatment | `rewrite_generator.py:586` reads classifier key `classification` instead of `tier`; human-substitution proposals may be ranked despite original-SRS-only grounding failure | Candidate assessment differs from refinement; a human-source annotation is not a verification of supported facts |
| CLOSED treated as no longer unanswered regardless of answer validity | Workflow index tracks OPEN/REOPENED only; answers are only checked for non-empty text | Deferral/waiver can be confused with resolution unless validation separately checks active answer relevance |
| No original assessment/current validation signature in ledger | Workflow saves current contract decisions/candidates and events, but not an immutable original assessment | Original/current tiers and evidence are harder to distinguish; dependent validation has no explicit input identity |

Existing project BDD policy checks upstream quality/grounding/consistency,
unresolved questions/placeholders, actor/subject, shall/must followed by an
action token, and non-blocking current tier. A verified single-requirement
no-peer consistency skip is already allowed. It does not require numerical
thresholds or a fully formed Given/When/Then triple. This policy will be kept;
no unsupported new completeness criteria will be inferred.

Implementation decisions:

- Keep all historical text/events internally and in allowed existing contract
  fields, but pass only validation-unresolved questions to the readiness gate.
- OPEN/REOPENED remain unresolved. ANSWERED requires a valid relevant current
  answer. CLOSED defaults to deferred; waiver is not an answer. A closed question
  can use an answer only with explicit answered closure and a valid current answer.
- Preserve immutable original assessments; recompute current text, defects,
  grounding, final-set consistency, tier and readiness every refinement round.
- Permit reviewed semantic candidates to leave Tier 2 only with independently
  supported grounding, clean quality, resolved questions, and no active escalation
  or supported contradiction. Tier 3 checks retain precedence.
- Support active human facts conservatively: exact placeholder/span replacement
  retaining the original SRS scaffold, or an explicitly supplied whole obligation
  answering a requirement/rule/behavior question. Do not infer extra actors,
  conditions, numbers or obligations. Uncovered changes fail grounding.
- Label original SRS and human-answer evidence separately; use existing allowed
  evidence fields with HUMAN-prefixed IDs and explicit human-source sections.
- Sign relevant validation inputs deterministically and always recompute. Answer
  revisions invalidate inherited approval unless explicitly reaffirmed. Approval
  and answer existence alone never pass validation.
- An escalation resolution statement requests rechecking; it is not evidence
  that a contradiction disappeared. Check actual final requirements and original
  SRS support before readiness.

No shared contract schema change is needed: ready output remains
`validation.status = passed`, an accepted explicit `human_decision`, and
`bdd_ready = true`. Additional provenance, original/current distinctions and
signatures belong only to internal sidecars.
