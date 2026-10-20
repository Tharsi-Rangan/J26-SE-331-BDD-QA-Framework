# M3 validation record — 20 October 2026

**PARTIAL PASS for synthetic technical testing with actual local models. BLOCKED for approved publication and genuine-SRS end-to-end validation. C1 is not declared research-complete.**

Branch `c1/feat/rag-grounding`, starting commit `b5a7746`. No staging, commit, push, model download, network request, or model asset edit was performed.

The user authorized `test-documents/CampusCare_SRS_Test_Document.docx` as a synthetic test document. Its introduction explicitly says it is fictional and created for testing, not externally collected or industry validated. SHA-256: `203c2b8fd18db7e31beda432f3a6f7fb3aa99e8215579c39b5055023b7045805`. No genuine SRS was used.

## Evidence and model readiness

Local evidence directory, relative to the repository:
`packages/c1-requirement-quality/local-inference/m3-readiness-20261020/`.
This ignored directory contains inspection scripts, `readiness.json`, `smoke.json`, `candidates.json`, `output-validation.json`, guided CLI and wizard transcripts, test logs, authenticated run/session state, and exported documents. It must be retained separately if sharing this report.

| Component | Implemented/configured | Verified in this run |
| --- | --- | --- |
| DistilBERT requirement defects | Local 267,841,796-byte checkpoint; all four Experiment 2 identity hashes and label provenance verified | Initial attempt blocked at 2.23 GiB. After RAM increased, actual scores produced for all 25 items; repeated successfully in mandatory-model session |
| MiniLM L6 v2 embeddings | Local cached snapshot `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, weights present | Actual CPU embedding/retrieval executed in probe and document workflow |
| DeBERTa v3 small NLI | Local repository cache snapshot `fa2804872c3b4bd748f38c0185cc85775361e735`, weights present | Actual CPU NLI executed in probe and document workflow |
| Qwen via local endpoint | `.env` specifies `qwen2.5-coder:7b-instruct`, localhost:11434/v1 | Endpoint not contacted; weights and availability not verified |
| Configured embedding endpoint | `.env` specifies `nomic-embed-text` | Not the MiniLM adapter used by RAG; endpoint not contacted |
| Groq Qwen | `.env` specifies `qwen/qwen3.8-27b` | Not contacted because network use was prohibited |

Python 3.12.10; installed package metadata: torch 2.14.1, transformers 5.19.0, sentence-transformers 6.1.0, spaCy 3.8.16, python-docx 1.2.0, pytest 9.1.1. Actual torch import identifies `2.14.1+cpu`. Runtime imports and the three local neural models were subsequently verified. No required Python distribution was found missing in these checks. There were no mocked inference results in either synthetic document run. No generative LLM was executed.

Available RAM initially ranged roughly 2.13–2.31 GiB and later rose above 3 GiB; no model memory guard was weakened. The retrieval probe recorded 3,881,902,080 available bytes before MiniLM and 3,472,822,272 before NLI. Hardware inventory through CIM was denied by the environment. GPU capacity and process peak RSS were not measured; a sampled RAG process working set was 1,253,969,920 bytes. Metadata inspection took 0.37 seconds; the initial scripted session/resume/export smoke took 0.83 seconds. MiniLM retrieval probe took 9.64 seconds including imports/load, NLI probe 2.19 seconds, and the mandatory-model session (RAG plus 25 DistilBERT scores) 23.25 seconds. These single runs are technical observations, not reproducible benchmark estimates.

## Executed workflow

The actual document loader and CLI extracted 25 items: 16 FR labels, eight NFR labels, and an additional unnumbered acceptance/review statement (`Paragraph-51`). Whether the latter belongs in the requirement population needs annotation; 25 is an observed count, not extraction accuracy.

Quality rules found four defects across three items: two vague, one non-measurable, one non-verifiable. All 25 items remained `TIER_2_CLARIFY`. Lexical grounding reported 24 unsupported and one supported. Deterministic consistency reported 25 `potential_conflict` statuses. The report's zero confirmed contradiction count must not be read as proof of consistency: the synthetic source explicitly contains cancellation, notification-channel and retention conflicts that this baseline did not resolve.

Executed: DOCX ingestion, source archive and registry creation, quality rules, lexical grounding, deterministic consistency, tiers, session creation, restart, guided CLI issue display, numbered wizard navigation/overview, deterministic candidate CLI and verification, and unresolved Refined SRS export. Session `generate_review_candidates()` refused the lexical-only session with `Initial-RAG review generation requires verified provenance`; the separate lexical candidate CLI produced three proposals, all rejected as unsupported. This method is intended for initial-RAG review; its rejection is not an inference success or a reason to bypass provenance.

The initial saved session contains no clarification questions. Its wizard offers external Groq suggestions, which were not invoked. Clarification answers, candidate selection and human approval were not fabricated. The active approval list is empty. Controlled publication cannot proceed without verified approval intents. Successful publication is covered only by synthetic/injected-evidence regression tests, not by this document demonstration.

After memory recovered, `probe_rag.py` executed MiniLM retrieval: FR-09's exact labelled source was top-ranked with similarity 0.9144. Its NLI probe classified the email-only/SMS hypothesis as contradiction with raw score 0.8263 (not calibrated confidence). The CLI also completed `synthetic-rag-run/`. `grounded_smoke.py` then created `grounded-session/` with `mandatory_rag=True` and `mandatory_ml=True`: authentic initial RAG provenance, 25 RAG diagnostic rows, 25 DistilBERT advisory results, restart, FR-09 deterministic grounded candidate generation, and `grounded-export/` all completed. FR-09 produced zero candidates because no justified substitution was available. Candidate generation remains deterministic; actual neural retrieval/NLI is not generative LLM inference.

The grounded report has 25 unsupported grounding statuses, four rule findings and 25 Tier 2 items. Diagnostics retain retrieved source quotes, line ranges, raw NLI labels and explicit INCONCLUSIVE applicability findings. For example, FR-01's exact labelled evidence yields raw entailment but remains inconclusive because the literal source label prevents the conservative same-obligation signature from matching. Other retrieved chunks are also uncertain. This is an observed integration limitation requiring provenance-aware handling of structural document labels, not justification to lower support thresholds or treat similarity/raw entailment as approval. No rules were weakened to make it pass.

After the Windows staging fix, `grounded-review/` was created from the same authenticated RAG snapshot. FR-23 generation and actual candidate verification completed in 14.97 seconds, recorded a `candidate_evidence_registered` journal event, and rejected “The system shall support many users without problems.” as `rag_or_meaning_ineligible`. Its evidence receipt remains available in that session's `candidate_evidence/` directory. No selection or approval followed. `grounded-review-export/` is the final post-candidate inspection export. `grounded-output-validation.json` confirms both grounded export bundles preserve IDs, source labels and original text and contain zero approvals/readiness grants.

DistilBERT returns independent sigmoid scores with no threshold set, so no binary defect predictions or calibrated confidence are claimed. For FR-09 the scores were VAGUE 0.531665, AMBIGUOUS 0.533405, INCOMPLETE 0.501523, NON_MEASURABLE 0.514470 and NON_VERIFIABLE 0.507121. The checkpoint was trained on 36 provisional AI-assisted records; identity validation and successful inference do not establish generalization.

The lexical export is `synthetic-export-final/refined_srs.docx`, with `quality_report.json` and `quality_report.md` beside it. The actual-model export is `grounded-export/refined_srs.docx` with equivalent reports including model/evidence traceability. The earlier `synthetic-export/` is a retained pre-fix export. These are unresolved inspection exports, not an approved revised baseline. All 25 original texts and C1 IDs are preserved; all source texts were found in the DOCX; source locations remain present; zero items are approved or BDD-ready. No approved-change rendering can be claimed for this run. JSON, Markdown and DOCX were opened and inspected programmatically.

## Examples and reviewer handoff

| Original label / C1 ID | Original and finding | Proposal and final state |
| --- | --- | --- |
| FR-09 / REQ-CAMP-009 | “The system shall notify students quickly when their appointment is changed.” Rules flag `quickly` as vague/non-measurable | Proposed “within 3 seconds” borrowed a search-performance target from NFR-01. Verification rejected it as unsupported. Original remains pending |
| FR-14 / REQ-CAMP-014 | “The system shall provide an easy-to-use dashboard for students and advisers.” Rule flags vague `easy` | No proposal. Original remains pending; measurable usability criteria require stakeholder input |
| NFR-02 / REQ-CAMP-018 | “The system shall be fast and reliable during busy periods.” Rule flags non-verifiable `reliable` | No proposal. Original remains pending; load, availability and performance conditions require stakeholder input |
| NFR-07 / REQ-CAMP-023 | “The system should support many users without problems.” | Modal-normalization proposal changes `should` to `shall`; rejected as unsupported. Original remains pending |

Required reviewer actions: supply an authorized notification deadline, trigger and measurement conditions for FR-09; specify usability and concurrency targets; reconcile FR-06 against BR-03, FR-11 against BR-04/interface constraints, and NFR-06 against BR-05; review the password-storage statement against institutional authentication scope. After sufficiently applicable RAG evidence is available, register and verify candidates, explicitly select or edit them, record approval with reviewer identity, then explicitly confirm publication. The user explicitly answered that FR-09 must remain unresolved; no authorized deadline was supplied.

## Confirmed development fix

The initial export retained canonical C1 IDs but omitted source `FR-*` and `NFR-*` labels. `refined_export.py` now matches the verified archived source item by original text and source coordinates and includes `source_document_item` in the report and “Original document ID” in DOCX/Markdown. Frozen contracts and authorization rules are untouched. Added a DOCX integration regression covering both labels and unresolved text preservation. The final synthetic export verifies all original source labels are present.

An actual FR-23 grounded candidate attempt also exposed a Windows path-length failure writing `reference.json.pending-<uuid>` in its hash-named evidence directory. The final reference path was 225 characters; the temporary suffix pushed it past MAX_PATH. `demo_workflow._write` now uses a destination-independent `.pending-<uuid>` filename in the same directory. Exclusive creation, fsync, hard-link publication and no-overwrite behavior remain intact. A Windows regression exercises a long reference path and verifies that a second publication cannot replace the first. Both new fix tests pass (2 tests, 0.70 seconds). The failed candidate-evidence slot is retained, not deleted or adopted as successful evidence.

## Evaluation limits

Classification precision/recall/F1, smell precision/recall/F1, extraction precision/recall, RAG relevance, hallucination rate, semantic meaning preservation, user satisfaction and refinement acceptance rate: **Not Evaluated**. No labelled ground truth, systematic relevance judgements or actual reviewer decisions were available. Actual local inference was verified, but that does not establish accuracy. The candidate sidecar's `fabrication_rate: 0.0` is an internal heuristic counter and must not be represented as measured hallucination performance; its first rejected candidate demonstrably borrows an unrelated threshold. Observed lexical outcomes: 3 deterministic proposals generated, 3 verifier rejections, 0 ranked candidates, 0 human decisions, 25 unresolved exports, 0 BDD authorizations. Grounded FR-09 generation produced zero proposals. Technical workflow completion is partial.

## Reproduction (PowerShell, repository root)

Do not reuse an existing output/session directory; choose a fresh suffix when repeating.

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$py='packages/c1-requirement-quality/.venv/Scripts/python.exe'
$cli='packages/c1-requirement-quality/.venv/Scripts/c1.exe'
$out='packages/c1-requirement-quality/local-inference/m3-repro-20261020'
$srs='test-documents/CampusCare_SRS_Test_Document.docx'
& $py packages/c1-requirement-quality/local-inference/m3-readiness-20261020/inspect_readiness.py
& $cli run --srs $srs --out "$out/run" --run-id RUN-20261020-120000-rpr1 --project-code CAMP --document-id M3-SYNTHETIC-CAMPUSCARE --registry "$out/registry.json"
& $cli diagnose-defects --in "$out/run/c1/validated_requirements.json" --out "$out/defects.json"
& $cli generate-candidates --in "$out/run/c1/validated_requirements.json" --srs $srs --out "$out/candidates.json"
& $cli demo --workspace "$out/session" --in "$out/run/c1/validated_requirements.json"
# In the guided CLI enter: issues, then pause.
& $cli demo --resume "$out/session" --wizard
# Numbered wizard: Individual sections, overview, then save/return.
& $cli export-refined --session "$out/session" --out "$out/export"
& $py -m pytest packages/c1-requirement-quality/tests/test_refined_export_source_ids.py packages/c1-requirement-quality/tests/test_controlled_publication.py -q -p no:cacheprovider --basetemp=.pytest-tmp/m3-repro-focused
& $py -m pytest packages/c1-requirement-quality/tests -q -p no:cacheprovider --basetemp=.pytest-tmp/m3-repro-full
```

