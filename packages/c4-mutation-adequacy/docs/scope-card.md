# C4 scope card — Requirement-Traceable Mutation Adequacy Attribution

**Owner:** Shajana G. (IT23164208). **Planner task:** C4-01. **Version:** PP1, 9 Oct 2026.

## Problem

A mutation score tells you how strong a test suite is. It does not tell you which requirement is weak.
C4 connects each mutant to the test, scenario and requirement that should catch it.
Then C4 tells the earlier stage (C1, C2 or C3) what to fix.

## Two headline functions

1. **Traceability:** mutant → Jest test → scenario → requirement (`MUT → TST → SCN → REQ`).
2. **Gap diagnosis and recommendations:** each surviving mutant gets a gap type and evidence.
   C4 ranks the fixes and routes each one to C1, C2 or C3.

## Functional requirements

| FR | Feature | Planner task |
|---|---|---|
| FR1 | Load `c3/test_manifest.json`, `subject-manifest.json` and the subject code. Check them against the shared schemas. | C4-03 |
| FR2 | Run StrykerJS with the Jest runner and `coverageAnalysis: perTest`. Keep `c4/raw/mutation.json`. | C4-02 |
| FR3 | Filter likely equivalent mutants with rules. Log a hand-checked sample. | C4-05 |
| FR4 | Map `coveredBy` / `killedBy` test IDs to Jest names, then to TST, SCN and REQ IDs. Support many-to-many links. | C4-06 |
| FR5 | Give each survivor one gap type: `missing_test`, `weak_assertion`, `untested_branch`, `incomplete_mock`, `missing_boundary`. Add evidence and an explanation. | C4-09 |
| FR6 | Compute scores (overall, per module, per requirement). Write `c4/adequacy_report.json` and an HTML view. | C4-04, C4-11 |
| FR7 | Rank the recommendations by predicted score gain. Route each one to C1, C2 or C3. | C4-10 |
| FR8 | Trace-signal switch: `coverage_only`, `embedding_assisted` (SBERT tie-break), `full`. | C4-07 |

## Input and output

| | Files |
|---|---|
| Input | `c3/test_manifest.json`, `c3/runnable_tests/*.test.js`, `subject-manifest.json`, subject source (`--subject-root`) |
| Output | `c4/adequacy_report.json` (contract `c4.adequacy-report`), `c4/adequacy_report.html`, `c4/raw/mutation.json` |

Command: `c4 run --in runs/<RUN-ID> --subject-root <path> --out runs/<RUN-ID>`.

## Score rules

- `mutation_score` = (killed + timeout) / (killed + timeout + survived + no_coverage). This is the StrykerJS formula.
- `mutation_score_filtered` removes the equivalent survivors from the bottom of the fraction.
- Per requirement: `score` = killed / (killed + survived), for the mutants that a test of that requirement covers or kills.
- Requirement status: `protected` = no survivors; `unprotected` = no mutant traced or none killed; `at_risk` = all other cases.

## Done definition for PP1

- `c4 run` works on the golden example and on the 3 BugsJS pilot subjects.
- `adequacy_report.json` passes `validate.mjs`. The HTML report is readable.
- Every survivor on the golden example and the pilots has a trace to test, scenario and requirement.
- Trace accuracy is measured against a blind ground truth from 2 annotators (C4-08).
- One before/after demo: apply the top recommendation, run again, show the score change (C4-12).

## Out of scope for PP1

- The full C1 → C4 pipeline run by the orchestrator (PP2).
- Automatic application of recommendations by C1, C2 or C3 (PP2).
