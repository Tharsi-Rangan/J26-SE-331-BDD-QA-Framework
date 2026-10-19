# C1 Requirement-Smell Annotation Guideline (Draft)

**Status:** Draft for research-team review; not approved for labeling or evaluation.
**Draft version:** 0.1

## 1. Purpose and scope

This guideline proposes a consistent human-labeling process for evaluating the
C1 requirement-smell detector. It covers five independent labels:
`vague`, `ambiguous`, `incomplete`, `non_measurable`, and `non_verifiable`.
Labels describe evidence in requirement text and its supplied SRS context; they
are not severity, priority, tier, validation status, human approval, or BDD
readiness.

The existing C1 implementation is a deterministic lexical rule baseline, not
the proposed gold-label policy and not a complete detector. This draft keeps
its behavior visible so a later evaluation can measure agreement and
disagreement rather than silently changing what the baseline detects.

## 2. Proposed label definitions

Annotators should assess each label independently. A positive label requires
textual or contextual evidence that the requirement has the corresponding
specification problem. Do not mark a label positive merely because the
requirement lacks a preferred writing style.

| Label | Proposed operational definition | Existing C1 rule signals (baseline only) |
| --- | --- | --- |
| `vague` | A material term, quality, or boundary is subjective or underspecified enough that its intended meaning cannot be determined from the available SRS context. | `suitable …`, `appropriate`, `reasonable`, `easy`, `user-friendly`, `quickly` |
| `ambiguous` | The text or its context supports two or more materially different interpretations of required behavior, scope, actor, or condition. | `and/or`, `either … or`, `may`, `might`, `could`, `as needed` |
| `incomplete` | The requirement contains an unresolved placeholder or omits information necessary to determine its intended behavior. Whether implicit omissions count requires team confirmation. | `TBD`, `TBC`, `to be determined/defined/decided`, bracketed placeholders such as `[time]` |
| `non_measurable` | A stated target or quality has no objective quantity, threshold, or observable criterion by which its degree or limit can be assessed. | `quickly`, `promptly`, `efficiently`, `high-performance`, `within a reasonable time` |
| `non_verifiable` | The requirement lacks an objective way to determine whether it has been satisfied, such as an observable result or a pass/fail oracle. | `secure`, `reliable`, `robust`, `scalable`, `intuitive`, `user-friendly`; the baseline suppresses `reliable` only when the same requirement contains a recognized percentage-based reliability/availability target |

These definitions are proposals. In particular, the research team must decide
whether `incomplete` includes implied omissions, how much surrounding context
may resolve a smell, and when vague, non-measurable, and non-verifiable should
co-occur.

## 3. Positive and negative examples

Examples are illustrative and are not labeled research data. For each example,
the stated context is part of the judgment.

### `vague`

- **Positive:** “The system shall accept a suitable identifier.” `suitable`
  has no stated suitability criterion in the requirement or supplied SRS
  context.
- **Negative:** “The system shall accept identifiers containing 8 to 24
  alphanumeric characters.” The acceptance boundary is explicit. This is a
  negative example for `vague`, not a claim that every other quality property
  is satisfied.

### `ambiguous`

- **Positive:** “The system may send an email after a password reset.” If the
  requirement set does not say whether sending is optional, conditional, or
  required, materially different behavior is possible. The current rule
  flags `may` regardless; annotation should record whether the ambiguity is
  real in context.
- **Negative:** “The system shall send exactly one email after each successful
  password reset.” The actor, event, and expected count are explicit in this
  example.

### `incomplete`

- **Positive:** “The system shall respond within [time].” `[time]` is an
  unresolved placeholder. The current rule flags this form directly.
- **Negative:** “The system shall respond within 2 seconds.” The response
  target is supplied. This example does not establish that the whole SRS is
  complete.

### `non_measurable`

- **Positive:** “The system shall respond quickly.” No response-time limit or
  measurement condition is available. The current rules report both
  `vague` and `non_measurable` for `quickly`.
- **Negative:** “Under 100 concurrent requests, the system shall return a
  response within 2 seconds for at least 95% of requests.” The target and
  measurement conditions are explicit.

### `non_verifiable`

- **Positive:** “The system shall provide a secure service.” No testable
  security property or acceptance criterion is given. The current rule flags
  `secure`, including in some technically detailed wording.
- **Negative:** “For each login, the system shall reject a password that does
  not meet the 12-character minimum and record the rejection event.” The
  example gives observable behavior that can be checked. Annotators should
  still consider whether the supplied context makes the behavior testable.

## 4. Overlapping labels

The labels are not mutually exclusive. Judge and record every label
independently; do not force a single “main defect.” For example,
“The system shall be user-friendly and respond quickly” may be labeled
`vague`, `non_measurable`, and `non_verifiable`: the wording is subjective,
the response target is unbounded, and no objective usability or response
criterion is provided. The current tests expect `user-friendly` to trigger
both `vague` and `non_verifiable`, and `quickly` to trigger both `vague` and
`non_measurable`.

An annotator should not copy the rule baseline mechanically. If context makes
one label negative while a lexical rule still fires, record the contextual
rationale; the discrepancy is useful evaluation evidence.

## 5. Context rules