The actual RAG CLI run used the `run` command with `--grounding-mode rag`, output `synthetic-rag-run`, registry `rag-registry.json`, document ID `M3-SYNTHETIC-CAMPUSCARE-RAG` and run ID `RUN-20261020-120000-rag1` beneath the evidence directory. `probe_rag.py` and `grounded_smoke.py` in that directory reproduce the actual-model probes and mandatory-model session; choose fresh session/export paths inside the latter script before repeating. DistilBERT scores are in `defects-python.json` and `grounded-session/sidecars/initial-defect-predictions.json`. `publish-approved --session <session> --reviewer <actual-reviewer> --confirm yes` is only appropriate after the reviewer has recorded valid, current approval intents; it was not executed here.

## What remains for genuine project evaluation

Obtain an actual project SRS with source/ownership and permission to use it; freeze its version and hash; annotate expected requirement boundaries, original IDs, defect labels, contradictions and relevant evidence independently; supply reviewer decisions and clarification answers; ensure at least the existing 3 GiB available RAM threshold is met before diagnostic inference (more headroom may be needed for the combined workflow); verify local inference sequentially; run the complete grounded workflow through explicit approval, controlled publication, restart and final export. Then report per-stage coverage, meaningful labelled metrics, model runtime and peak process memory, and errors on a sufficient sample. No remaining task is silently treated as complete.

