# C1 implementation delivery and verification — 20 October 2026

The selectable application now connects the existing C1 processing and review
services through one terminal interface. The optional-RAG provenance mismatch,
mandatory-RAG human clarification/consistency integration, candidate generation,
approval and export connections have been repaired. This report distinguishes
automated integration coverage from live execution. Fresh local MiniLM and
DistilBERT processing, resume and export succeeded; a separate real DeBERTa
adapter check also succeeded. Genuine stakeholder and live-cloud acceptance
remain unverified.

## Specifications and audit findings

The implementation followed the existing package README, phase implementation
and validation audit documents, interactive/guided CLI documentation, research
methodology and consistency policy, together with the actual Python entry points,
models, grounding validators, workflow persistence, publication and tests. The
user authorised full completion and subsequently approved the narrow integration
of verified human evidence into mandatory-RAG review.

| Confirmed discrepancy | Implemented result |
| --- | --- |
| Ordinary `run --grounding-mode rag` produced advisory diagnostics which policy resolution incorrectly treated as mandatory provenance | Diagnostics alone no longer imply mandatory RAG. Dedicated provenance, mandatory hash markers, source changes and invalid ancestry remain fail-closed. Policy is resolved before clarification-provider calls. |
| Mandatory-RAG drafts could not use existing Phase 1B.3 human support rules | New version-2 review events separately bind verified human evidence to source, requirement, question, reviewer, workflow record and exact journal prefix. Existing exact scaffold/span and whole-obligation rules are reused. |
| Mandatory-RAG consistency review was disconnected from controlled publication | The same journal now records explicit reviews under the existing consistency policy, with current obligations and evidence. Publication independently reconstructs the reviewed basis. |
| The cloud generator exposed one proposal while the requested workflow needs alternatives | A separate structured multi-proposal method requests two or three genuine alternatives, or explicit abstention, in one request. Legacy single-proposal scripting remains compatible. |
| Numbered menus required technical identifiers and separate actions | Textual screens expose source preview, analysis, evidence selection, questions, comparison, approval, publication, exports and resume over existing services. |
| The DOCX bundle lacked selectable downstream/report outputs | Five selectable formats now include the authenticated C2 JSON, decision and traceability reports, while default legacy exports retain their previous files. |
| Draft annotation aspirations exceeded validated model/rule capabilities | The interface identifies existing deterministic findings and experimental classifier scores separately. No missing model capability, calibrated threshold or research metric is fabricated. |

No tier algorithm, model, defect taxonomy, frozen schema, C2 interface or
consistency-coverage methodology was replaced. Historical Markdown results retain
their original scope; current guidance is in `selectable-cli.md`.

## Implemented workflow

- Arrow/Enter navigation, Tab/Shift+Tab forms, Esc cancellation, F1 help,
  Ctrl+S return to dashboard, responsive layouts and scrollable content.
- Dashboard actions for new analysis, resume, previous results, help and exit.
- Native file-picker integration, path fallback, packaged sample and recent
  sources; supported-format checks, preview, source-byte duplicate detection and
  explicit source-hash confirmation before analysis.
- Real service-stage progress over ingestion, extraction, deterministic quality,
  RAG/consistency/tiers, advisory local classifier and session preparation.
  Failed stages remain incomplete, with retained staging and diagnostic evidence.
- Searchable requirements with original wording, IDs, source evidence, rule
  findings, advisory scores, facts, tier, unanswered questions and workflow gates.
  Atomicity guidance reuses extracted clauses without splitting or renumbering.
- Labelled clarification forms with known question/source-span selection,
  reviewer identity and explicit confirmation. No navigation input becomes an
  answer. Generated questions remain proposals until accepted.
- Existing deterministic generation and optional Groq/Qwen generation; each
  proposal receives independent source/grounding, quality, consistency and BDD
  checks. Selection, editing, rejection and approval remain separate actions.
- Candidate and generation history survives regeneration. Unsupported proposals
  are retained as excluded suggestions without approval authority.
