# Phase 1B.1 — Stable Requirement Identity and Source Integrity

Implemented scope: document-scoped identity, local original-source integrity,
DOCX/PDF provenance repair, and validated state publication. No Phase 1B.2–1B.4,
ML integration, LLM implementation, shared contract changes, or architecture
redesign was performed.

## Root causes and resulting behavior

| Root cause | Before | After |
|---|---|---|
| Registry changed key format depending on global duplicate presence | Adding A in another section replaced unchanged A/B IDs 001/002 with 003/004 | Every occurrence always uses the same encoded section-hierarchy/text key; unchanged A/B keep 001/002, new A receives 003 |
| One project-wide active set | Processing document B retired document A's IDs | Active sets are keyed by logical document identity; project allocation remains global and retired IDs are never reused |
| Filename-only source identification | Same-name edited source could supply evidence for an earlier run | Original bytes, archive, normalized representation and input artifact must match their manifest SHA256 values |
| DOCX continuation paragraphs skipped by raw-text collection | Extracted obligation included “within 2 seconds”, grounding text omitted it | Normalized grounding keeps the complete obligation; original paragraphs and styles are separately preserved |
| PDF continuation advanced the source coordinate | Source line pointed at the continuation endpoint | Source line is captured before continuation collection; physical page is preserved |
| Registry saved before pipeline completion | Later analysis/output failure could advance state | Assignments remain in memory; staged artifacts are validated and published before the registry is atomically committed |

An occurrence is the exact text within its logical section hierarchy. Source
number, line and physical page are deliberately excluded from identity so
insertion, renumbering and page movement do not renumber unchanged requirements.
Identical text in different section hierarchies gets different IDs. Identical
text in the same hierarchy is rejected as indistinguishable, rather than given
positional IDs that could silently swap. Changing text or hierarchy creates a
new occurrence identity; existing retired IDs remain retired.

Default document identity derives from the resolved source location, separately
from the content hash identifying a source version. Use the same explicit
`--document-id` on every version to preserve continuity across renames/moves.
Identically named files at distinct locations are separate documents. An
explicit ID deliberately declares files to be versions of the same document.

## Files modified or added for this phase

Paths below are relative to `packages/c1-requirement-quality/`. The working tree
already contained Phase 1A.1 changes; those were retained.

| File | Reason |
|---|---|
| `src/c1_requirement_quality/requirement_registry.py` | Versioned document active sets, invariant section/text keys, explicit read-only legacy compatibility/export, deferred assignment, publication lock and stale-snapshot protection |
| `src/c1_requirement_quality/source_integrity.py` (new) | Original byte snapshot, SHA256 manifest, full normalized NIR persistence, artifact binding, source verification and refinement bundle copying |
| `src/c1_requirement_quality/cli.py` | Explicit registry selection, optional document ID, archive-relative existing contract path, staged output validation/publication, commit registry last, refinement source verification |
| `src/c1_requirement_quality/ingest/models.py` | Internal `source_blocks` metadata for original physical paragraph/page/table information; no shared schema changes |
| `src/c1_requirement_quality/ingest/docx_loader.py` | Complete continuation grounding text, original paragraph blocks/styles, section hierarchy for tables, document-order normalized text and prevention of merging across tables |
| `src/c1_requirement_quality/ingest/pdf_loader.py` | Requirement start-line retention and original per-page extracted text; physical page coordinates preserved |
| `src/c1_requirement_quality/rewrite_generator.py` | Verify existing generation input/source bundle before evidence use; exclusive publication of existing deterministic candidate sidecar. No generator strategy, ML or LLM changes |
| `tests/test_phase1b_identity.py` (new) | 29 executed regression cases covering identity, integrity, provenance, migration compatibility and failure/publication behavior |
| `tests/conftest.py` (new) | Integrity-aware setup for existing hand-authored artifact tests |
| `tests/test_cli.py` | Update expected existing `source_document.path` to its run-relative archive location |
| `tests/test_refinement.py` | Supply a real integrity bundle for the existing hand-authored refinement CLI test |
| `tests/test_rewrite_generator.py` | Supply integrity bundles for the three existing hand-authored candidate CLI tests |
| `README.md` | Document CLI, registry ownership/migration boundary, identity policy, source bundles and publication/legacy behavior |
| `docs/phase1b1-implementation.md` (new) | This implementation report |

