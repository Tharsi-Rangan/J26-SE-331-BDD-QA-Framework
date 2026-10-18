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
| C4-07 | Trace-signal modes with an embedding tie-break (`src/signal.ts`, `src/embedding.ts`). Comparison on the pilot: `docs/c4-07-comparison.md` |
| C4-08 | Blind ground truth for the Express-5 pilot survivors: `docs/annotation/express-5/ground-truth.json`. Guideline: `docs/trace-annotation-guideline.md` |
| C4-09 | Gap classifier: each survivor gets a gap type, evidence and an explanation (`src/gap.ts`) |
| C4-10 | Ranked recommendations, routed to C1, C2 or C3 (`src/recommend.ts`) |
| C4-11 | HTML view: `c4 run` also writes `c4/adequacy_report.html` (`src/html.ts`). Screenshot: `docs/c4-11-html-express-5.png` |
| C4-12 | Trace accuracy against the ground truth (`src/accuracy.ts`, `scripts/trace-accuracy.ts`) and one before/after run: `docs/c4-12-results.md` |

On the golden example, `c4 run` gives 14 mutants, 13 killed, 1 survived (mutant 12), score 0.9286.
Mutant 12 traces to TST-EX-001-02-01 and TST-EX-001-02-06, SCN-EX-001-02 and REQ-EX-001.
This is the same as the golden `adequacy_report.json`, and the report passes `validate.mjs`.
The gap of mutant 12 is `weak_assertion`, and REC-001 routes it to C3 with a predicted impact of 0.0714.
Both are the same as the golden report. Only the action text is different.

## Express-5 pilot

`fixtures/pilot-express-5` is a C4-owned run folder for BugsJS Express-5, `lib/utils.js`.
C4 wrote its 5 requirements, 12 scenarios and 16 Jest tests by hand. They are not C1, C2 or C3 output.
`scripts/pilot-express-5-fixture.py` writes the folder again.

```sh
git clone https://github.com/BugsJS/express.git /tmp/c4-subjects/express
git -C /tmp/c4-subjects/express checkout 999546dfdeb874c20b360ad58346ed07917f3ac0
npm --prefix /tmp/c4-subjects/express install --omit=dev --ignore-scripts
pnpm c4 run --in fixtures/pilot-express-5 --subject-root /tmp/c4-subjects/express --out /tmp/c4-pilot-express-5
```

The run gives 138 mutants, 79 killed, 29 survived, 29 no coverage, score 0.5766.

## Ground truth (C4-08)

| Step | File |
|---|---|
| Blind packet: requirements, scenarios, tests, source and survivors, with no C4 output | `docs/annotation/express-5/packet.md` (`scripts/annotation-packet.py`) |
| Labels from 2 annotators, made on their own: Claude Haiku and Claude Sonnet | `labels-haiku.json`, `labels-sonnet.json` |
| Agreement (`scripts/annotation-agreement.mjs`) | `agreement.md` |
| Disagreements decided by a person (Shajana G.) | `decisions.md` |
| Ground truth: agreed labels plus decisions | `ground-truth.json` |

| Field | Agreement | Cohen kappa |
|---|---|---|
| `requirement_id` | 0.931 | 0.906 |
| `scenario_id` | 0.983 | 0.975 |
| `test_ids` | 0.983 | 0.974 |
| `gap_type` | 0.845 | 0.761 |

## Trace accuracy and before/after (C4-12)

```sh
npx tsx scripts/trace-accuracy.ts <out>/c4/adequacy_report.json docs/annotation/express-5/ground-truth.json
```

| Field | `coverage_only` accuracy |
|---|---|
| requirement | 0.845 |
| scenario | 0.759 |
| tests | 0.983 |
| gap type | 0.759 |

`fixtures/pilot-express-5-rec-001` is the pilot with REC-001 applied: 1 new scenario and 1 new test.
The mutation score goes from 0.5766 to 0.6569 (+0.0803). REC-001 predicted +0.0365.
Details: `docs/c4-12-results.md`.

## HTML view (C4-11)

`c4 run` writes `c4/adequacy_report.html` next to the JSON report. The page is one file with no scripts and no external files.
It shows the summary, the requirement scores, the ranked recommendations and every survivor with its trace and gap.
To write the page again from a JSON report: `npx tsx scripts/render-html.ts <out>/c4/adequacy_report.json`.

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
- If the subject has a `node_modules` folder, Jest gets its path in `modulePaths`. The StrykerJS sandbox does not copy the subject's `node_modules` link.

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

## Gap rules

C4 gives each survivor one gap type. The first rule that matches wins.

| Order | Gap type | A survivor gets it when | Evidence |
|---|---|---|---|
| 1 | none (`gap: null`) | The mutant is equivalent (C4-05). | - |
| 2 | `missing_test` | No manifest test covers the mutant. | Mutated code |
| 3 | `incomplete_mock` | The mutated code calls a symbol that `c3/mock_decisions.json` mocks for a scenario of the trace. | Mutated code |
| 4 | `missing_boundary` | The mutator is `EqualityOperator`, for example `<` to `<=`. | Mutated code |
| 5 | `untested_branch` | The mutator is `ConditionalExpression`, `LogicalOperator`, `BlockStatement` or `OptionalChaining`. | Mutated code |
| 6 | `weak_assertion` | All other survivors that a test covers. | The `expect(...)` line of a covering test |

For `weak_assertion`, C4 picks a `toThrow` check when the mutated code throws, and a value check when it returns.

## Recommendations

C4 groups the survivors that have a gap by gap type, route and scenario. Each group is one recommendation.

| Gap type | Route | What the stage must do |
|---|---|---|
| `missing_test` | C2 | Add a scenario that runs the code. Used when the trace has no scenario. |
| `missing_test` | C3 | Generate a test for the scenario. Used when the `full` mode found a scenario. |
| `missing_test` | C1 | Add the behaviour to a requirement. Used when the embedding link has a confidence below 0.5. |
| `untested_branch` | C2 | Add a scenario that takes the branch. |
| `missing_boundary` | C2 | Add Examples rows at the exact limit. |
| `weak_assertion` | C3 | Make the assertion check the changed value. |
| `incomplete_mock` | C3 | Check the mock call arguments, or make the mock return depend on the input. |

- `predicted_impact` is the gain in `mutation_score_filtered` when the tests kill every mutant of the group.
- Rank order: higher impact first, then gap type in the order of the table, then requirement and scenario ID.
- A survivor with no requirement targets the subject's requirement when the subject has exactly one. If not, C4 skips it.

## Next Planner tasks

- C4-13 Demo script, slides and backup video
