# Stage 4E: beginner terminal wizard

## Phase 2, Step 3: mandatory initial RAG grounding

Step 3B.1 adds a conservative applicability check. Exact symbolic evidence and
narrow numeric contradictions remain authoritative. An NLI judgment can establish
support/contradiction only when an explicit obligation signature matches, retaining
actors, objects, conditions, units, quantities and entity numbers. Numbered-list
prefixes, shall/must and polarity are the only applicability normalizations. No
cosine cutoff or semantic non-applicability claim is introduced. Unknown NLI
contradictions remain visible and make the claim inconclusive even if another
passage supports it; an applicable contradiction still takes precedence. This
can conservatively block paraphrases pending human review. Per-passage
`evidence_assessments` retain raw NLI labels, applicability and effective outcomes.

Bracketed placeholders, TBD/TBC and explicit to-be-determined/defined/decided
markers abstain before symbolic/NLI support, in both claims and evidence. A
statement containing its own placeholder does not establish the missing fact.
Quality findings remain separate. The fact extractor explicitly recognizes day
units so same-obligation retention bounds can use existing numeric verification.

After initial RAG, owned CPU model references and indexed embeddings are released
and cyclic objects collected before DistilBERT. The sealed RAG provenance includes
available-memory observations before RAG, after inference and after release.
This does not guarantee allocator/OS memory recovery. The existing 3 GiB guard
still controls whether the mandatory DistilBERT stage may run; insufficient memory
continues to leave the analysis incomplete. Resume does not reload released models.

New numbered-wizard imports now select the existing RAG grounding service before
tier classification. One document index is reused for all requirements. Existing
rule-based fact extraction is explicitly selected (`use_spacy=False`); MiniLM
retrieves traceable source chunks, symbolic checks run first per passage, and
local DeBERTa verifies passages on which symbolic checks abstain. Similarity is
only retrieval relevance. Neutral/inconclusive claims remain unresolved; any
contradicted fact prevents fully supported grounding. Retrieval covers its top-k
passages, not a proof that every relevant passage in the source was examined.

Both local model directories must pass structural/label/file checks. Asset hashes
are captured before and after analysis. These hashes establish local identity and
change detection, not independent remote authentication or model accuracy.
The existing 3 GiB memory preflight is retained. There are no downloads or cloud
requests. NLI stays lazy where symbolic verification settles every passage.

`c1/rag_diagnostics.json` records requirement IDs, original text, factual claims,
verification outcomes, per-passage outcomes, and retrieved evidence with line
references. `c1/internal/rag_provenance.json` binds model provenance to the exact
contract artifact, archived source and normalized ingestion hashes. The existing
source manifest seals both files. Resume verifies these bytes without redoing
retrieval or inference. Errors mark the stage incomplete, retain staging files
and `rag_failure.json`, and prevent initial run/registry publication. A neutral
result is an executed check with an unresolved claim, not a model failure or
successful grounding. Existing source, approval and C2 schema policies remain.

This is the initial-analysis-only integration step. New RAG runs are available
for inspection and export, with pending approvals and no BDD-ready rows.
Refinement publication and candidate sidecar generation are deliberately refused
for the sealed `c1-initial-rag-v1` policy until the same RAG and human-evidence
validation are integrated into refinement. A CLI refinement cannot silently
replace authoritative RAG with lexical checks. Old sessions and advanced lexical
runs retain their existing behavior; existing data is never backfilled.

## Phase 2, Step 2: mandatory initial local classification

New imports in the normal numbered wizard automatically run the verified local
DistilBERT classifier. The existing initial artifact is published first so the
prediction service can bind its output to the exact artifact hash. Classification
then runs before the session is opened for human review. Progress now has seven
stages. Initial tier calculation remains deterministic and precedes this ML
stage; ML scores do not change tiers, findings, approvals or readiness.

Scores for all five defect labels, requirement IDs/text, checkpoint provenance
and the input hash are saved in `sidecars/initial-defect-predictions.json` inside
the new session. No cutoff is chosen: `predicted_defects` remains empty rather
than inventing validated binary predictions. There is no learned readiness head.
`ml_analysis.json` binds completed results to their bytes. Resume verifies these
files without loading a model or replaying inference. These are original-text
predictions, not predictions for later human-edited final text.

