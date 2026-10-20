# Final C1 development verification — 20 October 2026

**Subsequent provider correction:** the user's intended Qwen provider is the existing Groq API configuration, not the generic Ollama variables. The newest real CLI test with updated credentials and application HTTP headers succeeded with HTTP 200 and generated one candidate, which independent checks rejected. See [Real Qwen CLI integration](qwen-real-cli-integration-20261020.md); it supersedes this report's earlier provider/availability interpretation and the intermediate 403-only result. Other development/publication results below remain the record of that earlier demonstration.

Status: **PARTIAL PASS**. Actual local classifiers and retrieval ran on synthetic documents. The configured generative Qwen endpoint is unavailable. This is a technical integration demonstration, not research evaluation on genuine project data.

Branch: `c1/feat/rag-grounding`; last committed baseline: `b5a7746`. Existing uncommitted M3 fixes and artifacts were retained. Nothing was staged, committed or pushed. C2, shared contracts, model assets and the original CampusCare document were not edited.

## Changes and confirmed defects

1. The RAG verifier compared `FR-01 The system shall ...` with `The system shall ...` literally. A narrow leading-label normalization now applies to known FR/NFR/REQ document-label formats only when followed by an explicit obligation. It affects comparison tokens, not quotations, source IDs, retrieval results, offsets or source hashes. Numeric values, negation, actors, predicates, entities and conditions remain significant. Numeric evidence parsing uses the same normalization. Exact labelled evidence can now support the original obligation; different obligations remain uncertain, and applicable contradiction takes precedence over support.
2. Candidate verification's symbolic/applicability policy versions were updated. Old receipts are not silently reinterpreted under changed semantics; the new demonstrations use fresh source-bound sessions and receipts. Existing M3 artifacts remain untouched.
3. Clarification generation previously covered explicit placeholders only. Added opt-in `generate-review-questions --session ... [--requirement-id ...]` and an offline wizard option for neutral questions derived from existing quality findings. The operation records system provenance, never answers or approvals; repeated invocation does not duplicate questions. Existing placeholder behavior and decision gates remain unchanged.
4. M3 source-label exports and Windows-safe evidence staging are preserved, including their regression tests. No broad refactoring, provider substitution, contract changes or relaxed verification rules were introduced.

## Models and configuration

| Model/component | Actual execution | Limits |
| --- | --- | --- |
| Fine-tuned DistilBERT requirement-defect checkpoint | CPU inference on all 25 CampusCare items and the one-item synthetic fixture; authenticated Experiment 2 asset identity | Independent sigmoid scores only; no approved cutoff/calibration found |
| `sentence-transformers/all-MiniLM-L6-v2` | Actual dense embedding/retrieval in both sessions and candidate-specific receipt creation | Similarity locates passages; it does not establish factual support |
| `cross-encoder/nli-deberta-v3-small` | Actual NLI during CampusCare grounding | Raw labels remain advisory where applicability is uncertain; exact fixture passages are settled symbolically |
| Local `qwen2.5-coder:7b-instruct` | **Not executed** | Configured `http://localhost:11434/v1/models` refuses connections with WinError 10061; `ollama` not on PATH and no manifests found in the standard user model location |
| Groq backend | **Not invoked** | Existing opt-in cloud backend retained; no automatic cloud substitution |
| Candidate generation | Explicit deterministic baseline | No deterministic result is described as generative LLM inference |

The local endpoint and configured model were read from C1 `.env` with process-environment precedence; no secret values were logged. No model download or weight modification was attempted. No new provider or dependency was introduced. The current CLI backend choices are deterministic and Groq; the local endpoint variables do not establish a working local generator adapter. Since the configured endpoint is unavailable, no live local adapter was added or claimed verified. The user's specified unavailable-Qwen path was followed: deterministic generation continued explicitly, without cloud substitution. Actual local generative integration remains unfinished.

