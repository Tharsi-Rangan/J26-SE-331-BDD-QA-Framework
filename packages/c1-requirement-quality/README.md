# c1-requirement-quality — Grounded Requirement Quality and Refinement

**Owner:** Jathusan J. (@Jathusan-Jesuthasan). Only the owner edits this folder (see `docs/INTEGRATION_RULES.md`).

This package is **Python** (Presidio, NLI, sentence-transformers and ML classifiers are Python tools).
It talks to C2 only through `c1/validated_requirements.json`, so the language does not affect anyone else.

## Set up (once)

The whole team uses **Python 3.12** (CI too). `pyproject.toml` refuses other versions.

```
cd packages/c1-requirement-quality
py -3.12 -m venv .venv            # Windows  (macOS/Linux: python3.12 -m venv .venv)
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
python --version                  # must print Python 3.12.x
pip install -e ".[dev]"
```

## Run and test

```
c1 run --srs <file> --out runs/<RUN-DIRECTORY> --run-id <RUN-ID> --registry <registry.json>
pytest
```

### Requirement registry selection

Pass `--registry <path>` explicitly. C1 does not choose a historical default.
The root legacy registry has active `REQ-EX-080`, next number 81 and 79 retired
IDs; the package legacy registry has active `REQ-EX-155`, next number 156 and
154 retired IDs. Neither history has been declared authoritative. Both remain
unchanged and read-only to the new registry implementation. Do not merge them
or reprocess against them implicitly. Tests use isolated new registries.

New registries scope active IDs by logical document identity and allocate IDs
across the project. An exact section-hierarchy/text pair keeps its ID through
insertion, renumbering, reordering and duplicates added in other sections.
Identical text within the same hierarchy is indistinguishable and is rejected
before state publication; give the occurrences distinct source sections.
Changing text or its hierarchy creates a new identity and retires the old ID
only in that document. Another document cannot retire its IDs.

By default a document identity hashes its resolved source location, while the
source version hashes its bytes. Use `--document-id <stable-logical-id>` on
every version when continuity must survive renaming/moving the source. Separate
files with the same basename at different locations are separate documents.
Reusing an explicit document ID declares the files to be versions of that same
logical document; choose these IDs deliberately within a project registry.

An approved legacy migration can use `RequirementRegistry.export_legacy` with
an explicit mapping from every old active key to `(context, exact_text)` and a
logical document ID. It writes a **new** file, retains every ID, retirement and
allocator high-water mark, and never changes or merges the original histories.
For CLI compatibility, context is the JSON encoding of the NIR requirement's
`section_hierarchy`, e.g. `json.dumps(["Requirements"], ensure_ascii=False)`.
No historical migration has been executed. The team must choose an owner,
history, document bindings and destination before doing so.

### Source integrity and publication (Phase 1B.1)

Each new run stores read-only original bytes in `c1/internal/source/<filename>`,
the complete NIR in `c1/internal/normalized_ingestion.json`, and identity/hash/
format/original-location metadata in `c1/internal/source_manifest.json`.
The manifest hashes original bytes, normalized data and the validated artifact.
The frozen contract contains no new internal fields; its existing
`source_document.path` points to the archived source relative to the run folder.

Both `refine` and `generate-candidates` require this bundle and verify the input
artifact, archive, normalized data and supplied SRS bytes before using evidence.
Same-name changed content is rejected. Renamed but byte-identical supplied
files are accepted. Refinement copies the original source/NIR unchanged into
its new output and binds a new manifest to the new artifact. Legacy artifacts
without a manifest fail closed: they require an explicitly verified reprocessing
run, not filename-only fallback or an inferred hash.

