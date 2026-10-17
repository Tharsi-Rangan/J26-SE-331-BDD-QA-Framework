import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, test } from 'vitest';
import { loadInputs } from '../src/loader.js';
import { buildReport, writeReport } from '../src/report.js';
import { aggregateScores } from '../src/scores.js';
import { buildSurvivors, testsByStrykerId } from '../src/trace.js';
import type { MutationReport } from '../src/types.js';

const golden = path.resolve(
  import.meta.dirname,
  '../../contracts/fixtures/golden/example-registration',
);
const validator = path.resolve(import.meta.dirname, '../../contracts/scripts/validate.mjs');
const temps: string[] = [];

afterEach(() => {
  for (const d of temps.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});

function goldenReport() {
  const inputs = loadInputs(golden);
  const mutation = JSON.parse(
    fs.readFileSync(path.join(golden, 'c4', 'raw', 'mutation.json'), 'utf8'),
  ) as MutationReport;
  const tests = inputs.manifest.tests;
  const scores = aggregateScores(mutation, tests, inputs.subject.requirement_ids);
  const survivors = buildSurvivors(mutation, testsByStrykerId(mutation, tests));
  return buildReport(inputs, '10.0.0', scores, survivors, new Date('2026-10-14T00:00:00Z'));
}

describe('c4 adequacy report', () => {
  test('golden example: header, config and summary', () => {
    const r = goldenReport();
    expect(r).toMatchObject({
      contract: 'c4.adequacy-report',
      producer: { component: 'C4' },
      run_id: 'RUN-FIXTURE-EX-1',
      generated_at: '2026-10-14T00:00:00.000Z',
      subject_id: 'SUB-EX-1',
      config: { trace_signal: 'coverage_only', mutate: ['subject-src/src/registration.js'] },
      summary: { mutants_total: 14, survived: 1, mutation_score: 0.9286 },
      recommendations: [],
    });
    expect(r.summary).not.toHaveProperty('other');
    expect(r.survivors.map((s) => s.trace.requirement_ids)).toEqual([['REQ-EX-001']]);
  });

  test('written report passes validate.mjs in a copy of the golden folder', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'c4-report-'));
    temps.push(dir);
    fs.cpSync(golden, dir, { recursive: true });
    writeReport(goldenReport(), dir);

    const res = spawnSync(process.execPath, [validator, dir], { encoding: 'utf8' });
    expect(res.stdout + res.stderr).toContain('All contract checks passed.');
    expect(res.status).toBe(0);
  });

  test('writeReport refuses a report that breaks the contract', () => {
    const bad = { ...goldenReport(), subject_id: 'not an id' };
    expect(() => writeReport(bad, os.tmpdir())).toThrow(/does not match/);
  });
});
