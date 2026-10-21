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
assertion; a row that throws does not also check `result`. An assertion may not check what only a mock returns
(rule 4): neither a `result.<field>` the act does not pass in, nor a `called_with` field that only the mock's
value has or that no step names (found in the real Qwen run on 19 Oct: `save()` expected `{ id: null,
registered: true }`, both taken from the mock). A bad answer gets one retry; a second bad answer
marks the plan `failed` (C3-13 routes it to a stub). Without a model every plan is `failed`.

Fixed templates (`src/assert/templates.ts`):

| Category       | Jest code                                                                                                   |
| -------------- | ----------------------------------------------------------------------------------------------------------- |
| `equality`     | `expect(actual).toBe(x)` (literals), `toMatchObject(x)` (objects: the requirement names some fields, not all), `toEqual(x)` (arrays, row values), `toBeFalsy()` for `false`, `expect(actual ?? null).toBeNull()` for `null` |
| `exception`    | `expect(() => act).toThrow(Error)`; async: `await expect(act).rejects.toThrow(Error)`                       |
| `state_change` | `expect(mock).toHaveBeenCalledWith(...)`, `.toHaveBeenCalled()`, `.not.toHaveBeenCalled()`, `.toHaveBeenCalledTimes(n)` |
| `range`        | `expect(actual).toBeGreaterThanOrEqual(min)` / `toBeLessThanOrEqual(max)` (or the strict forms)              |

`false` uses `toBeFalsy()` because JavaScript predicates often return `undefined` for "no", which the
requirement also means. `null` means "no value" (JSON has no `undefined`), so it accepts `null` and
`undefined`: a function that returns nothing gives `undefined` (found in the C3-14 pilot: `compileETag(false)`).

