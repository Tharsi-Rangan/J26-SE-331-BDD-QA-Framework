# @j26/c3-test-generation — Runnable Test Generation with Explainable Assertions and Mocking

**Owner:** Tharsiga R. (@Tharsi-Rangan). Only the owner edits this folder (see `docs/INTEGRATION_RULES.md`).

## Run

```
pnpm c3 run --in runs/<RUN-ID> --subject-root <path> --out runs/<RUN-ID>
```

During PP1, use a golden fixture folder as `--in`, for example
`packages/contracts/fixtures/golden/example-registration`.

## Develop

```
pnpm --filter @j26/c3-test-generation test        # unit tests (Vitest)
pnpm --filter @j26/c3-test-generation typecheck   # TypeScript check
pnpm --filter @j26/c3-test-generation add <dep>   # add a dependency to THIS package only
```

Copy `.env.example` to `.env` for model settings. Never commit `.env`.

## First Planner tasks

- C3-03 Input reader: `.feature` + `scenario_metadata.json` + subject manifest (`fully_verified` only)
- C3-02 Golden C3 fixture following `packages/contracts/conventions/jest-tests.md`
- C3-04 ts-morph dependency scan