Runs require a fresh `c1` directory, stage output in a sibling
`.c1-run-pending-*` folder and validate before publishing. Registry allocation
stays in memory until publication; the registry is committed last under an
exclusive lock and stale snapshots are rejected. If registry publication fails,
the C1 directory is moved back to staging and the registry is unchanged.
Failed staging files are retained for inspection, never used as final output.
Refinement also stages before publishing. Candidate sidecars refuse overwrites.
After a process crash, leftover locks/staging need explicit inspection; there is
no automatic recovery/resumption implementation in Phase 1B.1. Read-only files
and hashes detect accidental alteration, not coordinated tampering by a user
who can replace the entire bundle. Filesystem crash-atomicity across the run
directory and registry is not claimed.

### Human clarification history (Phase 1B.2)

New runs also write `c1/internal/workflow_snapshot.json`, with its SHA256 bound
in the source manifest. Each refinement snapshot preserves cumulative events,
question texts/identities/statuses, all answer versions, candidate disposition,
and explicit decisions. Parent artifact paths are relative to the new `c1`
folder; parent artifact/ledger hashes, snapshot IDs, source identity and history
prefixes are checked through the complete chain. Keep parent snapshots available.
Moving just one snapshot without its parents breaks the reference and fails
closed. Existing snapshots are never overwritten.

Question IDs hash the requirement ID and whitespace-normalized question text.
Automatic placeholder questions and custom string questions are deduplicated;
original text variants remain auditable. Internal statuses are `OPEN`,
`ANSWERED`, `REOPENED`, and `CLOSED`. Answers are append-only versions with
question/requirement IDs, supplied provenance, event/snapshot references, and
resolution state at submission. Reopening clears the current answer pointer
and retains every earlier version. `unanswered_question_ids` contains only
open/reopened questions. Human answers never become original SRS facts.

Existing `refine --actions <JSON>` fields remain supported. Additional internal
action fields are:

- `actor_id` and `human_timestamp`: optional, explicitly supplied identifiers or
  claimed times. If absent, human actions use actor `unknown` and no human time.
  Events record the actual system `recorded_at` separately; automatic question
  creation uses actor `system`.
- `workflow_action`: `approve`, `reject`, `request_clarification`, `escalate`,
  `reopen`, or `resolve_escalation`. Approve/reject map to existing contract
  decisions; the other actions remain internal. Resolution requires non-empty
  `resolution` text and reruns the existing checks. If a contradiction remains,
  escalation stays active. Reopening revokes approval and implies no new answer.
- `question_actions`: a list of `{ "question_id": "<ID>", "status":
  "REOPENED|CLOSED", "reason": "<optional reason>" }` operations.
- `reconsider_candidate_ids`: explicitly permits reconsidering prior rejected
  candidates. Reconsideration resets the selected rejection to pending, never
  to approval. New selection still does not imply approval.
- Answers may reference `question_id` or the existing `question` text, and may
  supply per-answer `actor_id`, `human_timestamp` and `provenance` metadata.

The workflow sidecar distinguishes `AWAITING_CLARIFICATION`,
`AWAITING_ESCALATION`, `REVIEW_PENDING`, `REJECTED` and `VALIDATED`. The CLI
prints these states and unanswered counts. It remains a file-based batch CLI,
with no interactive prompt, web UI, or automatic answers. Tier 2 can remain
awaiting review/clarification even when every recorded question is answered.

Phase 1B.2 originally left BDD-readiness rules unchanged. Phase 1B.3 now
uses valid active clarification resolution and independently revalidates the
current rewrite as documented below. The contract question list still retains
historical text. An empty unanswered index alone is never readiness approval.

Candidate generation verifies the lineage and reuses active recorded answers
when no explicit answer file is supplied. It excludes reopened answers, preserves
human rejections, and blocks active escalations. Deterministic generation
strategies and original-SRS grounding checks are unchanged. An explicit answer
file still supplies generation-only inputs; persist those answers with `refine`
if they must become part of the snapshot audit history.

