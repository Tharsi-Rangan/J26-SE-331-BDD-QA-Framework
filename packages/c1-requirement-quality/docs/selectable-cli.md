# C1 selectable terminal application

This interface presents the existing C1 implementation. `DemoSession`, source
verification, the existing workflow/journal, candidate receipts, validation and
controlled publication remain authoritative. It adds no replacement database,
requirement registry, classifier, tier algorithm or shared contract.

## Setup and launch

Python 3.12 is required. In the repository root:

```powershell
.\packages\c1-requirement-quality\.venv\Scripts\Activate.ps1
python -m pip install -e "./packages/c1-requirement-quality[dev,tui]"
c1
```

The optional interface uses Textual 8.x. Existing batch installations do not
import it until requested. Rich and Markdown dependencies are reused. Windows
Terminal running PowerShell is supported; headless Pilot tests exercise key
navigation and resizing. Native desktop file-dialog appearance still needs a
manual check on the user's desktop. Paste-path input remains available.

Explicit alternatives:

```powershell
c1 tui --root .c1-sessions
c1 tui --session <existing-session-directory>
```

The existing `run`, `refine`, `generate-candidates`, `propose-clarifications`,
diagnostics, publication/export and argument-based `demo` commands remain.
Redirected input retains the old text menus. No cloud request happens on launch.

## Keys and screens

| Screen | Actions |
| --- | --- |
| Dashboard | Start, resume, view previous results, help, exit |
| Document selection | Browse, paste a path, use the packaged sample, recent sessions, preview and explicit analysis confirmation |
| Analysis | Actual service-stage states and progress; a failed stage leaves later work incomplete |
| Review | Search by ID or text, navigate requirements, inspect quality, evidence, workflow blockers and current selections |
| Clarification | Select a recorded question and known source span, enter a labelled free-text answer, reviewer identity and explicit confirmation |
| Candidates | Compare registered candidates, validate evidence, select, edit or reject; inspect excluded generation history |
| Consistency | Both obligations side by side on wide terminals; stacked on narrow terminals; selectable evidence, decision, scope, conditions, coverage and explanation |
| Approval | Original, selected text, existing independent checks and approval eligibility; an explicit separate confirmation |
| Publication | Confirm publication of current active approval intents; all original integrity and readiness checks rerun |
| Export | Select DOCX, C2 JSON, quality, clarification/decision, traceability, or the complete bundle |

Use arrow keys and Enter in lists. Tab/Shift+Tab move between fields. Esc backs
out or cancels a form. Ctrl+S returns to the dashboard after the current operation
finishes. F1 opens guidance. Long lists and forms scroll. Navigation numbers are
never silently interpreted as stakeholder answers.

Confirmed actions save immediately. Unconfirmed form contents are cancelled on
exit. Reviewer labels are recorded, not authenticated identities. A generated
question, answer submission, candidate selection, approval intent and publication
remain distinct events.

## Analysis and methodology mapping

| Methodology | Existing implementation used by the interface |
| --- | --- |
| Input and extraction | `ingest/`, `source_integrity.snapshot_source`, requirement registry and `cli.run` |
| Rule findings | Existing five-label deterministic quality analyser; empty results mean no rule matched |
| Local classification | Existing verified DistilBERT adapter and saved advisory five-label scores; no unvalidated default cutoff |
| Facts and RAG | Existing rule-based fact extraction, MiniLM retrieval, symbolic checks and lazy DeBERTa NLI, with source-bound provenance |
| Consistency and tiers | Existing deterministic analyses and `human-consistency-gates-v2`; unassessed pairs remain unresolved |
| Clarification | Existing question/answer identities, exact Phase 1B.3 scaffold/span and whole-obligation validation |
| Rewriting | Existing deterministic backend or explicitly selected Groq/Qwen backend; independent candidate verification |
| Review and approval | Existing session journal, candidate receipts, explicit review intents and controlled publication |
| Final outputs | Existing frozen C1 JSON plus `refined_export` DOCX and reports |

The displayed stage order follows actual service transitions. The existing
memory-aware analysis grounds and computes initial deterministic tiers before
advisory DistilBERT classification; model scores do not alter the tier policy.
A successful stage means it executed, not that the requirement passed its checks.

The requirement view flags multiple clauses found by the existing fact extractor
for atomicity review. It does not automatically split or renumber requirements.
No new missing-actor or acceptance-criteria label policy is inferred from the
draft annotation guideline. The existing deterministic BDD element checks remain.
There is no learned BDD-readiness head or claim of comprehensive semantic defect
or contradiction detection.

## Source and human evidence

Optional `run --grounding-mode rag` diagnostics are advisory and do not declare
mandatory RAG. A dedicated provenance file, orphan mandatory hashes, missing
policies, altered source bytes or invalid ancestry cannot be treated as a legacy
workflow. Clarification policy is checked before a provider request.