The checkpoint documentation and adapter describe an experimental 36-record, provisional AI-assisted training set. Neither metadata nor an approved held-out calibration procedure establishes a validated operating threshold. Raw scores are retained with `threshold: null`, advisory status and no decision effect. Validation requires independently labelled, representative held-out requirements, per-label threshold selection/calibration and a separate untouched evaluation set. No accuracy, confidence calibration, precision, recall or F1 is invented.

## Inputs and runtime

CampusCare input: repository `test-documents/CampusCare_SRS_Test_Document.docx`, SHA-256 `203c2b8fd18db7e31beda432f3a6f7fb3aa99e8215579c39b5055023b7045805`. The document explicitly identifies itself as fictional controlled test data. It was not modified.

Separate integration fixture: `local-inference/final-c1-20261020/synthetic-structural-fixture.md` under C1. Its title explicitly identifies it as synthetic. It contains one extracted requirement without a terminal period, plus explicit supporting evidence with that period. It establishes a structural formatting refinement only, not a demonstrated substantive stakeholder-policy rewrite.

The model runs were sequential by document, and RAG resources were released before DistilBERT diagnostic inference. Memory guards were retained. Available RAM was about 4.23 GiB at readiness inspection; the fixture model session recorded 4,699,037,696 available bytes and completed in 15.81 seconds. The CampusCare mandatory-model session recorded 5,500,387,328 bytes and completed in 12.52 seconds. These are observed wall times including loading and workflow writes, not statistically controlled benchmarks. No process peak RSS or GPU benchmark was obtained. No large generative model was started.

## Functional stage coverage

| Stage | Implementation/testing and result | Processing |
| --- | --- | --- |
| Import, extraction, original IDs | PASS on actual DOCX and synthetic Markdown fixture; source archives, registry and source locations retained | Deterministic document loaders |
| Quality/smells | PASS execution: four rule findings across three CampusCare items | Deterministic; not measured recall |
| ML classification | PASS inference: 25 CampusCare score vectors plus fixture | Actual DistilBERT, no validated binary cutoff |
| Retrieval and provenance | PASS execution and source-bound receipts | Actual MiniLM; full quotes/line references retained |
| Fact verification | PASS execution; exact labelled support fixed, unknown applicability stays inconclusive | Symbolic plus actual CampusCare DeBERTa |
| Consistency analysis | PASS execution, limited coverage | Conservative deterministic pairs; natural-language policy conflicts remain unconfirmed |
| Tiers | PASS execution | Deterministic checks; CampusCare remains Tier 2 |
| Clarifications | PASS generation: three neutral questions, no invented answers | Offline quality rules; FR-09 intentionally unresolved |
| Candidate generation | PASS fixture candidate; CampusCare FR-09 abstains | Deterministic fallback; Qwen blocked |
| Independent candidate verification | PASS fixture source support and meaning preservation with candidate-specific receipt | Actual retrieval, symbolic exact support, immutable source binding |
| Human selection/approval | Actual user selected, approved and authorized fixture publication in this conversation | Reviewer identity `user`; no CampusCare approval |
| Controlled publication/export/resume | PASS: approved change published, exported and verified after restart | Existing journal and authorization path; no readiness bypass |

The core deterministic/RAG lifecycle is implemented; generative local integration remains unverified and unfinished. This table distinguishes executed technical behavior from remaining limitations. CampusCare still has 25 extracted items: 16 FR, eight NFR, and one unnumbered acceptance/review statement. The latter's inclusion needs extraction annotation before measuring quality.

CampusCare initial RAG now reports eight supported and 17 unsupported items (29 fact outcomes: eight SUPPORTED, 21 INCONCLUSIVE), compared with zero supported in the M3 mandatory-model run. This is an observed integration change, not an accuracy metric. Uncertain raw NLI contradictions from other retrieved passages still prevent support; that conservative aggregation safeguard was retained. The rule count remains four, every tier remains Tier 2 and every consistency aggregate remains `potential_conflict`. The frozen contract has no `unassessed` status, so the conservative sentinel is expected; underlying diagnostics mark skipped/unassessed comparisons. It would be incorrect to silently mark unrelated or unanalysed pairs consistent just to advance tiers.

