# @j26/c3-test-generation — Runnable Test Generation with Explainable Assertions and Mocking

**Owner:** Tharsiga R. (@Tharsi-Rangan). Only the owner edits this folder (see `docs/INTEGRATION_RULES.md`).

## Run

```
pnpm c3 run --in runs/<RUN-ID> --subject-root <path> --out runs/<RUN-ID>
```

During PP1, use a golden fixture folder as `--in`, for example
`packages/contracts/fixtures/golden/example-registration`.

`run` also scans each subject module (C3-04) and writes `<out>/c3/work/dependency_scan.json`
(an internal file, not a contract). The subject folder is `--subject-root`, or the manifest's
`source.repo_path` inside `--in` for golden fixtures.

### Dependency scan only (C3-04)

```
pnpm c3 scan --subject-root <checked-out subject> --module lib/utils.js [--exports a,b] [--out scan.json]
```

Lists the module's imports, what it really uses from each (plus globals such as `Date`,
`Math.random`, `process`, timers), which dependencies each export reaches (also through local
helpers), what runs as soon as the module is required, and a side-effect guess (`io`, `network`,
`time`, `random`, `database`, `none`, `unknown`) from known names. Kinds and side effects match `dependency.kind` and `dependency.side_effect` in
`c3-mock-decisions.schema.json`.

### Mock decisions (C3-05)

`run` turns the scan into `<out>/c3/mock_decisions.json` (contract file): one decision per
(scenario, dependency) the test touches, i.e. what the function under test reaches plus what runs on
`require()`. The decision always comes from a rule (first match wins, `rules_version` 0.1.0):

| Rule | Decision | When                                                                        |
| ---- | -------- | --------------------------------------------------------------------------- |
| R-01 | mock     | the dependency talks to the network                                         |
| R-02 | no_mock  | the dependency only writes log or warning output                            |
| R-03 | mock     | the dependency uses a database                                              |
| R-04 | mock     | the dependency reads the clock or random numbers                            |
| R-05 | mock     | the function under test reads or writes files, processes or the environment |
| R-06 | no_mock  | the I/O happens only while the module loads (the project's own files)       |
| R-07 | no_mock  | the dependency has no side effect                                           |
| R-08 | no_mock  | the side effect is unknown (kept real, flagged for review)                  |

The function under test is the manifest export named in the scenario text (or the only one). A
`mock` decision gets a rule-based default `behaviour`; C3-07 replaces it with behaviour derived from
the Given/When steps.

### Model client (C3-06)

All model calls go through one `ModelClient` (`src/model/`). Settings come only from `.env`
(copy `.env.example`), so switching between local Ollama (daily work) and Hugging Face (official
runs, provider pinned) is an `.env` change, never a code change.

- Timeouts (`LLM_TIMEOUT_MS`) and retries with backoff for HTTP 429/5xx and network errors (`LLM_MAX_RETRIES`).
- Every answer records the model tag (`<model>@<provider>`).
- Answer cache in `model-cache/` (`LLM_CACHE=readwrite`). For the offline PP1 demo use
  `LLM_CACHE=readonly`: only cached answers are used, and a missing one is a clear error.
- Unit tests use `FakeModelClient` and never call a real model.

Check your setup (cache off, one tiny prompt):

```
pnpm c3 model-check
```

## Develop

```
pnpm --filter @j26/c3-test-generation test        # unit tests (Vitest)
pnpm --filter @j26/c3-test-generation typecheck   # TypeScript check
pnpm --filter @j26/c3-test-generation add <dep>   # add a dependency to THIS package only
```

Copy `.env.example` to `.env` for model settings (see "Model client" above). Never commit `.env`.

## First Planner tasks

- C3-03 Input reader: `.feature` + `scenario_metadata.json` + subject manifest (`fully_verified` only)
- C3-02 Golden C3 fixture following `packages/contracts/conventions/jest-tests.md`
- C3-04 ts-morph dependency scan