A rule-based category guess (keywords such as *error/rejected* -> exception, *between/at least* -> range,
*saved/sent/called* -> state_change, else equality) is kept for every (row, Then step), and
`category_agreement` (share where the model used the rule's category) is a confidence signal for C3-13.

Output: `c3/work/assertion_plan.json` (internal), read by the Jest writer (C3-10).

### Strategy (C3-09)

Rules only (`src/strategy.ts`, `rules_version` 0.1.0), written to `c3/work/strategy.json` with a reason:

| Rule | Strategy       | When                                                                                     |
| ---- | -------------- | ---------------------------------------------------------------------------------------- |
| S-01 | `parametrised` | Scenario Outline: one `test.each` row per Examples row; C2's values and BV/EP refs as-is |
| S-02 | `factory`      | any other scenario: one test built from the Given/When step values                       |

`property_based` (fast-check over a C2 numeric range) is planned for PP2. A plain scenario with a numeric
range says in its reason that it is a candidate.

### Jest writer (C3-10)

`c3 run` writes, from the assertion plans (C3-08), mock behaviour (C3-07) and strategy (C3-09):

- `c3/runnable_tests/<REQ>.test.js`: one file per requirement, first line `// @requirement REQ-...`, one top-level
  `describe('[REQ-...] <feature>')`, test titles `[SCN-...][TST-...] <scenario> :: <case>`
  (`packages/contracts/conventions/jest-tests.md`). Outline rows become `test.each` rows (TST id, case label,
  then the Examples values with C2's types); rows whose code is the same share one `test.each`.
- Mocks: `jest.mock()` for each mocked module (path inside the subject for internal modules); every test resets
  its mocks and sets the C3-07 behaviour, so scenarios never share mock state. Globals (`Date.now`) use
  `jest.spyOn`, restored after each test.
- `c3/jest.config.cjs`: run from the run folder (`rootDir: '..'`), with the subject's `node_modules` on the module path.
- `c3/test_manifest.json` (contract): every test with its exact Jest full name, Examples row, BV/EP refs,
  strategy, assertion categories and mock decision ids. Verification fields are `skipped` until C3-11.

The tests expect the subject at `<run folder>/<source.repo_path>` (default `subject-src`), like C4.
`src/runner/jest.ts` runs them in a sandbox (the run's `c3/` + a copy of the subject, `node_modules` linked).
On the golden example the 7 generated tests pass, every Jest full name equals its manifest name, and an
off-by-one bug (`age > 64`) makes exactly the age-65 test fail.

### Verification (C3-11, PP1 version)

After writing the tests, `c3 run` runs them with Jest in a sandbox on the given subject and records four
checks per test in `test_manifest.json` (`verification`), with details in `c3/work/verification.json`:

| Layer          | PP1 check                                                                                                  |
| -------------- | ---------------------------------------------------------------------------------------------------------- |
| `syntactic`    | the file parses and Jest loads it                                                                          |
| `referential`  | the module under test, the names taken from it and internal mocked modules exist in the subject           |
| `traceability` | TST embeds SCN, the name is `[REQ] ... [SCN][TST] ...`, C2 fully verified it, Jest reported that exact name |
| `semantic`     | rule-based grounding score: 0.5 x category agrees with the rule guess + 0.5 x share of literal values found in the steps (pass >= 0.5). The cross-encoder is planned for PP2. |

Each Jest result is sorted by cause, because C3 usually runs on the version C4 will mutate (the buggy one):
`passed`, `assertion_failed` (an expect() failed) and `subject_error` (the code under test threw) are kept,
as they may have found a bug (check on the fixed version, C3-14); `test_error` (the error is raised in the
test code) and `suite_error` (Jest could not load the file) mean the test is broken and go to repair (C3-12).

On the golden example all 7 tests pass all 4 checks; with an off-by-one bug (`age > 64`) the age-65 test is
`subject_error` ("age out of range"), not a broken test.

### Repair loop (C3-12, PP1 version)

Only **broken** tests are repaired: a check fails (syntactic, referential, traceability) or Jest reports
`test_error` / `suite_error`. A test that fails because the code under test throws or an expect() fails may
have found a bug, so it is never "repaired" into passing.

Each round (at most 3), the model gets its previous answer and the errors, answers again (checked like C3-08),
and all tests are rebuilt and run again. A scenario still broken after 3 rounds gets no runnable test (a
broken test is never released); C3-13 routes it to a stub. `repair_rounds` goes into `test_manifest.json`;
every round is logged in `c3/work/repair_log.json`.

### Confidence routing (C3-13)

Every scenario C3 received gets a route and a reason in `c3/generation_confidence_report.json` (contract).
Confidence is a weighted formula over rule-based signals, **not** the model's own confidence
(formula 0.1.0, threshold 0.8, `calibrated: false`; PP2 calibrates it against the expert labels):

| Signal                          | Weight | Meaning                                                              |
| ------------------------------- | ------ | -------------------------------------------------------------------- |
| `all_deterministic_checks_pass` | 0.30   | syntactic, referential and traceability pass for every test          |
| `semantic_score`                | 0.30   | mean C3-11 semantic score of its tests                               |
| `runs_clean`                    | 0.10   | Jest ran every test without a broken-test error                      |
| `no_repair_needed`              | 0.10   | no repair round                                                      |
| `c2_fully_verified`             | 0.10   | C2 verified the scenario                                             |
| `mock_behaviour_from_model`     | 0.10   | every mock behaviour came from a checked model answer (or no mocks) |

A clean test scores 0.7 + 0.3 x semantic, so it needs semantic >= 0.34 to run; a repaired test needs >= 0.67.

| Route                  | When                               | Output                                                              |
| ---------------------- | ---------------------------------- | ------------------------------------------------------------------- |
| `runnable`             | confidence >= 0.8                  | its tests stay in `c3/runnable_tests`; `test_ids` in the report    |
| `stub`                 | confidence < 0.8, or no usable plan | `c3/test_stubs/STB-...stub.js`: `test.todo`, the steps, the reason and C3's draft code for a human |
| `skipped_not_verified` | C2 did not fully verify it         | nothing                                                             |

A runnable scenario whose tests fail on the given subject says so in its reason ("possible bug found; check
on the fixed version"). Stubs never run (`jest.config.cjs` only looks in `c3/runnable_tests`).

### Pilot: buggy vs fixed (C3-14)

```
pnpm c3 pilot --run runs/<RUN-ID> --buggy <subject root> --fixed <subject root> --label Express-5
```

Tests are generated **once, on the buggy version** (`c3 run --subject-root <buggy>`), as in real use
where the fix is not known. `c3 pilot` then runs the **same** test files on both versions:

| Outcome | Meaning |
|---|---|
| `bug_detected` | fails on buggy, passes on fixed |
| `false_alarm` | fails on fixed (the fixed code is taken as correct) |
| `no_signal` | passes on both: the test does not reach this bug |

It writes `c3/work/pilot_results.json` and `c3/work/pilot_results.md` (scenarios, runnable %, tests,
bugs detected, false alarms, stubs).

Control subject: `fixtures/pilot/example-off-by-one/` is the golden example with a planted off-by-one
bug (`age > 64`). It is not a BugsJS bug; it shows what a detected bug looks like in the table.

Fixes found while preparing the Express-5 pilot (`lib/utils.js`, 6 exports):

- **Target export (C3-05):** when no export is fully named in the scenario, the one export with the
  most name words in the scenario or feature text is used ("Trust a number of hops" -> `compileTrust`).
  Generic words (`is`, `set`, `compile`, ...) do not count; a tie keeps all exports in scope.
- **Returned functions (C3-08):** an act may call the function an export returns, e.g.
  `compileTrust(2)("10.0.0.1", 0)`; its callee is still `compileTrust`. Prompt version 0.4.0.
- **`null` expected (C3-08 template):** `expect(x ?? null).toBeNull()`, because a JS function that
  returns nothing gives `undefined` (`compileETag(false)`).

Fix-3, from the first real Qwen run on Express-5 (run 1: 15 tests, 0 bugs found, 10 false alarms that
also fail on the fixed code). Three causes, each now handled for every subject:

| Cause in run 1 | Tests | Fix (prompt version 0.5.0) |
|---|---|---|
| Quote marks copied into the value: `toBe("\"text/html\"")` | 3 | A string that is a step value wrapped in quotes is unwrapped (`unquoteValue`) |
| A Given/When value missing from the act: `compileTrust(<hop>)` for "the trust setting 2" | 2 | Rule 7 + check: every Given/When value must appear in the act, else the answer is retried with the reason (`unusedStepValues`) |
| Result shape guessed: `result.type`, `result.q`; a returned function compared to `true` | 6 | Rule 8 + check: `actual` may only use field names from the Then steps (or `length`/`size`) (`inventedResultFields`); the export's **JSDoc** (description, `@param`, `@return`) is shown to the model as the documented interface, never its code |

Fix-4, from Qwen run 2 (14 tests, 6 false alarms, 1 stub). Five more generic causes (prompt version 0.6.0):

| Cause in run 2 | Fix |
|---|---|
| A documented `Object`/`Array`/`Function` result compared whole with a plain value (`toBe("text/html")`) | Rejected with the documented type (`documentedReturn`) |
| Invented key inside an expected object (`{ type: ... }`); whole-object `toEqual` fails on extra fields | Keys checked like fields; objects render as `toMatchObject` |
| A string no step states (`"application/json"`) | Rule 10 + check (`ungroundedStrings`); `typeof` words are allowed |
| A Then step with `<kind>` but one assertion for every row (the `none` row) | Rule 11 + check: use `"<kind>"` or `when` on that column (`thenColumns`) |
| A When-step `<hop>` missing from the act; a list value passed split up was wrongly rejected | Placeholders of Given/When steps must reach the act; `"a, b"` counts as used when every part is in the act |

Fix-5, from the control run (golden example, prompt 0.6.0): Qwen wrote `expect(result).toBe("accepted")` for the
accepted rows. The checks rightly refused it (it would fail on correct code), but two messages misled the retry.
Now Examples cells count as stated values, an outcome label used as the return value is named as such and rule 5
is given when a mocked dependency exists (`outcomeLabel`), and `"actual": "<result>"` gets a clear message instead
of a parser error. The prompt text did not change (still 0.6.0); only the checks and retry messages did.

When the requirement does not say what shape the result has, C3 takes the shape from the documented
interface. If there is no documentation either, the answer cannot pass the checks and the scenario is a stub
with the reason, never a guessed test.

### BugsJS batch: screening all 453 bugs and running C3 on the 10 in scope

`scripts/screen-bugsjs.mjs` reads every BugsJS bug (tags `Bug-N` vs `Bug-N-fix`, code is never run) and asks:
is the fix in ONE production file, inside an exported function that C3 can call with plain values (no
request/callback/context/AST input, no `this`, no constructor)? Reviewed exceptions are listed in `MANUAL`.

```
node scripts/screen-bugsjs.mjs <folder with the 10 BugsJS clones> screen.json docs/bugsjs-screening.csv
```

Result (21 Oct 2026): **10 of 453 bugs (2.2%)** are in C3's PP1 scope: express-5, shields-4, hexo-7, eslint-22,
eslint-23, eslint-197, eslint-209, eslint-267, eslint-273, eslint-281. The other 443 need inputs such as rule
contexts, requests or class instances (PP2: input factories). Full table: `docs/bugsjs-screening.csv`.

`fixtures/bugsjs/<bug>/` holds the C2 input for the 9 new bugs (express-5 is `fixtures/pilot-express-5` in C4).
Requirements and scenarios are written **from each project's documentation, not from the bug or the fix**; the
doc source is in each `subject-manifest.json` (`notes`). Every scenario was checked to be true on the fixed version.

One command sets up all bugs (clone, buggy + fixed folders, npm install) and runs `c3 run` + `c3 pilot` on each:

```
powershell -ExecutionPolicy Bypass -File packages\c3-test-generation\scripts\run-bugsjs.ps1
```

Options: `-Subjects C:\c3-subjects`, `-Only eslint-22,hexo-7`, `-SkipSetup`, `-Cache readonly` (replay). The
summary table is printed and written to `runs\bugsjs-summary.md`.

Found while preparing the batch: a nameless `module.exports = function (...)` (ESLint's `lib/formatters/junit.js`)
was scanned as `default`, which is not a valid variable name in a test. It is now named after its file
(`junit.js` -> `junit`, `make-badge.js` -> `makeBadge`, see `nameFromFile`).

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
