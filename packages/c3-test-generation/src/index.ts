import type { RunOptions } from './args.js';
import { readC3Inputs } from './input/reader.js';

export type { RunOptions } from './args.js';
export { readC3Inputs, C3InputError } from './input/reader.js';
export type * from './input/types.js';

/**
 * Runnable Test Generation with Explainable Assertions and Mocking.
 * Done so far: C3-03 input reader. Next: C3-04 ts-morph dependency scan.
 */
export async function run(options: RunOptions): Promise<void> {
  if (!options.in) throw new Error('Missing --in <run folder>');
  const inputs = readC3Inputs(options.in);
  console.log(
    `[c3] run ${inputs.runId}: ${inputs.scenarios.length} scenario(s) to build, ${inputs.skipped.length} skipped`,
  );
  for (const s of inputs.scenarios) {
    const rows = s.isOutline ? `, ${s.examples.length} example rows` : '';
    console.log(
      `  ${s.scenarioId} [${s.scenarioType}] ${s.subject.subjectId}:${s.subject.modulePath}${rows}`,
    );
  }
  for (const s of inputs.skipped) console.log(`  skip ${s.scenarioId}: ${s.reason}`);
}
