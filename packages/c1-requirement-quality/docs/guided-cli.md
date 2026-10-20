# Guided C1 terminal workflow (Stage 4C)

This is the historical command-oriented review reference. The current default
interactive application is documented in [Selectable CLI](selectable-cli.md).
Existing argument-based `demo` commands remain available. Later mandatory-RAG
review integrates the same journal and controlled publication, with versioned
human clarification support; no legacy audit-only pair record is promoted implicitly.

## Start and resume

From the repository root, attach to the verified portable Kinmail bundle with a
fresh session path (the session path itself must not exist):

```powershell
& .\packages\c1-requirement-quality\.venv\Scripts\c1.exe demo `
  --workspace .\packages\c1-requirement-quality\local-inference\kinmail-demo-001 `
  --in .\packages\c1-requirement-quality\local-inference\kinmail-portable-001\run\c1\validated_requirements.json
```

The archived SRS is selected automatically unless `--srs` is supplied explicitly.
The full verified bundle and ancestors must remain accessible. No standalone
validated JSON can replace them. Keep the session on the same drive as the run
family so existing relative parent references can be created.

For a new analysis:

```powershell
c1 demo --workspace <fresh-session-directory> --srs <SRS-file> `
  --run-id RUN-20261015-230000-demo --registry <registry.json> `
  --document-id <stable-document-id>
```

New analysis always uses lexical grounding. The existing run service owns
registry assignment, source sealing and publication. No decision policy is
implemented in the terminal controller.

```powershell
c1 demo --resume <existing-session-directory>
```

Resume uses the saved inputs; do not supply replacement SRS/run arguments.
Workspace pointers are absolute: retain this session's location and referenced
run family. Portable relocation of an entire session journal is not implemented.

## Review commands

- `resolve-pair` (Stage 4D.2): explicitly reaffirm a pair under the reviewed
  consistency policy, declaring complete or partial coverage. A new verified
  refinement snapshot records the review; guided and standalone refinement use
  the same assessment. The terminal explains remaining blockers and all-not-
  applicable coverage. Changed review bases invalidate dependent approvals;
  review adoption never grants approval. See [the policy](consistency-review-policy.md).
- `pairs` also shows how many unique comparisons still block consistency.
  Unknown comparisons and partial/stale reviews remain visible.

- `pairs`: list all unordered pairs with current deterministic outcome, human
  review decision and stale-review warnings. Unreviewed/stale means unresolved.
- `review-pair`: display both original/current requirements, source references,
  original/current deterministic findings and full review history. Optionally
  inspect a hash-matching saved MiniLM diagnostic; similarity never selects a
  decision. Enter one of `not_applicable`, `consistent_within_scope`,
  `conflict_confirmed`, `unresolved`, both source references, reviewed scope,
  conditions, rationale, reviewer ID and explicit `yes`. Enter at the decision
  prompt cancels. Ctrl+C/EOF pauses without recording an incomplete review.

Stage 4D.1 reviews are audit-only. They are recorded in the existing session's
numbered hash-chained `events/` journal, not in a parallel ledger or shared JSON.
They do not invoke refinement or change human approvals, eligibility, tier,
grounding, consistency gates or BDD readiness. Legacy applicability sidecars
remain audit-only and are not converted into these decisions.

Review version 1 binds both original/current texts, source locations, complete
source/normalized-source hashes, current question/answer state and evidence to
`human-consistency-audit-v1`. Source/evidence/policy/clarification changes require
review again. Historical snapshot transitions retain derived invalidation
history, even if wording later returns to its previous value. A changed SRS is
refused by source verification; start a separately verified session rather than
replacing trusted inputs. Superseding a review retains the previous record and
its invalidation reason. Reviewer attribution is not authenticated identity;
hashes detect alteration, not authorship. Recorded human clarification answers
are labelled separately from original-source evidence and do not gain grounding
authority by being cited here.

Keep the session journal with its verified run family: a standalone `c1 refine`
invocation does not import session review events. This is deliberate during the
recording-only stage. Repeated review display verifies historical snapshots;
large histories can take longer. There is no bulk approval or similarity-based
exclusion. Confirmed deterministic conflicts in original or current comparisons
cannot be dismissed with a non-applicability/consistency review.