No source edits were made to `refinement.py`, `bdd_readiness.py`,
`tier_classifier.py`, the ML modules or RAG algorithms during this phase.
Those files may still appear in git status due to earlier user changes.

## Internal artifacts and CLI behavior

Each new C1 run contains:

```text
c1/validated_requirements.json
c1/internal/source/<original-filename>
c1/internal/normalized_ingestion.json
c1/internal/source_manifest.json
```

The manifest records logical document ID, original filename, source byte SHA256,
format, original resolved location, relative archive/NIR paths, normalized-data
SHA256, and contract-artifact SHA256. Source/NIR/manifest files are marked
read-only. Complete NIR requirements, context, uncertain items, sections,
tables, warnings and supported physical source blocks are preserved. DOCX
physical pages remain unknown; no page numbers are invented.

Only the already-supported shared `source_document.path` field changes value:
it now points to the source archive relative to the run folder. No internal
manifest fields enter the frozen C1-to-C2 contract.

```powershell
c1 run --srs <file> --out <fresh-run> --run-id <RUN-ID> --registry <explicit-new-registry.json> --document-id <logical-SRS-ID>
c1 refine --in <run>/c1/validated_requirements.json --srs <byte-identical-source> --actions <actions.json> --out <fresh-refined-run>
c1 generate-candidates --in <run>/c1/validated_requirements.json --srs <byte-identical-source> --out <new-candidate-sidecar.json>
```

No implicit default registry is selected. Existing `c1` output directories are
never overwritten; other component folders in an existing run parent can remain.
Refinement retains the original byte/NIR bundle in its new run. A renamed source
with identical bytes is accepted for refinement/generation. Changed bytes with
the same filename are rejected. Legacy artifacts without an integrity bundle
fail closed and need an explicitly verified new processing run; their hashes
are never inferred after the fact.

Analysis, serialization and schema validation complete in a sibling staging
directory. A short exclusive registry lock checks that the loaded registry
bytes have not changed. Artifacts are then renamed into the final C1 directory,
and the registry is committed last using a uniquely named temporary file,
flush/fsync and atomic replacement. On registry commit failure, the C1 directory
is moved back into staging. Failed files are retained for inspection, and only
the transient lock created by the invocation is removed. Candidate publication
uses an exclusive hard link from a complete temporary sidecar and refuses an
existing destination.

## Regression tests and exact validation results

The new test module executes 29 cases:

- Duplicate added in another section preserves existing IDs.
- CLI insertion, renumbering and reordering preserve unchanged IDs.
- Separate documents sharing a registry retain independent active sets (API
  and CLI tests).
- Same basename at different locations has distinct document identity.
- Explicit document identity survives a source move.
- Indistinguishable duplicate rejection preserves registry bytes.
- Legacy read-only compatibility and explicitly mapped export preserve IDs,
  retired history and allocation high-water mark.
- Missing explicit registry / implicit legacy mutation is rejected.
- Original SHA256, source bytes, complete normalized representation and frozen
  contract fields are preserved.
- Same-name changed source is rejected for refinement and generation (two cases).
- Renamed identical source is accepted; refinement carries the original bundle.
- Corrupted archive, normalized representation and artifact are rejected (three
  cases).
- Manifest-free legacy artifact has no filename-only fallback.
- DOCX continuation grounding and physical paragraphs are preserved.
- DOCX table order/section hierarchy and paragraph boundary are preserved.
- PDF continuation start line and physical page are correct.
- Existing registry survives analysis, validation and commit failures (three
  cases), and failed staging is retained.
- Stale concurrent registry writer cannot overwrite newer history.
- Existing run cannot be overwritten.
- Failed first run creates no registry state.
- Source alteration during processing is rejected before registry commit.
- Artifact-publication rename failure preserves registry state.
- Actual registry atomic-replacement failure preserves original bytes and
  retains the pending registry for inspection.

