import fs from 'node:fs';
import path from 'node:path';
import type { RunOptions } from './args.js';
import { loadInputs } from './loader.js';
import { aggregateScores, type Scores } from './scores.js';
import { runStryker } from './stryker.js';

export type { RunOptions } from './args.js';
export { loadInputs } from './loader.js';
export { aggregateScores } from './scores.js';
export { runStryker } from './stryker.js';

/**
 * Requirement-Traceable Mutation Adequacy Attribution.
 * Done so far: input loader (C4-03), StrykerJS run (C4-02) and scores (C4-04).
 * Traces, gaps, recommendations and adequacy_report.json follow in C4-06 to C4-11.
 */
export async function run(options: RunOptions): Promise<Scores> {
  if (!options.in) throw new Error('Missing --in <run folder>');
  const inputs = loadInputs(options.in, options.subjectRoot);
  console.log(
    `[c4] ${inputs.manifest.tests.length} tests for ${inputs.subject.subject_id}; mutating ${inputs.mutate.join(', ')}`,
  );

  const { report } = runStryker(inputs);
  const rawFile = path.join(options.out, 'c4', 'raw', 'mutation.json');
  fs.mkdirSync(path.dirname(rawFile), { recursive: true });
  fs.writeFileSync(rawFile, JSON.stringify(report, null, 2));
  console.log(`[c4] wrote ${rawFile}`);

  const scores = aggregateScores(report, inputs.manifest.tests, inputs.subject.requirement_ids);
  printScores(scores);
  return scores;
}

function printScores({ summary: s, modules, requirements }: Scores): void {
  console.log(
    `[c4] mutants ${s.mutants_total}: killed ${s.killed}, survived ${s.survived}, no coverage ${s.no_coverage}, timeout ${s.timeout}`,
  );
  console.log(`[c4] mutation score ${s.mutation_score}`);
  for (const m of modules) console.log(`[c4]   module ${m.file}: ${m.mutation_score}`);
  for (const r of requirements)
    console.log(
      `[c4]   ${r.requirement_id}: ${r.killed}/${r.killed + r.survived} = ${r.score} (${r.status})`,
    );
}
