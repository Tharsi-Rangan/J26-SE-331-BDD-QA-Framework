# C3-14 pilot results: Express-5 (BugsJS) and a planted-bug control

Model: `Qwen/Qwen2.5-Coder-7B-Instruct:nscale@huggingface`, temperature 0, answer cache on.
Date: 19 Oct 2026. Tool: `c3 run` + `c3 pilot` (this branch).

## Setup

| | Express-5 | Control |
|---|---|---|
| Subject | BugsJS Express, `lib/utils.js` (6 exports) | Golden example, `src/registration.js` |
| Bug | `isAbsolute("c:/")` returns false (buggy `999546df`, fixed `23b85883`) | Planted off-by-one: `age > 64` instead of `age > 65` (`fixtures/pilot/example-off-by-one`) |
| C2 input | Hand-written by C4 (`c4/feat/html-report`, `fixtures/pilot-express-5`): 5 requirements, 12 scenarios | Golden C2 fixture: 2 scenarios (1 outline with 6 rows) |
| Mocks | none (all 10 dependencies are pure: `no_mock`) | `userRepository.save` (mock) |

Method: tests are generated **once, on the buggy version** (in real use the fix is not known), then
`c3 pilot` runs the **same** test files on the buggy and the fixed version.

- `bug_detected` = fails on buggy, passes on fixed
- `false_alarm` = fails on the fixed version (the fixed code is taken as correct)
- `no_signal` = passes on both

## Results per run (Express-5)

Each run uses the same C2 input. Between runs only C3's checks changed (fixes below), never the input.

| Run | C3 version | Scenarios runnable / stub | Tests | False alarms | Bug-5 detected |
|---|---|---|---|---|---|
| 1 | C3-14 base (prompt 0.4.0) | 12 / 0 | 15 | **10 (66.7%)** | 0 |
| 2 | + fix-3 (prompt 0.5.0) | 11 / 1 | 14 | **6 (42.9%)** | 0 |
| 3 | + fix-4 (prompt 0.6.0) | 8 / 4 | 8 | **0 (0%)** | 0 |
| 4 (final) | + fix-5 (checks only) | 8 / 4 | 8 | **0 (0%)** | 0 |

Control (golden example with the planted bug), final version: 2 scenarios, 1 runnable / 1 stub, 1 test,
0 false alarms, **0 bugs detected** (the outline that holds the age-65 row became a stub).

## What caused the false alarms, and what C3 does now

All fixes are generic rules, none is about Express. Each one is a unit test that replays Qwen's real answer
(`test/pilot-fixes.test.ts`).

