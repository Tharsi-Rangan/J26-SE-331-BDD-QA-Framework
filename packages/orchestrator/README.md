# @j26/orchestrator — Pipeline orchestrator (run folder, run_id, validation)

**Owner:** Tharsiga R. (@Tharsi-Rangan). Only the owner edits this folder (see `docs/INTEGRATION_RULES.md`).

## C3-15 skeleton: what `orch run` does now

Running c1 → c4 one after another is **PP2**. For PP1 the orchestrator only prepares a clean,
valid run folder that every component can use as `--in` and `--out`:

1. **Run id + folder.** Makes `RUN-<yyyymmdd>-<hhmmss>-<4 chars>` (local time) and creates
   `runs/<RUN-ID>/`. The pattern is read from `common.schema.json`, so it can never drift from the
   contract. A given `--out` must already be named like a run id, and must be new or empty, so one
   folder never mixes two runs.
2. **Subject manifest.** Copies it in byte for byte. Order: `--subject-manifest`, else the one in
   `--in`, else `fixtures/subjects/subject-manifest.json`.
3. **Seed (optional, PP1).** With `--in <golden folder>`, copies the stage folders in `--stages`
   (default `c1,c2`, the inputs C3 needs) plus everything that is not a stage (`subject-src/`,
   `jest.config.js`, ...). Later stage folders are left out, because those stages make them again.
   Copied contract files get the **new** `run_id`, so the folder holds one `run_id`
   (INTEGRATION_RULES s3). The `--in` folder itself is never changed.
4. **Validate.** Runs `packages/contracts/scripts/validate.mjs` on the folder. A failure makes
   `orch run` exit 1.
5. **Record.** Writes `orch/run.json`: run id, time, where the manifest and seed came from, which
   files got the new `run_id`, the validate result. `--srs` and `--subject-root` are recorded for
   PP2 only.

## Run

```
# fresh run folder with the pilot subject manifest
pnpm orch run

# PP1: seed from the golden example, then run C3 on it
pnpm orch run --in packages/contracts/fixtures/golden/example-registration --out runs/RUN-20261019-093000-demo
pnpm c3 run --in runs/RUN-20261019-093000-demo --out runs/RUN-20261019-093000-demo

# copy every stage (for example, to give C4 a ready folder)
pnpm orch run --in packages/contracts/fixtures/golden/example-registration --stages c1,c2,c3,c4
```

| Option | Meaning |
|---|---|
| `--out runs/<RUN-ID>` | Run folder; the folder name is the run id. Left out: `runs/<new id>`. |
| `--in <folder>` | Golden fixture (or earlier run) to seed from. |
| `--stages c1,c2` | Stage folders to copy from `--in`. Needs `--in`. |
| `--subject-manifest <file>` | Subject manifest to copy in. |
| `--srs`, `--subject-root` | Recorded in `orch/run.json` only (PP2). |

`runs/` is git-ignored.

## Develop

```
pnpm --filter @j26/orchestrator test        # unit tests (Vitest)
pnpm --filter @j26/orchestrator typecheck   # TypeScript check
pnpm --filter @j26/orchestrator add <dep>   # add a dependency to THIS package only
```

Copy `.env.example` to `.env` for model settings. Never commit `.env`.

## Planner tasks

- [x] C3-15 Orchestrator skeleton: create run folder + run_id, copy subject manifest, run validate
- [ ] PP2: call c1 → c2 → c3 → c4 in order, stop on the first failing stage
