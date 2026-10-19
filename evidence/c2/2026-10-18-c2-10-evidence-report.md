# C2-10 Evidence Report

## Task and scope

- **Task ID:** C2-10
- **Objective:** Preserve evidence for the C2-10 boundary-aware Gherkin generation and verification changes.
- **Scope:** Guard result assertions using the Gherkin parser, handle multiple named `Examples` blocks per outline, preserve scenario/block isolation, and cover inclusive/exclusive boundary outcomes. The task scope is taken from the project-owner request because no C2-10 Planner card or repository evidence checklist was found in the worktree.

## Changes evidenced

- The boundary-aware path checks parsed `Then` steps (and `And`/`But` continuations) for a result comparison. A comment or unrelated step does not satisfy the guard. Regression cases are in `packages/c2-gherkin-generation/test/pipeline.test.ts:510`.
- Feature AST traversal includes both direct feature scenarios and scenarios nested under `Rule` children in `packages/c2-gherkin-generation/src/index.ts:122` and `packages/c2-gherkin-generation/src/verification-layers.ts:86`. A Rule-contained outline and a separate top-level outline are checked for binding, generated boundary rows, completeness, and isolation in `packages/c2-gherkin-generation/test/pipeline.test.ts:657`.
- The existing `@cucumber/gherkin` parser is used to read every Examples block for its own outline. Augmentation appends generated rows within each block while retaining names, tags, descriptions, and pre-existing rows. Pipeline coverage is at `packages/c2-gherkin-generation/test/pipeline.test.ts:537`; completeness coverage for every block is at `packages/c2-gherkin-generation/test/verification-layers.test.ts:521`.
- Multiple outlines remain isolated in `packages/c2-gherkin-generation/test/pipeline.test.ts:596`.
- Mixed exclusive age bounds and inclusive quantity bounds are checked end to end, including endpoint values and result cells, in `packages/c2-gherkin-generation/test/pipeline.test.ts:729`.
- The default mode remains `llm_only_baseline`; boundary-row augmentation is only invoked in `boundary_aware` mode. The baseline default is set in `packages/c2-gherkin-generation/src/index.ts:55`, and the existing baseline pipeline coverage continues to check the unaugmented Examples data.
- Requirement consistency remains `{ status: 'skipped', ... }`, and `fully_verified` remains false while that required layer is skipped (`packages/c2-gherkin-generation/src/verification-layers.ts:461` and `:470`).

## C2-10 source and test files

- `packages/c2-gherkin-generation/README.md`
- `packages/c2-gherkin-generation/src/constraint-extractor.ts`
- `packages/c2-gherkin-generation/src/index.ts`
- `packages/c2-gherkin-generation/src/verification-layers.ts`
- `packages/c2-gherkin-generation/test/constraint-extractor.test.ts`
- `packages/c2-gherkin-generation/test/pipeline.test.ts`
- `packages/c2-gherkin-generation/test/verification-layers.test.ts`

These are the C2 package paths changed or added in the worktree relative to the current C2-09 `HEAD`. The untracked `AGENTS.md` and historical evidence files are outside this task and are not included.

## C2-10 evidence artifacts

- `evidence/c2/2026-10-18-c2-10-evidence-report.md` — this report; listed as an evidence artifact, not a source-code change.
- `evidence/c2/2026-10-18-c2-10-validation.txt` — concise captured command output and exit codes.

No files under `packages/contracts/` or frozen schemas were modified.

## Validation

These commands were rerun for this evidence; the concise output excerpts and exit codes are in [2026-10-18-c2-10-validation.txt](2026-10-18-c2-10-validation.txt):

- `corepack pnpm --filter @j26/c2-gherkin-generation typecheck` — exit code 0.
- `corepack pnpm --filter @j26/c2-gherkin-generation test` — the original run recorded 72 passing tests; after adding Rule-contained coverage, the follow-up run recorded **7 test files passed, 73 tests passed**. Both runs exited 0; see the appended follow-up in the validation artifact.
- `corepack pnpm --filter @j26/c2-gherkin-generation build` — exit code 0.
- `corepack pnpm exec prettier --check packages/c2-gherkin-generation/src/index.ts packages/c2-gherkin-generation/src/verification-layers.ts packages/c2-gherkin-generation/test/pipeline.test.ts packages/c2-gherkin-generation/test/verification-layers.test.ts` — exit code 0; all matched files formatted.
- `git diff --check` — exit code 0; no whitespace diagnostics.

The test-results artifact contains actual output excerpts from both runs, with local absolute paths omitted. No screenshots or terminal logs were fabricated.

## Limitation

Requirement consistency remains skipped until a genuine cross-encoder is configured. Therefore `fully_verified` remains false.