Missing dependencies, unavailable/unverified assets, low memory or inference
errors leave the stage incomplete and retain an exact error in `ml_failure.json`
when ordinary exception handling can publish it. An interrupted stage without a
completion receipt is also incomplete. Start a fresh analysis after correcting
the cause; no automatic retry or recovery is claimed. Baseline artifacts may
already exist, with pending decisions and no ready requirements, but do not
represent completion of the mandatory analysis.

Only local assets are loaded, with existing checkpoint verification and memory
guards. Old sessions and advanced batch/diagnostic commands retain their existing
behavior; old sessions are not backfilled with predictions. Step 3 above now
adds mandatory initial RAG; cloud orchestration is unchanged. Older Stage 4E
notes below describe historical behavior where AI stages were skipped on import.

## Stage 4E.4: DOCX compatibility and analysis progress

The existing native file picker is retained. Import now displays the file name,
type, resolved selected path and supported-extension status. Choose **Analyse
this document** to start, or **Back to import** to choose again. Extension support
does not guarantee the document contains recognised requirements. Cancelling the
picker returns to import without creating a session.

```text
Step 1 - Import SRS
  1. Browse SRS file (optional Windows dialog)
  2. Paste an SRS file path
  3. Use bundled sample SRS
  4. Back

Selected file: C1_Demo_SRS_Campus_Library.docx
File type: DOCX
Selected path: C:\Users\HP\Downloads\C1_Demo_SRS_Campus_Library.docx
Supported format: yes. Contents will be checked during extraction.

Confirm document before analysis
  1. Analyse this document
  2. Back to import
```

Rich is available in the current environment and is used opportunistically on
interactive terminals: a live panel shows each stage's status, a spinner and a
bar counting completed stages. It is not a new required dependency. Missing Rich,
redirected output or a dumb terminal uses the built-in line-oriented fallback.
No GUI framework, browser frontend or package installation is needed.

Stages are Read SRS document; Extract and identify requirements; Rule-based
quality checks; Grounding and consistency checks; Tier classification; Prepare
human review. Each begins pending and is updated by actual service transitions.
The extraction completion includes its actual count after ID assignment. The
last stage completes only after publication and session source/workflow checks.
Completed means that the implemented stage ran successfully, not that all
requirements passed its quality or readiness gates.

An example fallback display during successful Campus extraction is:

```text
[COMPLETED] Read SRS document - Source bytes archived
[COMPLETED] Extract and identify requirements - 12 requirements identified
[RUNNING] Rule-based quality checks ...
Analysis progress [##----]: 2 / 6 stages completed
[PENDING] Grounding and consistency checks
[PENDING] Tier classification
[PENDING] Prepare human review
```

Only completed stages count toward the bar. Rich displays green completion
ticks only for completed stages. Failures mark the current stage failed; later
stages remain pending. DistilBERT, MiniLM and Groq are explicitly skipped and do
not count as executed stages. The fallback logs transitions chronologically;
the Rich panel continuously displays current states.

The DOCX loader now recognises explicit FR/NFR/REQ numeric ID headings under
functional/non-functional requirement sections and associates one immediately
adjacent prose requirement body. It retains body wording, source IDs, parent
hierarchy, heading/body paragraph provenance and all original source blocks.
This includes permissive wording such as FR-007's `may` and preserves
`[CANCELLATION_WINDOW]`. It does not merge additional explanatory paragraphs,
cross a table, accept a following heading/question as a body, or harvest
stakeholder-review examples. Unsupported bodies produce a diagnostic warning;
unassociated prose remains context. This is structural recognition, not general
semantic splitting or a change to quality/tier/readiness policy.