## Git state and regression evidence

Development changes are limited to C1:

- Modified `src/c1_requirement_quality/refined_export.py` (source labels in inspection exports).
- Modified `src/c1_requirement_quality/demo_workflow.py` (short exclusive staging names).
- Added `tests/test_refined_export_source_ids.py`.
- Added `tests/test_journal_pending_path.py`.
- Added this validation report.

Pre-existing untracked `models/`, repository `test-documents/` and `test-output/` remain untracked. `git status` warns that `test-output/campuscare-01/c1/` is inaccessible; this run used its own accessible directory. Artifacts under `local-inference/` remain ignored. No shared contracts, C2 files or tracked model assets changed. Nothing was staged, committed or pushed. `git diff --check` passes (Git also reports its existing CRLF-to-LF normalization notice for `demo_workflow.py`).

Focused verification: 44 ingestion tests passed; 14 architecture tests passed; 23 authenticated-eligibility tests passed; the combined source-ID/publication/export suite passed 27 tests in 323.02 seconds; both final fix regressions passed in 0.70 seconds. Publication regression tests use explicitly injected synthetic evidence and scripted reviewer fixtures and do not establish that a real reviewer approved this SRS.

The first broad run used an overly long temporary directory, causing Windows MAX_PATH failures unrelated to model inference. A shortened-path retry was interrupted while expensive publication ancestry tests were executing. Those publication tests subsequently passed in the focused run. A broad remainder run excludes only `test_second_generation_publication_reverifies_ancestry`, which passed in the focused suite; its final result is recorded with the test artifacts. The shorter `.pytest-tmp/` basetemp and disabled cache provider avoid unrelated existing cache permission warnings.

Final broad result: **1,262 passed, 1 deselected in 443.56 seconds** (`pytest-remainder.log`, `pytest-remainder.xml`). The single deselected ancestry test passed in the 27-test focused suite. The latest Windows-path fix is additionally covered by the final two-test regression run; the broader process had already imported the earlier journal writer before that small fix. No all-green monolithic post-fix suite is claimed. Final `git diff --check` passes. Remaining blockers are stakeholder decisions, conservative RAG applicability for labelled evidence, genuine project data/annotations, and untested local/cloud generative LLM availability.
