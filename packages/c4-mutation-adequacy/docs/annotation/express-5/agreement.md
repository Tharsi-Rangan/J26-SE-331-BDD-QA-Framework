# Annotation agreement: labels-haiku vs labels-sonnet

Survivors labelled by both: 58.

| Field | Agreement | Cohen kappa |
|---|---|---|
| `requirement_id` | 0.931 | 0.906 |
| `scenario_id` | 0.983 | 0.975 |
| `test_ids` | 0.983 | 0.974 |
| `gap_type` | 0.845 | 0.761 |

## Disagreements (13)

| Mutant | Field | labels-haiku | labels-sonnet |
|---|---|---|---|
| 3 | `gap_type` | equivalent | missing_test |
| 6 | `gap_type` | weak_assertion | equivalent |
| 28 | `scenario_id` | SCN-EXPRESS-001-02 | SCN-EXPRESS-001-01 |
| 30 | `gap_type` | untested_branch | missing_test |
| 47 | `gap_type` | weak_assertion | untested_branch |
| 61 | `gap_type` | untested_branch | missing_test |
| 64 | `requirement_id` | none | REQ-EXPRESS-003 |
| 66 | `requirement_id` | none | REQ-EXPRESS-003 |
| 67 | `requirement_id` | none | REQ-EXPRESS-003 |
| 67 | `gap_type` | untested_branch | missing_test |
| 72 | `gap_type` | untested_branch | missing_test |
| 73 | `test_ids` | TST-EXPRESS-003-01-02,TST-EXPRESS-003-02-01 | TST-EXPRESS-003-01-01,TST-EXPRESS-003-01-02,TST-EXPRESS-003-01-03,TST-EXPRESS-003-02-01 |
| 124 | `gap_type` | weak_assertion | untested_branch |
| 128 | `requirement_id` | none | REQ-EXPRESS-004 |
| 128 | `gap_type` | untested_branch | missing_test |