1. Label the requirement as presented, then consult the surrounding SRS
   definitions, glossary, tables, and directly applicable rules supplied for
   annotation. Record the source/context used when it changes a judgment.
2. Do not invent a value, actor, condition, definition, exception, or
   acceptance rule that is absent from the supplied material.
3. A placeholder is a strong signal for `incomplete`. If another supplied
   section explicitly resolves it, annotators may judge the requirement in
   that context and explain the decision. The current lexical baseline still
   flags placeholders without contextual resolution; keep this difference
   visible in evaluation.
4. Missing information should be labeled `incomplete` only when it is
   necessary to determine intended behavior under the eventual approved
   definition. Whether this includes implied omissions is unresolved policy.
5. Do not automatically label every `may`, `might`, or `could` ambiguous.
   Determine whether optionality is intended and sufficiently bounded. The
   current baseline flags these terms regardless of context.
6. If a term such as “secure” or “reliable” is defined elsewhere, use that
   evidence when annotating. The baseline’s suppression is narrower: it only
   suppresses `reliable` when its same-requirement percentage pattern matches
   the implemented rule.
7. A negative label means the annotator found no evidence for that smell in
   the supplied text and context; it does not mean the requirement is
   globally defect-free.

## 6. Evidence spans

Every positive decision should include an exact evidence span when the smell
is expressed by text. Store offsets against the unmodified `requirement_text`:

- `start_offset` is zero-based and inclusive.
- `end_offset` is zero-based and exclusive.
- Offsets count Unicode code points as Python string indexing does, not UTF-8
  bytes.
- The invariant is
  `requirement_text[start_offset:end_offset] == evidence_text`.
- Do not trim or normalize the text before calculating offsets.

For a smell based on omitted information, include the shortest relevant
requirement phrase as an anchor span when possible and explain what necessary
information is absent. An evidence explanation does not replace a span when
an exact phrase is available. Multiple spans may be recorded for one label.

## 7. Uncertain cases

Do not force a positive or negative label when the supplied context is
insufficient or the label boundary is unclear. Mark that label uncertain,
record a concise reason, and set the annotation to `needs_adjudication`.
Uncertain records must not enter the adjudicated binary evaluation set until
resolved. For raw annotations, the team should approve whether uncertainty is
represented as `null` plus an `uncertain_labels` list or in a separate
per-label decision field; final `adjudicated_labels` must contain binary
values only.

## 8. Proposed annotation record (JSONL)

One JSON object per line represents one stable requirement example with
independent annotations and an adjudicated result. Example IDs are dataset
IDs, not persistent C1 `REQ-*` IDs. This example is illustrative only:

```json
{"example_id":"C1-ML-EX-001","source_system_id":"SYS-EXAMPLE-01","source_document_id":"DOC-EXAMPLE-01","requirement_text":"The system shall respond quickly.","annotations":[{"annotator_id":"ANN-01","labels":{"vague":1,"ambiguous":0,"incomplete":0,"non_measurable":1,"non_verifiable":0},"positive_evidence":{"vague":[{"start_offset":25,"end_offset":32,"evidence_text":"quickly","explanation":"No objective response boundary is stated."}],"non_measurable":[{"start_offset":25,"end_offset":32,"evidence_text":"quickly","explanation":"No response-time threshold is stated."}]},"uncertain_labels":[],"uncertainty_notes":null}],"adjudicated_labels":{"vague":1,"ambiguous":0,"incomplete":0,"non_measurable":1,"non_verifiable":0},"adjudication_status":"adjudicated","adjudication_note":"Illustrative only; no research annotation has been performed.","label_guide_version":"0.1-draft"}
```

The exact raw-annotation representation for uncertainty and the allowed
`adjudication_status` values require team approval before dataset collection.
Source identifiers and data provenance should be documented without
substituting dataset IDs for the project requirement registry.

## 9. Independent annotation, adjudication, and versioning

- Annotators should label independently before seeing one another’s labels.
- Preserve each annotator’s original labels, evidence, uncertainty, and
  annotator ID; do not overwrite disagreements with the adjudicated answer.
- Send uncertain labels and disagreements to the designated adjudicator.
  Record the adjudicator, resolution, and rationale in the adjudication
  record. The research team must approve the number of annotators and who may
  adjudicate.
- Report agreement before adjudication, preferably per label. The agreement
  statistic and minimum acceptable agreement are decisions for the research
  team; do not treat adjudicated labels as independent votes.
- Version the label guide and dataset separately. Every record should name
  the guide version used. If a definition changes, preserve the old version
  and document any re-annotation or mapping policy.
- Keep split assignment and evaluation labels frozen and versioned before
  comparing models.

## 10. Limitations and decisions for approval

This is a draft protocol, not an approved project policy or labeled dataset.
The current C1 rules are lexical heuristics: they can miss smells expressed
without their patterns and can flag words whose context is adequate. The
tests explicitly document some overlaps and false positives; they do not
establish label validity or annotator agreement.

Research-team approval is needed for: operational definitions and overlap
policy; whether implicit omissions count as `incomplete`; context boundaries;
uncertainty encoding and adjudication status values; annotator/adjudicator
roles and agreement criteria; and the dataset source, license, and
versioning/provenance requirements. Do not begin labeling or report model
performance as research evidence until these decisions and the data protocol
are approved.
