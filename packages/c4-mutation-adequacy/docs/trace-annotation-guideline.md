# Trace annotation guideline (C4-08)

This guideline tells an annotator how to label surviving mutants by hand.
The labels are the ground truth for C4 trace accuracy (C4-12).

## Rules

- Work blind. Do not read C4 output: `adequacy_report.json`, `mutation.json`, the `c4 run` log or `src/`.
- Use only the annotation packet: requirements, scenarios, tests, module source and the survivor list.
- Label each survivor on its own. Do not copy a label from a near mutant without checking it.
- Do not talk to the other annotator until both label files are complete.

## Labels for each survivor

| Field | Value | Question |
|---|---|---|
| `requirement_id` | A `REQ-...` ID, or `none` | Which requirement describes the behaviour of the mutated code? Use `none` when no requirement describes it. |
| `scenario_id` | A `SCN-...` ID of that requirement, or `none` | Which scenario should detect this change? Use `none` when no scenario fits. |
| `test_ids` | A list of `TST-...` IDs, can be empty | Which existing tests run the mutated code? |
| `gap_type` | See the next table | Why does no test detect the change? |
| `confidence` | `high`, `medium` or `low` | How sure are you about `requirement_id`? |
| `note` | One short sentence | The reason for the labels. |

## Gap types

| `gap_type` | Use it when |
|---|---|
| `missing_test` | No test runs the mutated code. |
| `weak_assertion` | A test runs the code, but its assertions do not check the changed value. |
| `untested_branch` | A test runs the code, but no test takes the other side of the changed condition or branch. |
| `missing_boundary` | The change moves a limit, and no test uses the exact limit value. |
| `incomplete_mock` | A mocked dependency hides the change. |
| `equivalent` | The change does not change the behaviour. No test can detect it. |

If 2 types fit, choose the one that names the first thing to fix.

## Output

Write a JSON array with one object for each survivor, in the order of the packet:

```json
[
  {
    "mutant_id": "12",
    "requirement_id": "REQ-EX-001",
    "scenario_id": "SCN-EX-001-02",
    "test_ids": ["TST-EX-001-02-01", "TST-EX-001-02-06"],
    "gap_type": "weak_assertion",
    "confidence": "high",
    "note": "The tests check the error type but not the error message."
  }
]
```

## Agreement

- Compare the 2 label files field by field. Report percent agreement and Cohen's kappa for `requirement_id`, `scenario_id` and `gap_type`.
- A person decides each disagreement. The decided labels are the ground truth.