The source contains cancellation, notification-channel and retention policy conflicts. The implemented deterministic pair detector cannot establish those cross-context natural-language contradictions. Zero confirmed contradictions is not proof that the SRS is consistent. Retrieved passages, raw NLI disagreement, inconclusive applicability and potential conflicts remain visible. This is a remaining software coverage limitation, separate from missing research labels. Model entailment and reviewer approval never independently grant BDD readiness.

## Review example and actual authorization

- Requirement: `REQ-FIXT-001`.
- Original: `The system shall record audit events`
- Explicit source evidence: `The system shall record audit events.`
- Problem addressed: missing terminal punctuation; no semantic smell or new fact is claimed.
- Candidate: `The system shall record audit events.`
- Generator: deterministic `terminal_punctuation` strategy.
- Verification: source support, preserved actor/action/object/modality, no added facts, candidate-specific evidence registration, independent quality/consistency/readiness checks.
- Actual user response: **“Select, approve, and authorize publication.”** Recorded as reviewer `user`, restricted to this requirement/candidate. This is not an automated regression reviewer fixture.
- CampusCare FR-09 remains the original notification statement containing `quickly`; no deadline was supplied or published. Its open question asks for a stakeholder-defined verifiable criterion. No answer was fabricated.

The fixture is deliberately small: its correct consistency policy is the existing single-requirement/no-peer exception, not an assertion that a general multi-requirement SRS has no conflicts. Publication still requires all other checks and valid human authorization.

Actual publication completed successfully: one approved requirement, one BDD-ready requirement, zero unresolved fixture requirements, and a new journal-bound snapshot. Selection, approval, publication, export and restart verification took 60.04 seconds. `publication-result.json` contains the full published row, snapshot path and approval-intent SHA-256. `export-validation.json` confirms that the approved sentence appears under the correct DOCX requirement heading, the approval reference matches that requirement, all CampusCare source labels/text remain intact, FR-09 is unanswered, and neither original CampusCare bytes nor checkpoint identity changed.

## Outputs and reproduction

Evidence root relative to C1: `local-inference/final-c1-20261020/`. This directory is ignored by Git and must be copied separately when sharing the report.

| Artifact | Relative path beneath evidence root |
| --- | --- |
| Model workflow and timing results | `demonstration.json`, `demonstration.log` |
| Local generator availability | `generator-readiness.json`, `probe_generator.py` |
| Mandatory CampusCare snapshot and provenance | `campus/initial/c1/` |
| CampusCare ML sidecar | `campus/sidecars/initial-defect-predictions.json` |
| CampusCare final unresolved DOCX | `campus-final-export/refined_srs.docx` |
| CampusCare quality/traceability | `campus-final-export/quality_report.json`, `quality_report.md` |
| Clarification generation | `questions.log`, CampusCare review journal |
| Fixture initial snapshot and model sidecar | `fixture/initial/c1/`, `fixture/sidecars/` |
| Fixture candidate-specific evidence and approval journal | `fixture/candidate_evidence/`, `fixture/events/` |
| Fixture approved DOCX/reports | `fixture-approved-export/refined_srs.docx`, `quality_report.json`, `quality_report.md` |
| Actual publication and restart result | `publication-result.json`, `publication.log` |
| Full C1 regression | `pytest.log`, `pytest.xml` |