Phase 1B.1 source-verified snapshots without a workflow sidecar can be adopted
prospectively into a new snapshot without modifying the parent. Existing
contract decisions/questions/candidates and available diagnostic answers are
retained; old diagnostics are labeled `legacy_diagnostics_unsealed` and their
current hash is captured. This does not retrospectively authenticate their
original human actor/time. Missing older answer history cannot be reconstructed.
See [the Phase 1B.2 implementation report](docs/phase1b2-implementation.md).

### Current validation lifecycle (Phase 1B.3)

Every refinement round replaces current defects, grounding, final-set
consistency, tier and readiness fields for **all** requirements, including
rejection, replacement, answer updates and reopening. Original text remains
unchanged in the contract. The workflow preserves `original_assessment` and its
verified root snapshot reference, plus separately recomputed `current_validation`.
Current candidate diagnostics use final peer texts; pre-action assessments remain
in diagnostics for audit. Relevant input signatures include text/selection,
human decision, source text, peer texts, questions/answer history, escalation,
request state and policy version. Results are always recomputed rather than
reused merely because a signature matches.

Readiness uses validation-unresolved questions, not historical text. OPEN and
REOPENED remain unresolved. ANSWERED requires a valid relevant current answer.
CLOSED defaults to `closure_kind: DEFERRED`; explicit `WAIVED` is not an answer.
`closure_kind: ANSWERED` allows a closed question to use its existing valid
answer, but cannot manufacture one. Deferred/waived/invalid answers continue
to block validation; their histories are retained.

Active human clarification can support only explicitly supplied facts. Supported
routes are exact named-placeholder substitution retaining the SRS scaffold;
explicit `replaces_span` plus replacement answer retaining the rest of the
original obligation; or an exact whole shall/must statement responding to a
requirement/rule/behavior question. Duration answers must be recognizable
duration values, not a duration followed by unrelated new obligations. Known
question types reject clearly mismatched answers. Uncovered changes to numbers,
actors, conditions, obligations or units fail grounding. No paraphrase or unit
conversion is inferred.

For a span replacement, add `replaces_span` to the recorded answer, e.g. the
literal defective span `quickly` and an explicit replacement answer
`within 2 seconds`. This is an internal clarification binding, not an automatic
rewrite strategy. The existing deterministic generator and human-authored
candidate paths remain available; no LLM backend is introduced.

SRS and human evidence remain separate in internal `grounding_categories`.
The shared artifact uses only existing evidence fields, with `HUMAN-` chunk IDs
and section `Explicit human clarification (not original SRS)` for human quotes.
Unsupported facts and conflict diagnostics remain internal. Original evidence
is preserved in the original assessment/source bundle.

A semantic candidate stays Tier 2 before required human review. After explicit
approval/editing, it can become current Tier 1 only if quality, attributable
grounding, resolved questions and peer consistency independently pass. The
frozen `TIER_1_AUTO_REFINE` label is reused for the current eligible assessment;
it grants no permission for further autonomous semantic edits. Confirmed
contradictions always retain Tier 3 precedence. Active escalation blocks
readiness until explicit resolution and successful rechecking. A resolution
statement alone is insufficient.

The current BDD element policy remains actor/subject, shall/must plus action,
no unresolved placeholders/questions, upstream quality/grounding/consistency,
and eligible current handling. Verified single-requirement no-peer consistency
is non-blocking. Approval alone and an answer alone never pass these gates.
Answer revisions revoke inherited approval unless explicitly reaffirmed; new
candidate selection/editing and reopening do not carry old approval forward.
Final ready representation remains `validation.status: passed`, an accepted
human decision and `bdd_ready: true`; no schema enum is added.

See [the Phase 1B.3 implementation report](docs/phase1b3-implementation.md) and
[the pre-implementation findings](docs/phase1b3-validation-audit.md).

Validate your output against the shared contract (from the repo root):

```
node packages/contracts/scripts/validate.mjs runs/<RUN-ID>
```