Read-only verification of the original Campus DOCX now yields exactly these 12
source items: FR-001, FR-002, FR-003, FR-004, FR-005, FR-006, FR-007, FR-008,
FR-009, FR-010, NFR-001 and NFR-002. Its SHA-256 remains
`ba1e68be2aa4bdc6bd030e90e5bcfa4dfb8bb62dbb3b2864f78a7080e6b61999`.
The archived Kinmail DOCX still extracts 21; the bundled Markdown still extracts
3. Source document IDs remain traceability metadata; canonical C1 requirement
IDs continue to come from the unchanged registry service.

If zero requirements are found, the wizard explains supported statement/block
layouts and offers the bundled sample. Technical exception/staging information
is behind **Details**. Retained failed sessions are preserved; retry creates a
new session. The earlier two failed Campus sessions are not repaired, deleted
or overwritten by this change.

The Stage 4E.3 sequential review, exact-candidate approval, explicit
no-rewrite-needed decision, escalation resolution and verified JSON export are
unchanged. Groq multi-candidate generation, readable SRS/HTML export, semantic
NLI and automatic C2 execution remain outside this stage.

Stage 4E.4 verification: **686 full-suite tests passed in 80.58 seconds**.
The final focused run, including the added real Campus offline wizard-session
test, passed **92 tests in 17.94 seconds**, with zero failures. Counts overlap.
It covers import confirmation/cancellation, actual stage ordering/counts,
failure ticks, final publication failures, Rich rendering and missing-library
fallback, source preservation, heading boundaries and prior review safeguards.
Local Campus/Kinmail reference tests skip explicitly when those private/local
documents are unavailable; portable generated DOCX fixtures remain tested.

From the repository root in Windows PowerShell, using the existing environment:

```powershell
Set-Location 'D:\Research\J26-SE-331-BDD-QA-Framework'
.\packages\c1-requirement-quality\.venv\Scripts\Activate.ps1
c1
```

`c1 demo` opens the same welcome menu. Activation is optional when calling the executable directly:

```powershell
.\packages\c1-requirement-quality\.venv\Scripts\c1.exe demo
```

For a new checkout without an environment (Python 3.12 required):

```powershell
py -3.12 -m venv packages/c1-requirement-quality/.venv
.\packages\c1-requirement-quality\.venv\Scripts\python.exe -m pip install -e './packages/c1-requirement-quality[dev]'
.\packages\c1-requirement-quality\.venv\Scripts\c1.exe
```

No additional wizard dependencies are required. Run from the same directory each time: sessions are discovered under that directory's `.c1-sessions`. No run names, registry files or workflow paths need to be entered. The existing advanced `run`, `refine`, diagnostic, candidate and argument-based `demo` commands remain available. For an existing advanced session, retain `c1 demo --resume <workspace>`.

## Screen demonstration

```text
C1 - Requirement Quality and Refinement
Review SRS quality, clarify missing facts and prepare requirements for BDD.
  1. Start new SRS analysis
  2. Resume previous session
  3. View previous results
  4. Help
  5. Exit
Choose a number (or help): 1

Choose your SRS document
  1. Browse files (optional Windows dialog)
  2. Paste an SRS file path
  3. Use bundled sample SRS
  4. Back
Choose a number (or help): 3

Optional AI diagnostics: skipped. No cloud requests, local inference or model downloads.
Document reading and requirement extraction...
Quality checks...
Consistency analysis...
Grounding...
Tier classification...

Step 1 - Analysis summary
...
Step 2 - Tier-based review: requirement 1 of 3
...
Recommended next step: Review unresolved consistency comparisons
  1. Review unresolved consistency comparisons
  2. Next / Skip for now
  3. Previous
  4. Details
  5. No rewrite needed - accept original
  6. Individual sections
  7. Back to session
  8. Pause
```

After import or resume, the guided sequence opens automatically. It shows the analysis summary, derives the next action from the current authoritative requirement/workflow state, and rereads that state after actions. There is no second persisted navigation state machine. Session controls also provide Continue guided workflow / Individual sections / Save and return to welcome. Type `help` or `pause` at a menu, or Ctrl+C anywhere to pause.

