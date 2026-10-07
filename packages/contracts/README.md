# @j26/contracts — shared contracts v1.0.0

Frozen interfaces between C1 → C2 → C3 → C4 (J26-SE-331).

| File | Producer → Consumer |
|---|---|
| `schemas/common.schema.json` | IDs, header ("envelope"), enums used by all |
| `schemas/subject-manifest.schema.json` | shared (C3+C4): which code each requirement is about |
| `schemas/c1-validated-requirements.schema.json` | C1 → C2 |
| `schemas/c2-scenario-metadata.schema.json` (+ `.feature`) | C2 → C3 |
| `schemas/c3-test-manifest.schema.json` | C3 → C4 |
| `schemas/c3-mock-decisions.schema.json` | C3 → C4 / reviewers |
| `schemas/c3-confidence-report.schema.json` | C3 → C4 / reviewers |
| `schemas/c4-adequacy-report.schema.json` | C4 → C1, C2, C3 |

## Key rules in one place
- C2 reads only `final_text` and only requirements with `bdd_ready: true`.
- C3 processes only scenarios with `verification.fully_verified: true` and uses C2's boundary values as-is.
- `jest_full_name` must match what StrykerJS prints, so C4 can trace tests to requirements.
- Every file carries the same `run_id`.

## Golden example
`fixtures/golden/example-registration/` is one complete, valid chain (requirement → scenarios → Jest tests → real StrykerJS result: 14 mutants, 13 killed, 1 survived).
Copy its shape for the three real BugsJS pilot subjects.

## Validate
```
pnpm --filter @j26/contracts install
node packages/contracts/scripts/validate.mjs packages/contracts/fixtures/golden/example-registration
node packages/contracts/scripts/validate.mjs runs/<RUN-ID>
```
Python: `jsonschema.Draft202012Validator` with a `referencing.Registry` holding all files in `schemas/`.

See `docs/INTEGRATION_RULES.md` for ownership, versioning and git rules.
