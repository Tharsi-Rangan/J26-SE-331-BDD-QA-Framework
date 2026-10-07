# Jest test conventions (C3 writes, C4 reads)

C4 maps StrykerJS per-test coverage back to requirements using the **test name**.
StrykerJS reports a test as `<describe title> <test title>`, so the name format is part of the contract.

```
describe('[REQ-EX-001] <feature name>', () => {
  test('[SCN-EX-001-02][TST-EX-001-02-03] <scenario name> :: <case>', ...);
});
```

- Exactly one top-level `describe` per requirement, titled `[REQ-...] <feature name>`.
- Every test title starts with `[SCN-...][TST-...]`.
- `test.each` is allowed; put the TST id in the first column and `%s` in the title.
- File name: `c3/runnable_tests/<REQUIREMENT-ID>.test.js`; first line comment `// @requirement REQ-...`.
- Stubs: `c3/test_stubs/<STUB-ID>.stub.js`, using `test.todo('[SCN-...][STB-...] <reason>')` so they never fail CI.
- `test_manifest.json` field `jest_full_name` = the exact name StrykerJS prints.

Checked with StrykerJS 10.0.0 + Jest 29 (`coverageAnalysis: "perTest"`) on the golden example: all 7 test names matched.