Stage A writes both `c1/parsed_requirements.json` and the contract-compliant
`c1/validated_requirements.json`. The latter intentionally keeps every
requirement pending review. Because the frozen contract has no unchecked
consistency status, the analyzer uses `potential_conflict` as a conservative
sentinel when no supported pairwise conclusion is available; this does not
claim that a conflict was detected. An empty `defects` array means only that no detector has reported a
defect, not that the requirement is defect-free.

Stage B adds deterministic lexical analysis in
`src/c1_requirement_quality/quality_analyser.py`. The independent rules report
signals for vague, ambiguous, incomplete, non-measurable, and non-verifiable
wording. They preserve overlapping findings and copy matched evidence exactly.
They are explainable heuristics, not a complete quality assessment: they can
produce false positives for wording that is clarified elsewhere and false
negatives for defects expressed without the implemented signal phrases.
The analyser suppresses only `reliable` when the same requirement contains an
explicit percentage-based availability or reliability target, such as `99.9%
monthly availability` or `reliability of at least 99.9%`. It does not suppress
`may`, `could`, or `secure` merely because technical terms or surrounding
details are present; those signals require richer context than this lexical
analyser provides. The CLI records findings in `defects` and maps the quality
check to `pass` or `fail` without promoting a requirement to ready.

Add dependencies to `pyproject.toml` (not a global pip install), so CI and teammates get them too.
Copy `.env.example` to `.env` for model settings. Never commit `.env`.

### Cross-requirement consistency

`src/c1_requirement_quality/consistency_analyser.py` compares every unordered
pair from the same parsed SRS. `c1/consistency_diagnostics.json` records pair
classifications, both requirement IDs, explanations, and exact evidence spans
with half-open character offsets. The `refine` workflow rechecks proposed
candidates against the untouched input requirement texts, then recomputes
consistency for the complete final-text set after all human decisions.

The analyzer reports a confirmed `conflict` only for (a) the same normalized
obligation and condition with opposite explicit `shall`/`must` negation or a
narrow supported opposing action verb, or (b) explicit numeric bounds on the
same normalized attribute, unit, and condition whose allowed intervals do not
overlap. Compatible explicit bounds and identical normalized obligations are
reported `consistent`. Missing/different units create `potential_conflict`;
different conditions, unrelated text, unsupported wording, and comparisons
that do not match a rule remain internally `unassessed`. No similarity score,
general semantic guess, or model is used.

The frozen contract has no `unassessed` status and no structured evidence-span
field for consistency. C1 retains the true analysis state and spans in its
separate diagnostics file. In the contract, unassessed or single-requirement
cases retain the conservative `potential_conflict` sentinel and the validation
check stays `skipped`; this does not assert that a conflict was detected.
Confirmed conflicts use the existing `conflict` status, both IDs, and an
explanation containing quoted evidence. A consistency check is marked `pass`
only when all comparisons for that requirement match supported rules and are
consistent; a confirmed conflict makes it `fail`. An inconclusive comparison
cannot make it pass. BDD readiness still requires every existing gate and an
eligible human decision.

This is intentionally a narrow rule set. It does not normalize units across
dimensions or convert values, infer actor-role overlap, resolve exceptions or
precedence, or establish whether differently worded predicates are equivalent.
Those cases remain for human review; team approval is needed before expanding
the rule vocabulary or treating analyzer coverage as a complete consistency
proof.

### Requirement tier classification

`src/c1_requirement_quality/tier_classifier.py` applies the existing C1
methodology using quality findings, traceable grounding evidence, and
cross-requirement consistency results. Run output keeps the explanation and
evidence in `c1/tier_diagnostics.json`; refinement diagnostics include
assessments for each candidate and the final requirement text. Refinement
recalculates tiers after all selected final texts are known.

