# C4-07 comparison: trace-signal modes on the Express-5 pilot

Subject: BugsJS Express-5, `lib/utils.js`. Input: `fixtures/pilot-express-5`. Ground truth: `docs/annotation/express-5/ground-truth.json`.
Embedding model: `nomic-embed-text` on a local Ollama server (`LLM_BASE_URL=http://localhost:11434/v1`).

```sh
LLM_BASE_URL=http://localhost:11434/v1 EMBEDDING_MODEL=nomic-embed-text \
  pnpm c4 run --in fixtures/pilot-express-5 --subject-root /tmp/c4-subjects/express --out <out> --trace-signal <mode>
npx tsx scripts/trace-accuracy.ts <out>/c4/adequacy_report.json docs/annotation/express-5/ground-truth.json
```

## Results (58 survivors)

| Mode | Coverage traces | Embedding traces | No trace | Requirement | Scenario | Tests | Gap type | Recommendations |
|---|---|---|---|---|---|---|---|---|
| `coverage_only` | 27 | 0 | 31 | **0.845** | **0.759** | 0.983 | 0.759 | 14 |
| `embedding_assisted` | 27 | 0 | 31 | **0.845** | **0.759** | 0.983 | 0.759 | 14 |
| `full` | 27 | 31 | 0 | 0.552 | 0.466 | 0.983 | 0.759 | 21 |

The mutation score is 0.5766 in all modes. The modes change only the traces.

## What the results show

- `embedding_assisted` gives the same output as `coverage_only`. No covered mutant links to more than 1 requirement, so there is no tie to break.
- `full` traces the 31 mutants that no test runs. 7 of them have a requirement in the ground truth, and `full` finds the correct requirement for all 7.
- The other 24 have no requirement in the ground truth, for example `compileQueryParser` and `etag`. `full` cannot give `none`, so it always picks a requirement. These 24 are errors.
- The `full` confidence is 0.21 to 0.27 for right and wrong traces. With 5 requirements, 0.2 means no preference. A confidence limit cannot separate right from wrong traces.

## Conclusion

- Keep `coverage_only` as the default.
- `full` is useful only when every part of the module belongs to a requirement. On this pilot, most untested code has no requirement.
- A future change can let `full` give `none` when the best similarity is below a fixed cosine value. That value must come from data, not from this pilot only.
- The tie-break of `embedding_assisted` needs a subject where 1 function serves more than 1 requirement.
