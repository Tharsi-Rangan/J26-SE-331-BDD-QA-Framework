import fs from 'node:fs';
import path from 'node:path';
import type { RunOptions } from './args.js';
import { loadInputs } from './loader.js';
import { buildReport, writeReport, type AdequacyReport } from './report.js';
import { aggregateScores, type Scores } from './scores.js';
import { runStryker } from './stryker.js';
import { buildSurvivors, testsByStrykerId, unmatchedTestNames, type Survivor } from './trace.js';

export type { RunOptions } from './args.js';
export { loadInputs } from './loader.js';
export { buildReport, writeReport } from './report.js';
export { aggregateScores } from './scores.js';
export { runStryker } from './stryker.js';
export { buildSurvivors, testsByStrykerId, traceMutant } from './trace.js';

/**
 * Requirement-Traceable Mutation Adequacy Attribution.
 * Done so far: loader (C4-03), StrykerJS run (C4-02), scores (C4-04) and traces (C4-06).
 */
export async function run(options: RunOptions): Promise<AdequacyReport> {
  if (!options.in) throw new Error('Missing --in <run folder>');
  const inputs = loadInputs(options.in, options.subjectRoot);
  console.log(
    `[c4] ${inputs.manifest.tests.length} tests for ${inputs.subject.subject_id}; mutating ${inputs.mutate.join(', ')}`,
  );

  const { report: mutation, strykerVersion } = runStryker(inputs);
  const rawFile = path.join(options.out, 'c4', 'raw', 'mutation.json');
  fs.mkdirSync(path.dirname(rawFile), { recursive: true });
  fs.writeFileSync(rawFile, JSON.stringify(mutation, null, 2));
  console.log(`[c4] wrote ${rawFile}`);

  const tests = inputs.manifest.tests;
  for (const name of unmatchedTestNames(mutation, tests))
    console.warn(`[c4] warning: no manifest test has jest_full_name "${name}"`);

  const scores = aggregateScores(mutation, tests, inputs.subject.requirement_ids);
  const survivors = buildSurvivors(mutation, testsByStrykerId(mutation, tests));
  printScores(scores);
  printSurvivors(survivors);

  const report = buildReport(inputs, strykerVersion, scores, survivors);
  console.log(`[c4] wrote ${writeReport(report, options.out)}`);
  return report;
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

function printSurvivors(survivors: Survivor[]): void {
  for (const s of survivors) {
    const t = s.trace;
    const chain =
      t.signal === 'none'
        ? 'no test covers it'
        : `${t.test_ids.join(', ')} -> ${t.scenario_ids.join(', ')} -> ${t.requirement_ids.join(', ')}`;
    console.log(
      `[c4]   mutant ${s.mutant_id} ${s.status} ${s.mutator} at ${s.file}:${s.location.start.line}: ${chain}`,
    );
  }
}