| Tier | Deterministic rule | Handling meaning |
| --- | --- | --- |
| `TIER_1_AUTO_REFINE` | No quality findings; attributable supported evidence; resolved validation questions; and consistent peers or a verified no-peer case. Unreviewed candidates must preserve content after whitespace normalization; explicitly reviewed current semantic rewrites may qualify after all independent gates pass. | Initial automatic edits remain structural-only. Current qualification does not generate, approve, or authorize further semantic edits. |
| `TIER_2_CLARIFY` | Any quality finding; unsupported, partial, missing, or untraceable grounding; or any potential/unassessed peer comparison. | Human review or clarification is needed before adding or changing facts or behavior. |
| `TIER_3_ESCALATE` | A confirmed pairwise contradiction, including a grounding contradiction corroborated by the deterministic consistency rules. | Human resolution is required before proceeding. |

Conflict evidence takes precedence over other findings. Tier is not computed
from defect count or the severity/priority labels. An unassessed pair cannot
produce Tier 1. A one-requirement SRS has no peer pair to compare; it can still
reach Tier 1 only when quality findings are empty and grounding is supported
by traceable evidence. Tier does not set validation status, human decision, or
`bdd_ready`; those safeguards remain independent.

Under the current team direction, Tier 3 is reserved for confirmed
contradictions. The existing analyses do not define an objective threshold
for calling a standalone quality defect “too broken”; such defects currently
require clarification under Tier 2 unless a supported contradiction is also
found. A new non-contradiction Tier 3 trigger requires a separate policy decision.
The rule-based analyzer also cannot establish that a requirement is globally
defect-free; Tier 1 means only that the implemented checks found no blocker.

### Defect severity and remediation priority

C1 writes `c1/quality_assessments.json` beside the normal run artifacts. The
refinement workflow includes corresponding per-candidate and final-text
assessments in `c1/refinement_diagnostics.json`. These are internal diagnostics;
the frozen v1.0.0 contract has no severity or priority fields, and the validated
artifact is unchanged by these assessments.

The deterministic rubric describes specification-quality impact only:

| Defect category | Severity | Rationale |
| --- | --- | --- |
| Incomplete | high | An explicit unresolved placeholder can leave required behavior undefined. |
| Ambiguous | high | Multiple plausible interpretations can lead to different implementations. |
| Vague | moderate | Subjective wording obscures the intended behavior or acceptance boundary. |
| Non-measurable | moderate | A target lacks a measurable threshold. |
| Non-verifiable | moderate | A stated quality lacks an objective verification criterion. |

For multiple findings, the highest known severity is reported. Priority is a
remediation ordering derived only from severity: high severity maps to high
priority and moderate severity maps to normal priority. C1 currently has no
validated dependency-impact or blocking data for this assessment, so neither
is inferred. These labels do not represent business, safety, security, or
operational risk and do not assign or change a refinement tier, validation
status, human decision, or BDD readiness.

An unknown finding type, missing evidence span, or no detected findings is
marked `needs_review`; severity is `unknown` when no known finding can be
assessed. In particular, an empty finding list means only that existing rules
did not match. The per-finding diagnostics retain the exact evidence span and
give a plain-language rationale. This initial rubric is an explicit C1
proposal and should be confirmed by the research team before interpreting its
labels as project-approved risk or policy.

Stage C adds deterministic standalone grounding analysis in
`src/c1_requirement_quality/grounding_analyser.py`. It compares candidate
claims with supplied SRS text using conservative exact-claim matching and
returns exact evidence spans. It does not infer support from general lexical
overlap, and its narrow conflict checks do not resolve conflicting source
statements. The CLI uses this lexical analyser by default. RAG is opt-in with
`--grounding-mode rag`; its diagnostics are written separately to
`c1/rag_diagnostics.json` and are excluded from the contract object. In RAG
mode, successfully loaded local model IDs are recorded in the schema-approved
optional `producer.model` field. Neither grounding mode sets `bdd_ready` to
true.

## Local RAG grounding (opt-in)

Lexical grounding remains the default and does not load RAG models. To use
RAG, install the optional dependencies and explicitly cache the two local
models. The CLI never downloads model weights automatically.