- `issues`: original/final text, quality findings, evidence, tier, consistency,
  validation, pending questions, candidates, human decision and BDD status.
- `diagnostics`: inspect a saved DistilBERT or MiniLM sidecar. Input hash, all
  IDs/texts, model metadata and advisory status must match. MiniLM shows the top
  15 pairs; all pairs remain in the original sidecar.
- `proposals`: validate a saved clarification sidecar, then review one item or
  `all`. Each question can be accepted, rejected or left pending. Accepted
  questions are submitted in one confirmed refinement action batch, never
  automatically answered or approved. Optional proposed rewrites are displayed
  as untrusted; use `edit` to submit any manually accepted candidate text.
- `generate`: explicitly run the existing deterministic candidate generator.
  This never invokes Groq or local models. A unique bound sidecar is produced.
- `candidates`: review a saved bound candidate sidecar. Choose one or `all` and
  register alternatives, reject a candidate separately, or leave items pending.
  Registration does not imply selection or approval. Rejected/invalid proposals
  are not imported as viable candidates; candidate validation is rerun by refine.
- `answer`: choose a recorded question, enter an actual human answer and,
  optionally, its exact `replaces_span`. Explicit reviewer ID and `yes` are
  required. A recorded answer may still be insufficient for grounding: existing
  exact-scaffold, span-binding and whole-obligation rules remain authoritative.
- `select`: choose a candidate ID already registered in the current artifact.
  Selection does not imply approval; changed selection invalidates old approval.
- `edit`: register/select explicit human-authored text, without implicit approval.
- `decision`: explicitly supply approved, edited, rejected, pending or not_required.
  Approved requires a selected candidate; edited requires text. All independent
  gates still apply even after human acceptance.
- `pause`, EOF or Ctrl+C: leave published snapshots intact and exit safely.

After any refinement action, old diagnostics/proposals/candidate sidecars no
longer match the current artifact hash. They remain available as historical
files, but cannot silently be reused. Batch-review multiple items with `all`
before publishing to avoid unnecessarily making the remaining items stale.
No API or model operation is replayed on resume. This initial implementation
has no live model/provider execution option; use separately approved commands
outside the guided session and return with a matching saved sidecar.

## Persistence and interruption

`session.json` is immutable session metadata. Numbered hash-chained receipts in
`events/` reference actual C1 artifacts rather than duplicating their workflow
state. Confirmed actions are stored exclusively in `actions/`; new C1 snapshots
are published under unique `snapshots/` paths. All human decisions still go
through the existing `refine_run` service and workflow validators.

Before refinement, a pending receipt records the action hash and parent hash.
If interruption occurs after publication but before the completion receipt,
resume offers explicit recovery: adopt the verified child, cancel the operation
while retaining files, or pause. Adoption verifies contract, lineage and input
hashes and never reruns the action. If no child was published, cancel or pause;
there is no silent retry. Failed initial analysis leaves its metadata/staging
for inspection; if no initial artifact exists, start a fresh workspace rather
than reconstruct or automatically rerun it.

An operating-system lock prevents simultaneous terminal review and is released
on process exit/crash. Its empty `.demo.lock` file may remain; it is not a stale
PID lock. Journal checksums detect accidental alteration, not authenticated
human identity or coordinated tampering. Unconfirmed prompt input is not saved;
review rejection receipts and all published snapshots are retained.

Candidate sidecars created by the generator now include input/source/workflow
hashes. Older unbound sidecars are refused for import and must be regenerated.
Proposal sources are revalidated against current source/active answers. Model
claims and advisory references never become independent grounding evidence.

## Demonstration limits

Kinmail's unknown peer comparisons remain blockers. Pair applicability reviews
remain advisory. Neither question acceptance nor human approval forces Tier 1
or BDD readiness. Show a successful single-requirement synthetic test separately
from a full Kinmail handoff; never isolate Kinmail records to evade peer checks.
A final report exporter and positive Kinmail consistency resolution remain
separate work. Do not use this terminal session to claim model accuracy.
