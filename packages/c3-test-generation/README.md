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

### Mock behaviour (C3-07)

For every `mock` decision, the model says **what** the mock does; the rule (C3-05) already decided
**whether** to mock. The prompt gives the model the scenario's Given/When steps numbered `S1, S2, ...`,
the dependency's signature and side effect, and the rule's reason. The model answers with one JSON object:

```json
{ "steps": ["S1"], "kind": "returns_input", "value": { "id": "u1" }, "error_message": null,
  "summary": "save() returns the given user with id 'u1'.", "rationale": "S1 says the repository is available, ..." }
```

- `kind` is one of `returns`, `returns_input`, `throws`, `resolves`, `rejects`.
- C3 checks the answer: known step ids only, `kind` from the list, `value` / `error_message` when the
  kind needs them, `resolves`/`rejects` only for functions that return a Promise, short sentences.
- A bad answer gets **one retry** with the problems listed. A second bad answer keeps the rule default
  (`source: "rule_default"` in the work file), so nothing invalid reaches the contract file.
- A Promise signature turns `returns`/`throws` into `resolves`/`rejects` (recorded as a note).
- Review warnings (not errors): a cited step sounds like a failure but the mock succeeds, or the other way round.

Output: `behaviour` in `c3/mock_decisions.json` gets the cited step texts, `summary`, `rationale` and the
model tag. The structured part (`kind`, `value`, ...) goes to `c3/work/mock_behaviour.json` for the Jest
writer (C3-10), which turns it into Jest code with `behaviourToJest()`, e.g.
`userRepository.save.mockImplementation((input) => ({ ...{"id":"u1"}, ...input }));`.

`c3 run` uses the model in `.env`. With `--no-model`, or when `.env` has no `LLM_BASE_URL`, it keeps the
rule defaults and never calls a model.

### Typed assertions (C3-08)

One model call per scenario. The model does **not** write test code: it fills slots in one JSON object.

```json
{ "act": "registerUser({ age: <age>, email: \"test@example.com\" })",
  "assertions": [
    { "then": "T1", "when": { "column": "result", "equals": "rejected" }, "category": "exception", "error": "ValidationError" },
    { "then": "T1", "when": { "column": "result", "equals": "accepted" }, "category": "state_change",
      "target": "userRepository.save", "change": "called_times", "times": 1 } ] }
```

- `act`: one call of the function under test with the values from the Given/When steps. Outlines keep
  `<column>` placeholders; `"<path>"` in quotes is passed as a string, bare `<age>` as the row's typed value.
- `assertions`: at least one per Then step (`T1`, `T2`, ...), each with a category and its slots.
  Outlines can add `when` so an assertion holds only for rows with that cell value.
- The model sees the function's **parameter names only, never its code**, so assertions follow the requirement.

C3 checks every answer: `act` parses, uses only exports / literals / placeholders and calls the function
under test; `actual` uses `result`; `error` is an exported class or a built-in error; `target` is a mocked
dependency of this scenario; `when` uses a real column value; every Then step and every Examples row has an
assertion; a row that throws does not also check `result`. A bad answer gets one retry; a second bad answer
marks the plan `failed` (C3-13 routes it to a stub). Without a model every plan is `failed`.

Fixed templates (`src/assert/templates.ts`):

| Category       | Jest code                                                                                                   |
| -------------- | ----------------------------------------------------------------------------------------------------------- |
| `equality`     | `expect(actual).toBe(x)` (literals), `toEqual(x)` (objects, arrays, row values), `toBeFalsy()` for `false`, `toBeNull()` for `null` |
| `exception`    | `expect(() => act).toThrow(Error)`; async: `await expect(act).rejects.toThrow(Error)`                       |
| `state_change` | `expect(mock).toHaveBeenCalledWith(...)`, `.toHaveBeenCalled()`, `.not.toHaveBeenCalled()`, `.toHaveBeenCalledTimes(n)` |
| `range`        | `expect(actual).toBeGreaterThanOrEqual(min)` / `toBeLessThanOrEqual(max)` (or the strict forms)              |

`false` uses `toBeFalsy()` because JavaScript predicates often return `undefined` for "no", which the
requirement also means.

A rule-based category guess (keywords such as *error/rejected* -> exception, *between/at least* -> range,
*saved/sent/called* -> state_change, else equality) is kept for every (row, Then step), and
`category_agreement` (share where the model used the rule's category) is a confidence signal for C3-13.

Output: `c3/work/assertion_plan.json` (internal), read by the Jest writer (C3-10).

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