PowerShell, from this package directory:

```powershell
pip install -e ".[rag]"
$env:HF_HOME = "$env:USERPROFILE\.cache\huggingface"
hf download sentence-transformers/all-MiniLM-L6-v2
hf download cross-encoder/nli-deberta-v3-small
c1 run --srs <file> --out runs/<RUN-ID> --run-id <RUN-ID> --grounding-mode rag
```

Run the `hf download` commands on a network-enabled machine. For a restricted
or offline machine, copy the complete Hugging Face cache directory to that
machine and set `HF_HOME` to the copied directory before running C1. To prevent
any Hub network access during inference, also set
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. Use the same `HF_HOME` for
model preparation and inference. A missing package or model file is reported
in the separate `c1/rag_diagnostics.json`; it is not treated as evidence that
the requirement is false. The contract output remains conservative when no
grounding evidence can be established.

## User-authored refinement candidates and decisions

The `refine` command does not generate rewrite text; it accepts alternatives
written by a requirement engineer, evaluates each with the existing lexical
quality, grounding, and consistency checks, and applies only an explicitly supplied human
decision. The original requirement is preserved in `original_text` in every
case. Explicit `[placeholder]`, `TBD`, and `TBC` markers produce clarification
questions; answers are never inferred.

Create an actions JSON file. Answers and candidate text are supplied by the
human; answers are retained in the separate run-local diagnostics file and are
not added as new contract fields:

```json
{
  "requirements": [
    {
      "requirement_id": "REQ-EX-001",
      "candidate_texts": [
        "The system shall return a result within 2 seconds."
      ],
      "clarification_questions": ["What response time is required?"],
      "clarification_answers": [
        {"question": "What response time is required?", "answer": "2 seconds"}
      ],
      "selected_candidate_text": "The system shall return a result within 2 seconds.",
      "human_decision": "pending"
    }
  ]
}
```

Process a validated C1 artifact into a **new** output folder (the folder must
not already exist). The artifact keeps the input `run_id`:

```powershell
c1 refine --in runs/<RUN-ID>/c1/validated_requirements.json `
  --srs <source-srs.md> --actions <actions.json> --out runs/<RUN-ID>-refined
```

Candidate IDs are deterministic hashes scoped to the requirement and exact
candidate text. A selection alone leaves `human_decision` pending and
`final_text` equal to `original_text`. `approved` requires a selected
candidate; `edited` requires `edited_text` and records that text as a
candidate. `rejected` and `pending` retain the original as `final_text`.
`not_required` must first be explicitly supplied by a human and can then be
preserved in subsequent unchanged refinement rounds.
Candidate checks, evidence, unsupported claims, and supplied clarification
answers are written to `c1/refinement_diagnostics.json`; the validated output
contains only fields permitted by the frozen v1.0.0 schema.

Candidate diagnostics list independent quality, grounding, final-peer
consistency and BDD-readiness checks. Proposal evaluation itself never sets
`bdd_ready: true`; the final requirement must satisfy every applicable check
and the required explicit human decision.

Grounding uses lexical SRS support plus separately attributed, exact active
clarification support as specified in Phase 1B.3. Unsupported paraphrases,
unprovided facts and unverified conflicts remain blocked. Human answers are
never relabeled as SRS evidence. Approval does not override failed/skipped
checks; only the already-defined verified single-requirement no-peer skip is
non-blocking. Tier is a current handling assessment and never implies approval.
Inconclusive consistency comparisons keep the conservative
`potential_conflict` contract sentinel and do not pass the consistency check.

## First Planner tasks

- C1-02 Mini-SRS for the 3 pilot modules + golden `c1/validated_requirements.json`
- C1-04 SRS parser + requirement extraction with stable `REQ` IDs (FR-C1-01)
- C1-03 Datasets: PURE subset + 40 annotated requirements + 10 contradictory pairs