- Consistency forms show both obligations and selectable evidence, scope,
  conditions, coverage and rationale. Unknown peers and incomplete confirmations
  are rejected by the existing services.
- Explicit escalation and resolution, with actual corrected obligations and
  successful independent checks required; remaining contradictions stay blocked.
- Approval previews expose the same eligibility predicate used by the approval
  service. Approval intents do not replace final contract text until publication.
- Controlled publication reruns source, candidate receipt, journal, ancestry,
  human-evidence, consistency and readiness checks.
- Session discovery/resume and explicit recovery of prepared publication state;
  failures and cancellation preserve existing artifacts. UI operations serialize
  through the existing session lock and reject changed review bases.
- Selectable refined DOCX, C2 JSON, quality report, clarification/decision report
  and traceability report. Existing output destinations are refused. Pending and
  rejected rows retain their original/published obligation and remain non-ready.

## Integrity and compatibility

Source-only RAG candidate receipts keep their existing policy and semantics.
Human evidence is separately attributed; it never becomes original SRS evidence.
The integration accepts only completed source-RAG assessments without confirmed
contradiction, plus the established exact human-support checks. Failed model
execution cannot be waived. Unsupported numbers or added obligations, stale
answers and mismatched state cannot gain approval. Version-1 review events retain
their historical replay rules; new review events use version 2.

Review edits invalidate dependent approval intents. Finish batch edits and
consistency review before collecting approvals and publishing. A rejected peer
proposal is assessed using that peer's published/original obligation.

CampusCare is guarded against cloud use by its known filename and exact source
hash, including a renamed byte-identical copy. No live cloud requests were made.
This guard does not claim to recognise arbitrary transformed excerpts.

The optional Textual dependency is isolated from batch command imports.
Textual 8.2.8 and its three newly installed dependencies occupy approximately
6.6 MiB of installed files; existing Rich/Markdown dependencies were reused.
`pip check` passed. No model downloads, Git commits or pushes were performed.

## Automated verification

The final complete suite passed **1,308 tests in 1,073.43 seconds (17:53)**:
zero failures, zero errors and zero skips. This includes **34 new regression
cases**, all **seven Textual Pilot tests**, and the final rejected-peer cases.
The earlier complete run passed 1,307 tests before that last regression was
added. Results are separate runs; their overlapping counts are not summed.