| Found in | Cause (Qwen's answer) | Tests | C3 now |
|---|---|---|---|
| Run 1 | Quote marks copied into the value: `toBe("\"text/html\"")` | 3 | Unwraps a step value wrapped in quotes |
| Run 1 | A Given value missing from the call: `compileTrust(<hop>)` for "the trust setting 2" | 2 | Rejects the answer: every Given/When value must reach the act (rule 7) |
| Run 1 | Result shape guessed: `result.type`, `result.q`; a returned function compared to `true` | 6 | Field names must come from the Then step (rule 8); the export's **JSDoc** (`@return {Function}`) is shown to the model, never its code |
| Run 2 | A documented `Object` compared whole with a plain value: `toBe("text/html")` | 1 | Rejected with the documented type |
| Run 2 | Invented key in an expected object `{ type: ... }`; whole-object `toEqual` | 1 | Keys checked like fields; objects use `toMatchObject` |
| Run 2 | A value no step states: `"application/json"` | 1 | Rejected (rules 1, 10) |
| Run 2 | One assertion for every row, ignoring `<kind>` (`none` row) | 1 | Rejected (rule 11): use `"<kind>"` or `when` |
| Run 2 | `<hop>` of the When step missing from the act | 2 | Rejected (rule 7) |
| Control | `expect(result).toBe("accepted")`: an outcome label used as the return value | (4) | Rejected with rule 5 (check that `save` was called); Examples cells count as stated values |

## What this shows

1. **Precision:** the final version wrote 9 runnable tests (8 Express + 1 control) and **none fails on correct
   code** (0 false alarms, down from 10 of 15 in run 1).
2. **The price is coverage:** 9 of 14 scenarios (64%) got a runnable test. The other 5 are **stubs with a
   precise reason** for a person, for example *"the documented result is Object, so all of result cannot equal
   0.5"*. C3 does not ship a test it cannot ground in the requirement.
3. **No bug was detected in the final runs.**
   - Express-5: no C2 scenario uses a Windows path like `"c:/"`. The requirement text describes the **buggy**
     behaviour ("a drive letter followed by `:` and `\`"), so no test generated from it can catch Bug-5. This is
     a requirement gap (C1/C2), not something C3 should invent.
   - Control: the scenario that would catch the bug (row age=65) became a stub. Qwen answered it correctly with
     the shorter prompt of fix-2 (7 correct tests on the golden code), but with the longer 0.6.0 prompt it
     wrote per-row checks that the checks reject. **Small models get worse as the prompt grows.**
4. **Routing:** in run 1 all 12 scenarios were routed runnable with confidence 1.000 although 10 tests were
   wrong: a failing test was trusted as a "possible bug". The confidence formula (0.1.0, `calibrated: false`)
   needs this pilot data to be calibrated.

## Panel question: "What if the requirement does not contain enough information for the expected output?"

C3 never works out the expected value from the code. Values come only from the steps and the Examples table;
the shape of the result may come from the function's **documentation** (JSDoc). If neither is enough, the
answer fails the checks and the scenario becomes a stub with the reason. Run 4 has 4 such stubs on Express-5.

## Limits

- One BugsJS bug (Express-5); Hessian.js-8 and Shields-4 have no C2 input yet.
- The C2 input is hand-written (by C4), not C1/C2 output.
- The fixes were found on this pilot, so they must be confirmed on the other bugs in PP2.
- One model (Qwen2.5-Coder-7B), temperature 0, one run per version.

## PP2 next steps

- Run C1 → C2 → C3 on a mini-SRS written from the Express docs (may include `c:/`), and on the other 2 bugs.
- A shorter prompt with one retry message per failed rule (the control run shows prompt length hurts a 7B model).
- Calibrate the confidence threshold with `pilot_results.json` (kept tests vs false alarms per threshold).
- C4 mutation score on the runnable tests (some are weak, e.g. only `typeof result === "function"`).

## Reproduce

```
# subjects (outside the repo)
git clone https://github.com/BugsJS/express.git C:\c3-subjects\express
git -C C:\c3-subjects\express worktree add C:\c3-subjects\express-buggy 999546dfdeb874c20b360ad58346ed07917f3ac0
git -C C:\c3-subjects\express worktree add C:\c3-subjects\express-fixed 23b858835036e728006a69b5895775d5f1f8b459
npm --prefix C:\c3-subjects\express-buggy install --omit=dev --ignore-scripts
npm --prefix C:\c3-subjects\express-fixed install --omit=dev --ignore-scripts

# Express-5 (C2 input copied from c4/feat/html-report: fixtures/pilot-express-5, c2/ + subject-manifest.json)
pnpm c3 run --in runs/express5-pilot-run4 --out runs/express5-pilot-run4 --subject-root C:\c3-subjects\express-buggy
pnpm c3 pilot --run runs/express5-pilot-run4 --buggy C:\c3-subjects\express-buggy --fixed C:\c3-subjects\express-fixed --label "Express-5 run 4"

# control
pnpm c3 run --in runs/example-control4 --out runs/example-control4 --subject-root packages\c3-test-generation\fixtures\pilot\example-off-by-one
pnpm c3 pilot --run runs/example-control4 --buggy packages\c3-test-generation\fixtures\pilot\example-off-by-one --fixed runs\example-control4\subject-src
```

With `LLM_CACHE=readonly` and the same `model-cache/`, the runs repeat exactly without calling the model.