New mandatory-RAG review events use `review_version: 2`. Version-1 approval
events retain their original source-only verification semantics. The source-only
candidate receipt policy is unchanged.

The approved narrow integration reuses Phase 1B.3's exact named-placeholder/span
replacement and exact whole-obligation mechanisms. It verifies the original
source and candidate-specific RAG receipt, then reconstructs separately attributed
human answers at an exact verified journal prefix. The requirement, question,
actor, answer, source and current review record are bound into the acceptance
assessment. Raw source RAG outcomes remain visible; human answers never become
original-SRS facts or change source-only receipts.

Failed/incomplete RAG execution and confirmed source contradiction cannot be
waived by an answer. Unsupported edits and stale/mismatched records fail.
Changing answers, questions, selection or peer state invalidates dependent
approval intents. Final publication reconstructs the approved basis against the
existing journal and complete ancestry. No caller-selected flag grants approval.

For a batch, finish candidate selections, answers and consistency reviews before
collecting the separate approvals. Then publish that batch. A later review edit
changes the shared review basis and requires fresh approvals; it never silently
carries earlier approval onto changed peer obligations.

Consistency adoption uses the existing complete/partial coverage and evidence
rules, now accessible in mandatory-RAG review. Audit-only records retain no gate
effect. Non-applicability is never inferred from similarity or selected in bulk.
Human-confirmed conflicts remain sticky under the documented policy; this work
does not introduce a conflict-adjudication or closure policy.

Tier 3 resolution requires explicit reviewer explanation, actual corrected
obligations and successful checks. A statement that a conflict was reviewed
cannot clear a remaining contradiction. Unresolved requirements remain pending.

## Cloud use and candidates

The existing Groq configuration and Qwen model are retained. Keys are read through
the existing backend and are never displayed. Consent precedes the model-list
availability check and content request. Only the configured model is accepted;
there is no automatic substitution or retry.

The selectable workflow requests two or three distinct model alternatives in one
bounded structured response. An explicit empty response is abstention. Missing
alternatives are never padded with invented text. Each proposal still passes
independent existing checks; fewer than two may be usable. Excluded proposals and
generation attempts remain in new sidecars and are inspectable as history, with
no selection or approval authority. The legacy backend's single-proposal method
retains its response contract for scripting compatibility.

CampusCare is local-only. The interface and workflow guards reject its known
filename/hash before transmitting requirement content, including a renamed copy
with the same bytes. This is the user-requested restriction, not a general data
loss prevention classifier for arbitrary excerpts or transformed documents.

Network errors, rate limits, missing models, timeouts and malformed output leave
review state intact. Retry is another explicit action; manual rewriting and skip
remain available. API tests use mocked transport. No live Groq verification is
implied by passing them.

## Sessions, exports and recovery

Default discovery is `<working-directory>/.c1-sessions`. Keep that working
directory, or use `c1 tui --root <directory>`. Each new analysis uses the existing
private session registry. Duplicate source-byte matches are shown before analysis;
resume the earlier session or deliberately confirm a new isolated analysis.
No historical registry is selected, merged or migrated automatically.

Preserve the session, its journal, source bundle and full run ancestry. Resume
does not replay inference, API requests or decisions. An interrupted publication
offers explicit verification/adoption of its prepared child or cancellation
while retaining files. Failed initial analysis remains incomplete; inspect the
retained failure and start a fresh session after correcting the cause.

Exports refuse existing destinations. DOCX and reports distinguish approved,
rejected and unresolved requirements. Unpublished approval intents do not replace
original text in final exports. The C2 JSON is an exact copy of the authenticated
contract; C2 must continue to process only `bdd_ready: true` rows. Reports do not
grant readiness. The handoff copy is not a portable approval/session bundle;
verification and resume use the originating journal and run family.

## Verification and supervisor demonstration

```powershell
python -m pytest packages/c1-requirement-quality/tests -q -p no:cacheprovider --basetemp <fresh-test-directory>
```

`tests/test_tui.py` uses Textual Pilot with real C1 services and explicitly
injected test models. Synthetic reviewer inputs are not genuine stakeholder
answers or user approvals. The dedicated integration tests cover confirmed
human support, stale/unsupported rejection, all three tiers, consistency,
publication and exports. Groq transport tests are mocked.

For a supervised demonstration: launch `c1`, select and preview an authorised
SRS, inspect actual stage results, review evidence and quality findings, provide
genuine answers, review consistency with both source references selected,
generate candidates, inspect every validation result, explicitly select and
approve an eligible requirement, publish, export, then resume. Show unresolved
rows separately. Do not substitute test-fixture identities or answers for the
reviewer's decisions. Live cloud use requires separate permission; CampusCare
must remain local.

Current execution results and remaining environment limits belong in the delivery
verification report, separate from this usage guide. Historical milestone logs
retain their original dates and results.
