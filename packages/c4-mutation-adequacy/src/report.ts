import fs from 'node:fs';
import path from 'node:path';
import { assertMatchesSchema } from './contracts.js';
import type { C4Inputs } from './loader.js';
import { buildRecommendations, type Recommendation } from './recommend.js';
import type { RequirementScore, Scores } from './scores.js';
import type { TraceSignalMode } from './signal.js';
import type { Survivor } from './trace.js';

export const REPORT_SCHEMA_VERSION = '1.0.0';

const toolVersion = (
  JSON.parse(fs.readFileSync(new URL('../package.json', import.meta.url), 'utf8')) as {
    version: string;
  }
).version;

export interface AdequacyReport {
  contract: 'c4.adequacy-report';
  schema_version: string;
  producer: { component: 'C4'; tool_version: string };
  run_id: string;
  generated_at: string;
  upstream: { contract: string; path: string; schema_version: string }[];
  subject_id: string;
  config: {
    trace_signal: TraceSignalMode;
    stryker_version: string;
    coverage_analysis: 'perTest';
    mutate: string[];
    embedding_model?: string;
  };
  summary: Omit<Scores['summary'], 'other'>;
  requirements: RequirementScore[];
  survivors: Survivor[];
  recommendations: Recommendation[];
}

/** Build `c4/adequacy_report.json`. Survivors with a gap give the recommendations. */
export function buildReport(
  inputs: C4Inputs,
  strykerVersion: string,
  scores: Scores,
  survivors: Survivor[],
  generatedAt = new Date(),
  signal: { mode: TraceSignalMode; embeddingModel?: string } = { mode: 'coverage_only' },
): AdequacyReport {
  const { other: _other, ...summary } = scores.summary;
  return {
    contract: 'c4.adequacy-report',
    schema_version: REPORT_SCHEMA_VERSION,
    producer: { component: 'C4', tool_version: toolVersion },
    run_id: inputs.manifest.run_id,
    generated_at: generatedAt.toISOString(),
    upstream: [
      {
        contract: 'c3.test-manifest',
        path: 'c3/test_manifest.json',
        schema_version: inputs.manifest.schema_version,
      },
    ],
    subject_id: inputs.subject.subject_id,
    config: {
      trace_signal: signal.mode,
      stryker_version: strykerVersion,
      coverage_analysis: 'perTest',
      mutate: inputs.mutate,
      ...(signal.embeddingModel !== undefined && { embedding_model: signal.embeddingModel }),
    },
    summary,
    requirements: scores.requirements,
    survivors,
    recommendations: buildRecommendations(
      survivors,
      scores.summary,
      inputs.subject.requirement_ids,
    ),
  };
}

/** Check the report against the contract, then write it. Throws when the report is not valid. */
export function writeReport(report: AdequacyReport, outDir: string): string {
  assertMatchesSchema(report, 'c4-adequacy-report.schema.json', 'c4/adequacy_report.json');
  const file = path.join(outDir, 'c4', 'adequacy_report.json');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(report, null, 2) + '\n');
  return file;
}