Choose quality review for Next / Previous / Details / Help / Back. Next on the last requirement finishes the review. Clarifications display one validation-unresolved question at a time, including invalid saved answers and deferred/waived closures. Enter answer opens labelled text input, followed by Save answer / Back, reviewer attribution and an explicit `yes` confirmation. Declining confirmation stays on that question. Invalid saved answers remain visible and correctable. Skipping leaves the question unresolved. An optional exact source span binds a replacement fact using the existing policy.

Candidate review opens previously registered candidates without regeneration, evaluating them against the current snapshot using existing services. If none are registered, the user can explicitly generate deterministic suggestions, enter a manual rewrite or go back. Each candidate displays original text, rewrite, current checks and blockers; technical findings are under Details. Select / Edit / Reject / Skip / Back are explicit choices. A publication returns to the guided sequence for current-state reclassification and exact-text approval. Rejected candidates are displayed but cannot be silently reconsidered. Approval remains a separate, explicitly confirmed action bound to the displayed selected candidate.

Tier 1 offers suggestions or explicit `No rewrite needed - accept original`, mapped to the existing `not_required` decision and revalidated. Tier 2 with unresolved registered questions opens clarification input; clean, grounded requirements blocked only by peer uncertainty open consistency review without invented questions. Other quality/evidence issues without registered questions lead to manual rewriting. Tier 3 shows conflict/escalation guidance and accepts a manual replacement obligation as explicitly attributed human evidence, never as original SRS evidence or automatic approval. Existing unanswered questions remain independent blockers. Accepting a selected candidate while escalation is active requires an explicit resolution statement through `resolve_escalation`, followed by full existing revalidation. Confirmed conflicts cannot be dismissed by that statement.

Consistency review filters to comparisons still unresolved or conflicting under the existing effective policy. After one individually confirmed review, Continue advances to the next comparison; re-entry derives the remaining comparisons from the snapshot. It requires an explicit decision, evidence, scope, conditions, rationale, reviewer, coverage and confirmation. The effective Stage 4D.2 service validates and publishes each decision. There is no bulk approval or preselected non-applicability. Raw findings remain available; stale reviews cannot clear blockers. Skipped, unresolved or partially reviewed comparisons can appear again on a later visit.

Final review counts total requirements, each tier, defects, unanswered questions, invalid/otherwise unresolved answers or closures, total pending clarifications, requirements with consistency blockers, approved/edited requirements, originals explicitly accepted without rewriting and BDD-ready requirements. It explains blocked rows individually. At the end of the guided pass it offers the existing verified JSON export path. Skipping is navigation only and never an approval or clearance.

## Stage 4E.3 example journey

For a one-requirement SRS containing `The system shall wait for [timeout].`:

```text
Step 1 - Analysis summary
Unanswered questions: 1
Pending clarifications: 1
Step 2 - Tier-based review: requirement 1 of 1
Recommended next step: Answer unresolved clarification questions
Question: What value or rule should replace [timeout]?
Your answer: 2 seconds
Exact original placeholder or span replaced: [timeout]
Answer preview: 2 seconds
Your name or reviewer label: Reviewer
Record this change? Type yes to confirm: yes
Step 3 - Reclassification from the current verified snapshot
Recommended next step: Review safe suggestions / registered candidates
No registered candidates
  1. Generate offline suggestions
Candidate rewrite: The system shall wait for 2 seconds.
  1. Select candidate
Record this change? Type yes to confirm: yes
Step 3 - Reclassification from the current verified snapshot
Recommended next step: Review selected candidate and explicitly approve
Exact selected candidate text: The system shall wait for 2 seconds.
  1. Approve selected candidate
Exact text to approve: The system shall wait for 2 seconds.
Record this change? Type yes to confirm: yes
Step 4 - Final summary (skipped requirements remain blocked)
BDD-ready requirements: 1
Step 5 - Existing JSON export
```

This outcome assumes the single-requirement example's other existing gates pass. A multi-requirement document may still require individually evidenced consistency reviews. Session pause/resume never replays a pending operation automatically.

## Supported documents

