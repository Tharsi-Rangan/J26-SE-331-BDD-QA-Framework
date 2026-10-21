# C4 trace accuracy (SUB-EXPRESS-5, coverage_only)

Survivors compared: 58.

| Field | Correct | Accuracy |
|---|---|---|
| requirement | 49 / 58 | 0.8448 |
| scenario | 44 / 58 | 0.7586 |
| tests | 57 / 58 | 0.9828 |
| gap_type | 44 / 58 | 0.7586 |

## Gap type: truth (rows) against C4 (columns)

| Truth | equivalent | missing_boundary | missing_test | untested_branch | weak_assertion |
|---|---|---|---|---|---|
| equivalent | 0 | 0 | 1 | 0 | 0 |
| missing_boundary | 0 | 1 | 0 | 0 | 0 |
| missing_test | 0 | 0 | 30 | 0 | 0 |
| untested_branch | 0 | 0 | 0 | 8 | 7 |
| weak_assertion | 0 | 2 | 0 | 4 | 5 |

## Survivors with at least one wrong field (24)

| Mutant | Field | C4 | Truth |
|---|---|---|---|
| 1 | requirement | none | REQ-EXPRESS-003 |
| 1 | scenario | none | SCN-EXPRESS-003-01 |
| 2 | requirement | none | REQ-EXPRESS-003 |
| 2 | scenario | none | SCN-EXPRESS-003-01 |
| 3 | requirement | none | REQ-EXPRESS-003 |
| 3 | scenario | none | SCN-EXPRESS-003-01 |
| 3 | gap_type | missing_test | equivalent |
| 4 | requirement | none | REQ-EXPRESS-003 |
| 4 | scenario | none | SCN-EXPRESS-003-01 |
| 30 | requirement | none | REQ-EXPRESS-001 |
| 30 | scenario | none | SCN-EXPRESS-001-01 |
| 61 | requirement | none | REQ-EXPRESS-002 |
| 61 | scenario | none | SCN-EXPRESS-002-02 |
| 72 | requirement | none | REQ-EXPRESS-003 |
| 72 | scenario | none | SCN-EXPRESS-003-01 |
| 21 | scenario | SCN-EXPRESS-001-01 | SCN-EXPRESS-001-02 |
| 21 | tests | TST-EXPRESS-001-01-02 | TST-EXPRESS-001-01-02, TST-EXPRESS-001-02-01 |
| 26 | scenario | SCN-EXPRESS-001-02 | SCN-EXPRESS-001-01 |
| 28 | gap_type | weak_assertion | untested_branch |
| 29 | scenario | SCN-EXPRESS-001-02 | SCN-EXPRESS-001-01 |
| 29 | gap_type | weak_assertion | untested_branch |
| 47 | gap_type | weak_assertion | untested_branch |
| 49 | gap_type | untested_branch | weak_assertion |
| 51 | gap_type | missing_boundary | weak_assertion |
| 53 | gap_type | untested_branch | weak_assertion |
| 60 | gap_type | untested_branch | weak_assertion |
| 58 | gap_type | missing_boundary | weak_assertion |
| 57 | gap_type | untested_branch | weak_assertion |
| 64 | requirement | REQ-EXPRESS-003 | none |
| 64 | scenario | SCN-EXPRESS-003-01, SCN-EXPRESS-003-02 | none |
| 66 | requirement | REQ-EXPRESS-003 | none |
| 66 | scenario | SCN-EXPRESS-003-01, SCN-EXPRESS-003-02 | none |
| 66 | gap_type | weak_assertion | untested_branch |
| 73 | gap_type | weak_assertion | untested_branch |
| 98 | scenario | SCN-EXPRESS-004-01, SCN-EXPRESS-004-02, SCN-EXPRESS-004-03 | none |
| 100 | scenario | SCN-EXPRESS-004-01, SCN-EXPRESS-004-02, SCN-EXPRESS-004-03 | none |
| 100 | gap_type | weak_assertion | untested_branch |
| 124 | gap_type | weak_assertion | untested_branch |