The final run listed every `test_*.py` file once, placing the expensive controlled
publication and new RAG integration modules first. No cases were deselected.
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` were set; no pytest cache was used.
The exact order, complete log and JUnit XML are retained. `git diff --check`
passed, with Git's existing CRLF-normalisation notices only.

The new regression files cover optional/mandatory provenance, cloud data guards,
strict multi-proposal parsing, human-supported mandatory-RAG review, stale and
unsupported changes, consistency, Tier 3 resolution, publication, all export
formats and Textual interaction. The full suite retains existing integrity,
ancestry, tamper, receipt, replay and compatibility coverage.

All provider transport is mocked in tests. Local model adapters are injected
where appropriate. Reviewer identities, answers and approvals in automated
fixtures are explicitly synthetic; they are not stakeholder evidence.

## Acceptance observations

| Check | Observed result and boundary |
| --- | --- |
| Windows launch | Launched the installed `c1.exe` in an interactive PowerShell terminal; Textual rendered the highlighted dashboard. Arrow/Enter opened Help, Esc returned, and Exit terminated with code 0. No analysis or cloud call occurred. |
| Interactive processing and review | Textual Pilot exercised actual C1 workflow services with injected offline models: import/confirmation and stage events; search; unconfirmed-answer rejection; confirmed answer; generation/comparison/selection; approval; publication; all-output export; narrow resize; save and resume. |
| Explicit consistency UI | Pilot selected evidence and recorded a confirmed, scoped review. Unconfirmed submission did not persist it. |
| Tier fixtures | Existing Tier 1 tests plus new clarified Tier 2 and corrected Tier 3 integration tests exercise controlled publication. Tier 3 resolution statements alone fail; actual verified correction is required. These are synthetic acceptance scenarios. |
| Multi-candidate backend | Mocked Groq returned two genuine response entries; each was independently validated. The supported alternative remained selectable and the unsupported alternative was rejected; generation history remained intact. No live Groq response is claimed. |
| Failure and cancellation | Pilot covered cancelled cloud consent with zero provider probes and provider failure without journal/artifact mutation. Existing tests cover publication recovery and integrity failures. |
| Fresh local inference | After RAM recovered, a fresh isolated synthetic SRS completed actual MiniLM retrieval, symbolic grounding and DistilBERT classification using installed weights. Available RAM before the successful run was 4,819,869,696 bytes. Five experimental scores were saved without a threshold or decision effect. One requirement remains pending, 0 approved and 0 BDD-ready. Resume reproduced the same artifact; all six export files were produced and the shared validator passed. No model was downloaded. |
| Local NLI | The fresh SRS had exact evidence and correctly did not invoke lazy NLI. A separate call to the existing `LocalNLI` adapter loaded `cross-encoder/nli-deberta-v3-small` locally and returned `entailment` for a synthetic must/shall pair. The existing memory guard passed before execution. This is a model-execution check, not an accuracy evaluation or approval. |
| Earlier local attempts | The first analysis was blocked before inference at the existing 3 GiB guard (1,501,265,920 bytes available). A later check-script attempt was rejected for its invalid run ID; correcting that script yielded the successful fresh run above. Both failed destinations remain retained. No application policy was changed to pass either check. |
| Existing real SRS | Read-only resume verified the saved local CampusCare session, then created a fresh export. It contains 25 requirements, 0 approved and 0 BDD-ready. This verified resume/export, not new inference or stakeholder review. Every existing session file was unchanged after the operation. |
| Downstream compatibility | The shared Node validator accepted the CampusCare export, a synthetic published UI handoff and the existing golden contract fixture. This checks contract compatibility; no C2 generation run is claimed. |
| Desktop file picker | Native picker implementation and fallback are connected. Appearance and interaction on the user's desktop remain unverified. |

Evidence is retained under repository-root `.pytest-tmp/`:

- `c1-full-20261020-5.log` and `.xml`: initial complete regression run.
- `c1-full-20261020-6.log` and `.xml`: final complete regression run, 1,308 passed.
- `c1-final-test-order-20261020.txt`: final complete-suite file order.
- `c1-final-contract-check-20261020.log`: shared validator passed for the final
  synthetic UI handoff, fresh CampusCare export and existing golden fixture.
- `c1l-a3bd21/actual-local-result.json`: actual local inference preflight failure.
- `c1-final-local-13c95d/actual-local-result.json`: rejected check-script run ID.
- `c1-final-local-629f14/actual-local-result.json`: successful fresh local
  MiniLM/DistilBERT analysis, resume and full export; the adjacent `handoff/`
  directory contains the six exported files and archived source.
- `c1-final-local-check-20261020-2.log`: successful local service-stage log.
- `c1-final-local-contract-20261020.log`: successful shared validation of that
  fresh local-model handoff.
- `c1-final-nli-097e31.json`: actual local DeBERTa adapter observation.
- `c1-existing-campus-summary-20261020.json`: read-only real-SRS observation.
- `c1-preservation-20261020.json` and `c1-preservation-final-20261020.json`:
  preservation fingerprints and final comparison.
- `c1-post-inference-preservation-20261020.json`: all nine preservation checks
  also passed after actual local model execution.

## Preserved data and boundaries

Final SHA-256 comparisons passed for the original CampusCare DOCX, both historical
requirement registries, frozen C1/common schemas and all four checked DistilBERT
assets. CampusCare's source SHA remains
`203c2b8fd18db7e31beda432f3a6f7fb3aa99e8215579c39b5055023b7045805`.
The existing CampusCare session's complete file comparison also passed.
Changes are confined to this C1 package; C2/C3/C4 and shared contract files are
unchanged. All verification outputs use fresh isolated destinations.

## Exact changed files

Paths below are relative to `packages/c1-requirement-quality/`.

Modified:

```text
README.md
docs/guided-cli.md
docs/interactive-wizard.md
pyproject.toml
src/c1_requirement_quality/clarification_proposals.py
src/c1_requirement_quality/cli.py
src/c1_requirement_quality/demo_workflow.py
src/c1_requirement_quality/groq_generator.py
src/c1_requirement_quality/rag/publication.py
src/c1_requirement_quality/refined_export.py
src/c1_requirement_quality/rewrite_generator.py
src/c1_requirement_quality/source_integrity.py
src/c1_requirement_quality/validation_lifecycle.py
src/c1_requirement_quality/wizard.py
```

Added:

```text
docs/c1-completion-verification-20261020.md
docs/selectable-cli.md
src/c1_requirement_quality/rag/review_evidence.py
src/c1_requirement_quality/tui.py
src/c1_requirement_quality/tui.tcss
tests/test_groq_multiple.py
tests/test_optional_rag_provenance.py
tests/test_rag_review_integration.py
tests/test_tui.py
```

## Launch and demonstration

From the repository root in PowerShell:

```powershell
.\packages\c1-requirement-quality\.venv\Scripts\c1.exe
```

Select Start, preview an authorised SRS, confirm analysis, and inspect the actual
results. Provide genuine answers and scoped consistency decisions. Compare and
validate candidates, select each proposed final text, complete batch edits, then
approve eligible requirements separately. Publish before exporting approved
text. Save/resume and inspect unresolved rows rather than presenting them as
complete. See `selectable-cli.md` for setup, keys and the methodology mapping.

Rendered terminal previews use an explicitly synthetic lexical input; no
inference, stakeholder approval or CampusCare content is represented:

- [Dashboard](../../../.pytest-tmp/c1-final-preview-363092/dashboard.svg)
- [Document preview](../../../.pytest-tmp/c1-final-preview-363092/document-preview.svg)
- [Requirement review](../../../.pytest-tmp/c1-final-preview-363092/requirement-review.svg)
- [Candidate comparison](../../../.pytest-tmp/c1-final-preview-363092/candidate-comparison.svg)
- [Approval preview](../../../.pytest-tmp/c1-final-preview-363092/approval-preview.svg)
- [Export choices](../../../.pytest-tmp/c1-final-preview-363092/export.svg)

These local preview and verification artifacts live under `.pytest-tmp/` and are
not version-controlled documentation assets. Keep them if they are needed for
the supervisor demonstration.

## Remaining limits

- Full genuine-stakeholder acceptance remains outstanding; no real reviewer
  supplied answers or approval during this task. Live Groq availability/generation
  was not run under the user's restriction. The successful fresh local-model
  analysis uses a synthetic SRS, separately from the saved real CampusCare check.
- The existing 3 GiB available-memory guard remains. The initial failure and later
  success show that local inference depends on RAM available at execution time.
- DistilBERT remains experimental advisory five-label classification. There is
  no learned BDD-readiness head, approved new confidence threshold or new measured
  model-performance claim. Existing deterministic checks remain authoritative.
- Exact grounding intentionally rejects unsupported paraphrases. Two or three
  provider proposals may yield fewer usable candidates or complete abstention.
- Human-confirmed consistency conflicts remain sticky under existing policy;
  no new adjudication or automatic conflict-closing policy was introduced.
- Deep ancestry verification can be slow. Integrity replay was preserved;
  the interface does not promise a fixed completion time.
- DOCX export is a readable refined requirements/report document, not a
  format-preserving editor for the entire original SRS.
- Preserve the source session and complete run ancestry. The copied C2 contract
  is a handoff artifact, not a portable approval-evidence/session bundle.
- Reviewer labels establish attribution, not authenticated identity.

The remaining live acceptance checks require an adequately provisioned local
environment and real reviewer participation. They must not be replaced by
synthetic answers or a claim that unit-test success proves full research
validation.
