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

## First Planner tasks

- C4-02 StrykerJS + Jest with `coverageAnalysis: perTest` on the pilot modules
- C4-03 Input loader: `c3/test_manifest.json` + subject root; run Stryker on the golden C3 tests
- C4-06 Traceability mapper: Jest name -> TST/SCN/REQ