- `.txt`: UTF-8 plain text.
- `.md` / `.markdown`: Markdown requirements.
- `.docx`: Word OOXML, using the implemented DOCX loader (not legacy `.doc`).
- `.pdf`: PDFs with extractable text. Scanned image-only PDFs require OCR outside C1; OCR is not implemented.
- `.json`: the existing structured requirement formats: requirement objects, object lists, a `requirements` list or `sections` containing requirements. Requirement text fields include `text`, `original_text`, `statement` and `description`. Arbitrary JSON is not automatically an SRS.

The wizard checks extension, file existence, nonempty content and read access. The existing ingestion service then validates/parses content; malformed documents, documents with no extracted requirements and parser/dependency failures are reported without overwriting another session. Other extensions are rejected even though the advanced ingestion dispatcher has a permissive text fallback.

## Recovery and terminal compatibility

Numbered line input is the primary interface on PowerShell and other terminals. No ANSI cursor handling or rich-terminal library is required. Redirected input uses the same text menus, announces text-menu mode, and exits safely at EOF. Ctrl+C pauses. File-dialog cancellation saves nothing; unavailable Tk/native dialogs return to file selection with paste-path guidance.

Session paths use full random UUIDs; session creation refuses an existing workspace. Each session has a private registry. Review publications use the existing journal, lock, immutable snapshots and source/contract checks. Interrupted operations require explicit adoption of verified published output or cancellation; they never replay automatically. Failed initial analysis remains preserved, with a message to start fresh if no initial artifact was published.

## Stage 4F / final live demonstration

HTML reporting is unavailable. Stage 4F must attach a renderer to verified `validated_requirements.json` plus workflow and consistency diagnostics. No HTML artifact or renderer is claimed here.

AI diagnostics are intentionally skipped; there are no Groq calls, local model inference, downloads or DeBERTa NLI in the wizard. Saved diagnostic/proposal inspection remains in the advanced guided CLI. Real AI diagnostics and cloud candidate generation are outside this stage. Native Windows dialog appearance needs a manual desktop smoke check; automated tests cover dialog failure and text fallback.

Consistency, tier and BDD-readiness policies and frozen schemas are reused unchanged. No ACL/ownership operations or Git staging, commits, pushes, stashes or branch changes are part of this stage. Pre-existing working-tree changes and outputs are preserved.

## Verification

```powershell
.\packages\c1-requirement-quality\.venv\Scripts\python.exe -m pytest packages/c1-requirement-quality/tests -q -p no:cacheprovider
```

The cache plugin is disabled to avoid the existing unwritable pytest cache; permissions are not altered. Wizard tests prohibit network connections and local NLI construction. They exercise first launch, navigation, source validation/dialog fallback, safe unique creation, resume, explicit answer confirmation, all candidate choices, effective consistency evidence validation, cancellation/EOF/Ctrl+C, pending recovery, verified exports, sample journeys and advanced command compatibility.

Stage 4E verification result: **661 passed in 77.38 seconds**, including **21 wizard tests**. Both installed entry points (`c1` and `c1 demo`) were also smoke-tested with redirected PowerShell input. The scoped tracked-file whitespace check passed; the repository-wide check additionally reported a pre-existing blank line at EOF in `bdd_readiness.py`, which this stage did not modify.

Stage 4E.3 verification: **673 full-suite tests passed in 73.82 seconds**. Follow-up focused regression covering wizard, demo sessions, validation lifecycle, effective consistency and CLI: **124 passed in 31.53 seconds**. After the final single-requirement blocker-display correction, **33 wizard tests passed in 10.03 seconds**. These counts overlap. Final runs had zero failures. Tests prohibit real network/Groq calls and DistilBERT, MiniLM and NLI loading in the wizard. Added journeys cover approval text, invalid-answer correction and cancellation, navigation boundaries, all three tiers, consistency-only routing, no-rewrite acceptance, manual rewriting without generated candidates, escalation resolution, persisted candidate inspection, next-pair continuation, pause/resume, and full answer-to-approval-to-export flow.

Stage 4E.3 changes are confined to `wizard.py`, `tests/test_wizard.py` and this guide. Existing refinement, consistency, tier, readiness, session and contract services remain unchanged. Groq multi-candidate generation, live model execution, readable SRS/HTML output and automatic C2 execution remain outside this stage.
