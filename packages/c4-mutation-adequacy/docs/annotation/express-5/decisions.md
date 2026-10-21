# Decisions: Express-5 annotation disagreements (C4-08)

Annotator A: Claude Haiku. Annotator B: Claude Sonnet. Both worked blind and on their own (see `agreement.md`).
A person decides each row below. The "Decided" column has the final value. Shajana G. accepted all suggestions on 18 Oct 2026.
All labels that both annotators agree on go into the ground truth unchanged.

| Mutant | Field | Haiku | Sonnet | Suggested | Reason | Decided |
|---|---|---|---|---|---|---|
| 3 | `gap_type` | `equivalent` | `missing_test` | `equivalent` | `etag(b, {})` and `etag(b, {weak: false})` give the same value (checked with Node). No test can detect it. | `equivalent` |
| 6 | `gap_type` | `weak_assertion` | `equivalent` | `weak_assertion` | Not equivalent: with the `hex` encoding, the string and the Buffer give different ETags (checked with Node). No test passes an encoding. | `weak_assertion` |
| 28 | `scenario_id` | `SCN-EXPRESS-001-02` | `SCN-EXPRESS-001-01` | `SCN-EXPRESS-001-02` | The mutant only changes the result for an empty path. An empty path is relative, so the "Reject relative paths" scenario must detect it. | `SCN-EXPRESS-001-02` |
| 30 | `gap_type` | `untested_branch` | `missing_test` | `missing_test` | Status is `NoCoverage`. The guideline says `missing_test` when no test runs the code. | `missing_test` |
| 47 | `gap_type` | `weak_assertion` | `untested_branch` | `untested_branch` | The test input has a space after `;`, so the changed regex gives the same result. No assertion can see it with this input. | `untested_branch` |
| 61 | `gap_type` | `untested_branch` | `missing_test` | `missing_test` | Status is `NoCoverage`. | `missing_test` |
| 64 | `requirement_id` | `none` | `REQ-EXPRESS-003` | `none` | REQ-EXPRESS-003 does not name a function as an ETag setting. | `none` |
| 66 | `requirement_id` | `none` | `REQ-EXPRESS-003` | `none` | Same as mutant 64. | `none` |
| 67 | `requirement_id` | `none` | `REQ-EXPRESS-003` | `none` | Same as mutant 64. | `none` |
| 67 | `gap_type` | `untested_branch` | `missing_test` | `missing_test` | Status is `NoCoverage`. | `missing_test` |
| 72 | `gap_type` | `untested_branch` | `missing_test` | `missing_test` | Status is `NoCoverage`. | `missing_test` |
| 73 | `test_ids` | 003-01-02, 003-02-01 | all 4 REQ-EXPRESS-003 tests | Haiku | The `switch` checks the `'strong'` label only for `'weak'` and `'bogus'`. `true` and `false` match an earlier case. | Haiku |
| 124 | `gap_type` | `weak_assertion` | `untested_branch` | `untested_branch` | Same as mutant 47, with `,` in place of `;`. | `untested_branch` |
| 128 | `requirement_id` | `none` | `REQ-EXPRESS-004` | `none` | REQ-EXPRESS-004 does not describe a missing trust setting. | `none` |
| 128 | `gap_type` | `untested_branch` | `missing_test` | `missing_test` | Status is `NoCoverage`. | `missing_test` |

## Notes for the guideline

- Mutants 47 and 124 fit no gap type well. The test runs the code, but its input does not reach the changed behaviour. A future guideline can add a type for a missing input class.
- Haiku gave `untested_branch` to 5 `NoCoverage` mutants. A future guideline can say first: "`NoCoverage` is always `missing_test`, unless the mutant is `equivalent`".
