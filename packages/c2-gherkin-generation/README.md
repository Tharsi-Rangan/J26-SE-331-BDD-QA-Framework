# @j26/c2-gherkin-generation — Boundary-Aware Gherkin Scenario Generation

**Owner:** Shanchika S. (@Shanchika). Only the owner edits this folder (see `docs/INTEGRATION_RULES.md`).

## Run

```
pnpm c2 run --in runs/<RUN-ID> --out runs/<RUN-ID>
```

During PP1, use a golden fixture folder as `--in`, for example
`packages/contracts/fixtures/golden/example-registration`.

## Develop

```
pnpm --filter @j26/c2-gherkin-generation test        # unit tests (Vitest)
pnpm --filter @j26/c2-gherkin-generation typecheck   # TypeScript check
pnpm --filter @j26/c2-gherkin-generation add <dep>   # add a dependency to THIS package only
```

Copy `.env.example` to `.env` for model settings. Never commit `.env`.

## First Planner tasks

- C2-03 Input reader for `c1/validated_requirements.json` (`bdd_ready` only, `final_text`)
- C2-02 Golden C2 fixture (`.feature` + `scenario_metadata.json`) following `packages/contracts/conventions/feature-files.md`
- C2-04 Baseline LLM-only generator (uses `LLM_BASE_URL`)
