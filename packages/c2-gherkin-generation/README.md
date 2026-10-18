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

## Generation modes

`C2_GENERATION_MODE` defaults to `llm_only_baseline` so the research baseline
remains available. Set it to `boundary_aware` to complete numeric EP and BVA
Examples rows from explicit ranges in `final_text`. Boundary-aware mode requires
the generated Scenario Outline to bind each constrained parameter and assert a
`<result>` value in a `Then` step. It adds rows with other constrained parameters
set to valid representatives and verifies the resulting examples before writing
the feature. Requirement consistency remains `skipped` until a genuine
cross-encoder check is configured, so scenarios remain `fully_verified: false`.

PowerShell:

```powershell
$env:C2_GENERATION_MODE = 'boundary_aware'
pnpm c2 run --in runs/<RUN-ID> --out runs/<RUN-ID>
```

## First Planner tasks

- C2-03 Input reader for `c1/validated_requirements.json` (`bdd_ready` only, `final_text`)
- C2-02 Golden C2 fixture (`.feature` + `scenario_metadata.json`) following `packages/contracts/conventions/feature-files.md`
- C2-04 Baseline LLM-only generator (uses `LLM_BASE_URL`)
