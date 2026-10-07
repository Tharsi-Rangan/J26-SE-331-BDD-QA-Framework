# @j26/orchestrator — Pipeline orchestrator (run folder, run_id, validation)

**Owner:** Tharsiga R. (@Tharsi-Rangan). Only the owner edits this folder (see `docs/INTEGRATION_RULES.md`).

## Run

```
pnpm orch run --srs <file> --subject-root <path> --out runs/<RUN-ID>
```

During PP1, use a golden fixture folder as `--in`, for example
`packages/contracts/fixtures/golden/example-registration`.

## Develop

```
pnpm --filter @j26/orchestrator test        # unit tests (Vitest)
pnpm --filter @j26/orchestrator typecheck   # TypeScript check
pnpm --filter @j26/orchestrator add <dep>   # add a dependency to THIS package only
```

Copy `.env.example` to `.env` for model settings. Never commit `.env`.

## First Planner tasks

- C3-15 Orchestrator skeleton: create run folder + run_id, copy subject manifest, run validate (full pipeline is PP2)
