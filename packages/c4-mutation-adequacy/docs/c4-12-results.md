# C4-12 results: trace accuracy and before/after run (Express-5 pilot)

Subject: BugsJS Express-5, `lib/utils.js`, buggy commit `999546d`. Trace signal: `coverage_only`.
Ground truth: `docs/annotation/express-5/ground-truth.json` (C4-08).

## 1. Trace accuracy against the ground truth

`tsx scripts/trace-accuracy.ts <adequacy_report.json> docs/annotation/express-5/ground-truth.json`

| Field | Correct | Accuracy | Rule |
|---|---|---|---|
| requirement | 49 / 58 | 0.845 | C4's first requirement equals the truth. |
| scenario | 44 / 58 | 0.759 | The truth is one of C4's scenarios. |
| tests | 57 / 58 | 0.983 | Same set of tests. |
| gap type | 44 / 58 | 0.759 | Same gap type. An equivalent survivor counts as `equivalent`. |

Full table, confusion matrix and the wrong rows: `docs/annotation/express-5/accuracy-coverage_only.md`.

### What the errors show

- 7 of the 9 requirement errors are `NoCoverage` mutants. `coverage_only` cannot trace a mutant that no test runs. The `full` mode is for these mutants (C4-07).
- The other 2 requirement errors (64, 66) are code that no requirement text describes. C4 traces them to REQ-EXPRESS-003, because its tests run the code.
- 7 of the 14 scenario errors are the same `NoCoverage` mutants.
- 4 scenario errors (64, 66, 98, 100) are mutants that tests of 2 or 3 scenarios cover. C4 lists all of them, and the truth is `none`.
- 3 scenario errors (21, 26, 29) are mutants where the covering test is in a different scenario from the one that must detect the change.
- The gap classifier mixes up `untested_branch` and `weak_assertion` (11 of 14 gap errors). It decides from the mutator only. For example, mutants 49, 53, 57 and 60 are in the parameter loop, and the true gap is the weak `toBeDefined()` check.
- The ground truth has 1 known error. For mutant 21, both annotators list TST-EXPRESS-001-02-01. That test cannot run `'\\' === path[2]`, because `&&` stops at `path[1]`. C4 is right here, and the ground truth is not changed.

## 2. Before/after: apply REC-001

REC-001 from the first run:

| Field | Value |
|---|---|
| Route | C2 |
| Gap type | `untested_branch` |
| Target | REQ-EXPRESS-002, SCN-EXPRESS-002-02 |
| Mutants | 49, 53, 56, 57, 60 |
| Predicted impact | +0.0365 |
| Action | Add a scenario to REQ-EXPRESS-002 that takes the parameter branch at `lib/utils.js:143` and `:145` and checks its result. |

Applied change, as C2 and C3 would make it: 1 new scenario, SCN-EXPRESS-002-04 "Parse the parameters of a full type", and 1 new test, TST-EXPRESS-002-04-01.
The test checks the full result of `normalizeType('text/html; charset=utf-8; q=0.5')`.
Fixture: `fixtures/pilot-express-5-rec-001` (`scripts/pilot-express-5-fixture.py <out> <subject-manifest.json> rec-001`).

| | Before | After | Change |
|---|---|---|---|
| Killed | 79 | 90 | +11 |
| Survived | 29 | 19 | -10 |
| No coverage | 29 | 28 | -1 |
| Mutation score | 0.5766 | 0.6569 | **+0.0803** |
| REQ-EXPRESS-002 score | 0.6071 | 0.9655 | +0.3584 |
| Recommendations | 14 | 12 | -2 |

- All 5 REC-001 mutants are killed. The predicted gain was +0.0365.
- The new test also kills 6 other mutants: 51, 54, 55, 58, 59 (REC-002 and REC-005) and 61 (no coverage before).
- So the real gain is larger than the prediction. `predicted_impact` counts only the mutants of the recommendation, so it is a lower bound.
- No new survivors. The scores of the other requirements do not change.