Full suite command (from repository root, existing Python 3.12 virtualenv):

```powershell
packages/c1-requirement-quality/.venv/Scripts/python.exe -m pytest packages/c1-requirement-quality/tests -p no:cacheprovider --basetemp <verification-directory>/pytest-final -q
```

Exact result: **285 passed in 20.32s**, no failures or skips reported.
Environment: `PYTHONDONTWRITEBYTECODE=1`, `HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1`. The existing local-model smoke test ran; nothing was
downloaded or trained. Initial full check before the five additional publication
edge cases: **280 passed in 20.66s**.

Shared validator command:

```powershell
node packages/contracts/scripts/validate.mjs <54-generated-output-folders> packages/contracts/fixtures/golden/example-registration
```

Result: **exit code 0**, **“All contract checks passed.”** C1-only output folders
skip absent downstream artifacts as designed; the golden fixture also validates
the existing cross-component links. This is frozen schema compatibility, not a
claim that C2's skeleton executes a production pipeline. Failed staging folders
were excluded. `git diff --check` passed (existing CRLF normalization notices
only).

Verification outputs, test-created documents/registries and exact logs are
isolated under:

```text
C:/Users/HP/AppData/Local/Temp/c1-phase1b1-87cccc8396044f219d48684d2718afb4/
```

Files include `pytest-first.txt`, `pytest-final.txt`, `contract-validation.txt`
and `historical-registry-hashes.json`. No benchmark corpus or existing run
artifacts were deleted or altered.

## Registry migration status

**No historical migration was executed.**

| Historical registry | Observed state | Final status |
|---|---|---|
| Root `.c1-state/requirement-registry.json` | next=81, active REQ-EX-080, 79 retired IDs | SHA256 unchanged |
| Package `.c1-state/requirement-registry.json` | next=156, active REQ-EX-155, 154 retired IDs | SHA256 unchanged |

The authoritative owner/history cannot be determined from the repository.
Before production migration, the team must identify the authoritative history,
the logical document(s) its active entries belong to, reviewed section/text
bindings and a new destination. `export_legacy` requires a mapping for every
active legacy key and writes only a new file. It never guesses context from
legacy `context::text` strings or merges the conflicting histories. For CLI
bindings, encode the NIR section hierarchy with `json.dumps(hierarchy,
ensure_ascii=False)`. Only isolated test registries were migrated to demonstrate
compatibility. Production state remains untouched pending that decision.

## Remaining limitations and deferred work

- Default document identity is location-derived. Renames/moves require consistent
  explicit document IDs. IDs are stable for exact text in the same hierarchy;
  semantic edits or hierarchy changes are new identities.
- Indistinguishable occurrences in the same hierarchy are deliberately rejected.
  Stable occurrence numbering for such cases would require another reviewed
  identity policy.
- Read-only files and hashes protect against accidental changes, not coordinated
  replacement of a manifest and all its artifacts. The bundle is a local trust
  boundary, not a signed attestation.
- Cross-file crash atomicity is not claimed. A process crash between artifact
  rename and registry commit can leave a validated but uncommitted run directory;
  registry state remains unadvanced. Crash leftovers/locks need manual review.
  Failed staging and temporary files are retained, not automatically recovered.
- Source input can be edited after any completed verification; the immutable
  archived snapshot remains the source used for that run. Processing verifies
  original bytes again before normal publication.
- DOCX physical page boundaries remain unavailable. PDF line coordinates refer
  to extracted page text; scanned/OCR support is not introduced.
- Question/answer continuity, post-approval tier/readiness semantics, stale
  validation on decision reversal, performance optimization, refined SRS export,
  ML integration and LLM rewriting remain outside this phase.

No shared schemas, C2/C3/C4 source, datasets, dependencies, model checkpoints,
cloud infrastructure or SQLite were changed. No commits, pushes, resets,
branch changes, model downloads/training or deletion of existing registries or
artifacts occurred. The ten-stage research architecture remains intact.

Implementation stops here at **Phase 1B.1**. Phase 1B.2 awaits separate approval.
