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
