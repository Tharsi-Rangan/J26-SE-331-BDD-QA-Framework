# @j26/c4-mutation-adequacy — Requirement-Traceable Mutation Adequacy Attribution

**Owner:** Shajana G. (@Shajana9). Only the owner edits this folder (see `docs/INTEGRATION_RULES.md`).

## Run

```
pnpm c4 run --in runs/<RUN-ID> --subject-root <path> --out runs/<RUN-ID>
```

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

On the golden example, `c4 run` gives 14 mutants, 13 killed, 1 survived (mutant 12), score 0.9286.
This is the same as the golden `adequacy_report.json`.

## How the StrykerJS run works

- C4 copies the `--in` folder to a temp folder and runs StrykerJS there. The input folder stays clean.
- If `--subject-root` is given, C4 copies the subject into the folder named by `source.repo_path` (default `subject-src`).
- C4 mutates `<repo_path>/<module_path>` from `subject-manifest.json`, and uses the Jest config in `runner.config_path`.

## Next Planner tasks

- C4-05 Equivalent-mutant filtering
- C4-06 Traceability mapper for survivors (TST/SCN/REQ, many-to-many)
