# C4-05 equivalent-mutant spot-check log

The owner checks a sample of mutants by hand and records the result here.
"C4 says" is the filter output. "Hand check" is the owner's decision. A draft reading is marked "draft".

## Rules

- **E1-same-code:** the mutated code has the same tokens as the original code.
- **E2-log-only:** the change is only in the arguments of a log call that has no side effects.

## Sample

| Date | Subject | Mutant | Mutator and change | C4 says | Hand check | Note |
|---|---|---|---|---|---|---|
| 14 Oct | SUB-EX-1 (golden) | 12 | StringLiteral `'age out of range'` -> `""` | not equivalent | not equivalent (draft, to confirm) | The error message changes. A caller can see it, so it is a real survivor (weak assertion). |
| 14 Oct | SUB-EX-1 + added log line | 14 | StringLiteral `'saving user with age'` -> `""` | E2-log-only | equivalent (draft, to confirm) | Only the log text changes. REQ-EX-001 says nothing about logs. |
| | SUB-EXPRESS-5 | | | | | Fill after the pilot run. |
| | SUB-HESSIAN-8 | | | | | Fill after the pilot run. |
| | SUB-SHIELDS-4 | | | | | Fill after the pilot run. |

## How the second row was made

Copy the golden folder and add `console.log('saving user with age', age);` before the `return` in
`subject-src/src/registration.js`. Then run `pnpm c4 run --in <copy> --out <copy>`.
Result: 15 mutants, 2 survived, `mutation_score` 0.8667, `mutation_score_filtered` 0.9286.

## Summary

| Subject | Survivors | Flagged | Hand-checked | Agree |
|---|---|---|---|---|
| SUB-EX-1 + log line | 2 | 1 | 0 (2 drafts) | - |