From the repository root, offline model settings are:

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$py='packages/c1-requirement-quality/.venv/Scripts/python.exe'
$cli='packages/c1-requirement-quality/.venv/Scripts/c1.exe'
$evidence='packages/c1-requirement-quality/local-inference/final-c1-20261020'
& $py "$evidence/probe_generator.py"
# demonstrate.py creates fresh sessions; choose a fresh evidence directory before repeating.
& $py "$evidence/demonstrate.py"
& $cli generate-review-questions --session "$evidence/campus"
& $cli demo --resume "$evidence/campus" --wizard
& $cli export-refined --session "$evidence/campus" --out "$evidence/campus-final-export"
# After explicit human selection and approval intents only:
& $cli publish-approved --session "$evidence/fixture" --reviewer user --confirm yes --requirement-id REQ-FIXT-001
& $cli export-refined --session "$evidence/fixture" --out "$evidence/fixture-approved-export"
& $py -m pytest packages/c1-requirement-quality/tests -q -p no:cacheprovider --basetemp=.pytest-tmp/finalall
```

The exact selection/approval/publication sequence used for the authorized candidate is retained in `publish_authorized_fixture.py`. It is not automatically rerun against existing state; repeated publication requires new, current approval intents. Existing output directories are never overwritten. An operator must not reuse the user's authorization for different candidates or documents.

## Remaining software limits versus research work

Software/runtime limits: local Qwen service/model unavailable; no actual generative inference claim. Conservative evidence applicability and uncertain contradiction aggregation leave 17 CampusCare items unsupported. The consistency detector cannot confirm general cross-context policy contradictions. Meaning verification currently permits only narrow structural rewrites; substantive clarification-based changes remain unproven without further evidence. Rule coverage does not detect every subjective or security/domain defect. These limitations are not resolved by arbitrary score cutoffs or automatic approvals.

External research needs: genuine SRS collection with provenance/permission; independently reviewed extraction boundaries and source IDs; ground-truth smell/classification/contradiction labels and evidence relevance judgments; authorized stakeholder clarification; representative model-validation/test splits; precision, recall, F1, semantic preservation and human acceptance studies; sufficient sample sizes and research reporting. All such metrics are **Not Evaluated** here. A successful one-item formatting refinement cannot establish substantive refinement accuracy, hallucination rate or usability.

## Git and tests

Current development changes, all inside C1:

- `src/c1_requirement_quality/rag/verifier.py`: narrow structural-label handling.
- `src/c1_requirement_quality/rag/candidate_validation.py`: explicit verification-policy version change.
- `src/c1_requirement_quality/demo_workflow.py`: opt-in neutral question generation; retained M3 short staging names.
- `src/c1_requirement_quality/cli.py`: question-generation command.
- `src/c1_requirement_quality/wizard.py`: offline question option; existing Groq/back option numbers retained.
- `src/c1_requirement_quality/refined_export.py`: retained M3 source-ID export fix.
- New `tests/test_rag_structural_labels.py` and `tests/test_review_quality_questions.py`; retained M3 `test_journal_pending_path.py` and `test_refined_export_source_ids.py`.
- This final report; the existing uncommitted M3 report was preserved.

Pre-existing untracked `models/`, root `test-documents/` and root `test-output/` remain untracked. `test-output/campuscare-01/c1/` is inaccessible in this environment; new artifacts use the accessible ignored evidence directory. No changes appear under contracts or C2. Branch remains `c1/feat/rag-grounding`; no staging/commits/pushes. `git diff --check` passes with Git's CRLF-normalization notices for two existing files.

Focused tests: 50 RAG verifier/label tests passed in 0.09 seconds, then 10 updated label/question tests passed in 0.95 seconds. These are explicitly deterministic/injected-NLI regression tests. Real DistilBERT/MiniLM/DeBERTa runs are separately recorded in the actual synthetic demonstration artifacts. The final full suite runs once after the implementation changes, including expensive publication, candidate verification, export, Windows path and recovery tests; its final count is recorded below after completion.

**Final full-suite result: 1,274 passed in 769.98 seconds (12:49), zero failed/errors/skipped/deselected/interrupted.** This was one complete post-implementation run, including the expensive ancestry test. Both retained M3 regressions and the new applicability/question regressions are included. See `local-inference/final-c1-20261020/pytest.log` and `pytest.xml`.

The fixture's actual approval-intent SHA-256 is `17c06426ce2274c233e0356454f2055b1f303daa0c700832694b39f200db0f7a`; the published snapshot is `fixture/snapshots/9041a079786140ab8784d5f93f1568ea/c1/validated_requirements.json` beneath the evidence root. Final source/receipt checks and DOCX/JSON/Markdown inspections passed. The overall result remains PARTIAL PASS because the configured local generative Qwen path is unavailable and unfinished; it is not upgraded solely because tests pass. Synthetic structural-refinement success does not complete genuine-SRS research evaluation.
