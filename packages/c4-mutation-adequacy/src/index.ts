import fs from 'node:fs';
import path from 'node:path';
import type { RunOptions } from './args.js';
import { embedderFromEnv } from './embedding.js';
import { findEquivalentMutants } from './equivalent.js';
import { classifyGaps } from './gap.js';
import { writeHtml } from './html.js';
import { loadInputs, loadMockDecisions, loadScenarioMetadata } from './loader.js';
import { buildReport, writeReport, type AdequacyReport } from './report.js';
import { aggregateScores, type Scores } from './scores.js';
import { applyTraceSignal, traceTexts } from './signal.js';
import { preflightProblems, runPreflight } from './preflight.js';
import { prepareWorkDir, runStryker } from './stryker.js';
import { buildSurvivors, testsByStrykerId, unmatchedTestNames, type Survivor } from './trace.js';

export type { RunOptions } from './args.js';
export { findEquivalentMutants } from './equivalent.js';
export { classifyGap, classifyGaps } from './gap.js';
export { renderHtml, writeHtml } from './html.js';
export { buildRecommendations, routeFor } from './recommend.js';
export { loadInputs, loadMockDecisions, loadScenarioMetadata } from './loader.js';
export { buildReport, writeReport } from './report.js';
export { aggregateScores } from './scores.js';
export { applyTraceSignal, traceTexts } from './signal.js';
export { preflightProblems, runPreflight, summarizePreflight } from './preflight.js';
export { runStryker } from './stryker.js';
export { buildSurvivors, testsByStrykerId, traceMutant } from './trace.js';

/**
 * Requirement-Traceable Mutation Adequacy Attribution.
 * Done so far: loader (C4-03), preflight of the C3 tests, StrykerJS run (C4-02), scores (C4-04), equivalent filter (C4-05)
 * traces (C4-06), trace-signal modes (C4-07), gap classifier (C4-09), recommendations (C4-10) and HTML view (C4-11).
 */
export async function run(options: RunOptions): Promise<AdequacyReport> {
  if (!options.in) throw new Error('Missing --in <run folder>');
  const inputs = loadInputs(options.in, options.subjectRoot);
  const embedding = options.traceSignal === 'coverage_only' ? undefined : embedderFromEnv();
  const texts = embedding ? traceTexts(loadScenarioMetadata(options.in)) : undefined;
  console.log(
    `[c4] ${inputs.manifest.tests.length} tests for ${inputs.subject.subject_id}; mutating ${inputs.mutate.join(', ')}`,
  );

  const work = prepareWorkDir(inputs);
  const preflight = runPreflight(inputs, work, options.out);
  if (preflight.status === 'fail')
    throw new Error(
      `Preflight failed, so C4 did not run StrykerJS. Work folder kept at ${work}\n  ` +
        preflightProblems(preflight).join('\n  '),
    );

  const { report: mutation, strykerVersion } = runStryker(inputs, console.log, work);
  const rawFile = path.join(options.out, 'c4', 'raw', 'mutation.json');
  fs.mkdirSync(path.dirname(rawFile), { recursive: true });
  fs.writeFileSync(rawFile, JSON.stringify(mutation, null, 2));
  console.log(`[c4] wrote ${rawFile}`);

  const tests = inputs.manifest.tests;
  for (const name of unmatchedTestNames(mutation, tests))
    console.warn(`[c4] warning: no manifest test has jest_full_name "${name}"`);

  const equivalent = findEquivalentMutants(mutation);
  const equivalentFile = path.join(options.out, 'c4', 'equivalent_mutants.json');
  fs.writeFileSync(equivalentFile, JSON.stringify(equivalent, null, 2) + '\n');
  for (const e of equivalent)
    console.log(`[c4]   equivalent: mutant ${e.mutant_id} (${e.rule}) ${e.reason}`);
  console.log(`[c4] ${equivalent.length} likely equivalent mutants; wrote ${equivalentFile}`);

  const equivalentIds = new Set(equivalent.map((e) => e.mutant_id));
  const scores = aggregateScores(mutation, tests, inputs.subject.requirement_ids, equivalentIds);
  const coverageSurvivors = buildSurvivors(
    mutation,
    testsByStrykerId(mutation, tests),
    equivalentIds,
  );
  const tracedSurvivors =
    embedding && texts
      ? await applyTraceSignal(
          coverageSurvivors,
          options.traceSignal,
          mutation,
          texts,
          embedding.embed,
        )
      : coverageSurvivors;
  console.log(`[c4] trace signal ${options.traceSignal}`);
  const survivors = classifyGaps(tracedSurvivors, {
    report: mutation,
    tests,
    testSource: (file) => {
      const f = path.join(inputs.inDir, file);
      return fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : undefined;
    },
    mockDecisions: loadMockDecisions(inputs.inDir),
  });
  printScores(scores);
  printSurvivors(survivors);

  const report = buildReport(inputs, strykerVersion, scores, survivors, new Date(), {
    mode: options.traceSignal,
    embeddingModel: embedding?.model,
  });
  for (const r of report.recommendations)
    console.log(
      `[c4]   ${r.rec_id} -> ${r.route_to} ${r.gap_type} (+${r.predicted_impact}): ${r.action}`,
    );
  console.log(`[c4] wrote ${writeReport(report, options.out)}`);
  console.log(`[c4] wrote ${writeHtml(report, options.out)}`);
  return report;
}

function printScores({ summary: s, modules, requirements }: Scores): void {
  console.log(
    `[c4] mutants ${s.mutants_total}: killed ${s.killed}, survived ${s.survived}, no coverage ${s.no_coverage}, timeout ${s.timeout}`,
  );
  console.log(`[c4] mutation score ${s.mutation_score} (filtered ${s.mutation_score_filtered})`);
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
    if (s.gap) console.log(`[c4]     gap ${s.gap.type}: ${s.gap.explanation}`);
  }
}
