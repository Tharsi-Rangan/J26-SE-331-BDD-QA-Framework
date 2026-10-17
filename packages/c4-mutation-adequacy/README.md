# @j26/c4-mutation-adequacy — Requirement-Traceable Mutation Adequacy Attribution

**Owner:** Shajana G. (@Shajana9). Only the owner edits this folder (see `docs/INTEGRATION_RULES.md`).

## Run

```
pnpm c4 run --in runs/<RUN-ID> --subject-root <path> --out runs/<RUN-ID> [--trace-signal <mode>]
```

`--trace-signal` is `coverage_only` (default), `embedding_assisted` or `full`.
The 2 embedding modes need `LLM_BASE_URL` and `EMBEDDING_MODEL` (see `.env.example`) and `c2/scenario_metadata.json`.

During PP1, use a golden fixture folder as `--in`, for example
`packages/contracts/fixtures/golden/example-registration`.

## Develop

```
pnpm --filter @j26/c4-mutation-adequacy test        # unit tests (Vitest)
pnpm --filter @j26/c4-mutation-adequacy typecheck   # TypeScript check
pnpm --filter @j26/c4-mutation-adequacy add <dep>   # add a dependency to THIS package only
```

Copy `.env.example` to `.env` for model settings. Never commit `.env`.

## Status

| Task | What works |
|---|---|
| C4-01 | Scope card: `docs/scope-card.md` |
| C4-02 | StrykerJS 10 + Jest 29, `coverageAnalysis: perTest`, run in a temp work folder (`src/stryker.ts`) |
| C4-03 | Input loader with schema checks (`src/loader.ts`); `c4 run` writes `c4/raw/mutation.json` |
| C4-04 | Scores: overall, per module, per requirement (`src/scores.ts`) |
| C4-05 | Equivalent-mutant filter with rules E1 and E2 (`src/equivalent.ts`); writes `c4/equivalent_mutants.json`. Spot-check log: `docs/equivalent-spot-check.md` |
| C4-06 | Trace of each survivor to TST, SCN and REQ (`src/trace.ts`); `c4 run` writes `c4/adequacy_report.json` (`src/report.ts`) |
| C4-07 | Trace-signal modes with an embedding tie-break (`src/signal.ts`, `src/embedding.ts`) |

On the golden example, `c4 run` gives 14 mutants, 13 killed, 1 survived (mutant 12), score 0.9286.
Mutant 12 traces to TST-EX-001-02-01 and TST-EX-001-02-06, SCN-EX-001-02 and REQ-EX-001.
This is the same as the golden `adequacy_report.json`, and the report passes `validate.mjs`.

## Equivalent-mutant rules

C4 checks only `Survived` and `NoCoverage` mutants. A flagged mutant gets `equivalent: true` and leaves `mutation_score_filtered`.

| Rule | A mutant is flagged when |
|---|---|
| E1-same-code | The mutated code has the same tokens as the original. Whitespace, comments and quote style do not count. |
| E2-log-only | The change is only inside the arguments of `console.<method>(...)` or `debug(...)`, and those arguments have no assignment, `++`, `--` or call. |

## How the StrykerJS run works

- C4 copies the `--in` folder to a temp folder and runs StrykerJS there. The input folder stays clean.
- If `--subject-root` is given, C4 copies the subject into the folder named by `source.repo_path` (default `subject-src`).
- C4 mutates `<repo_path>/<module_path>` from `subject-manifest.json`, and uses the Jest config in `runner.config_path`.

## Trace-signal modes

| Mode | What C4 does | `trace.signal` |
|---|---|---|
| `coverage_only` | Trace through the tests that cover or kill the mutant. | `coverage` or `none` |
| `embedding_assisted` | Same as `coverage_only`. When a mutant links to more than one requirement, C4 sorts `requirement_ids` by similarity to the mutated code. | `coverage+embedding` for these mutants |
| `full` | Same as `embedding_assisted`. A mutant with no coverage gets the most similar requirement and its most similar scenario. | `embedding` for these mutants |

- The mutant text is the mutated lines, 2 lines of context on each side, the mutator and the replacement.
- The requirement text is `requirement_text_used` (or `feature_name`) from C2, plus the names of its scenarios.
- The embedding modes never drop a coverage link. They only change the order and the confidence.
- `confidence` is the share of the top similarity in the sum of all similarities. Equal similarities give 1/n, the same as `coverage_only`.

## Next Planner tasks

- C4-07 comparison table: run all 3 modes on the pilots with Ollama running
- C4-08 Blind ground truth for the pilot survivor traces
- C4-09 Gap classifier: 5 gap types with evidence
