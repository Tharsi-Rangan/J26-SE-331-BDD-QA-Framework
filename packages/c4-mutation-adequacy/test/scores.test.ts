import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, test } from 'vitest';
import {
  aggregateScores,
  countMutants,
  mutationScore,
  requirementStatus,
  testsByStrykerId,
} from '../src/scores.js';
import type { MutationReport, StrykerMutant, TestManifest } from '../src/types.js';

const golden = path.resolve(
  import.meta.dirname,
  '../../contracts/fixtures/golden/example-registration',
);
const readJson = <T>(rel: string) =>
  JSON.parse(fs.readFileSync(path.join(golden, rel), 'utf8')) as T;
const report = readJson<MutationReport>('c4/raw/mutation.json');
const manifest = readJson<TestManifest>('c3/test_manifest.json');
const goldenReport = readJson<{
  summary: Record<string, number>;
  requirements: Record<string, unknown>[];
}>('c4/adequacy_report.json');

const mutant = (
  id: string,
  status: StrykerMutant['status'],
  coveredBy: string[] = [],
): StrykerMutant => ({
  id,
  status,
  mutatorName: 'X',
  location: { start: { line: 1, column: 0 }, end: { line: 1, column: 1 } },
  coveredBy,
});

describe('c4 scores on the golden example', () => {
  const scores = aggregateScores(report, manifest.tests, ['REQ-EX-001']);

  test('summary matches the golden adequacy report', () => {
    const { other, ...summary } = scores.summary;
    expect(other).toBe(0);
    expect(summary).toEqual(goldenReport.summary);
  });

  test('per-requirement row matches the golden adequacy report', () => {
    expect(scores.requirements).toEqual(goldenReport.requirements);
  });

  test('per-module score for the one mutated file', () => {
    expect(scores.modules).toHaveLength(1);
    expect(scores.modules[0]).toMatchObject({
      file: 'subject-src/src/registration.js',
      mutants_total: 14,
      mutation_score: 0.9286,
    });
  });

  test('every StrykerJS test name joins to a manifest test', () => {
    const map = testsByStrykerId(report, manifest.tests);
    expect(map.size).toBe(manifest.tests.length);
    expect(map.get('1')?.test_id).toBe('TST-EX-001-02-01');
  });
});

describe('c4 score formulas', () => {
  test('timeouts count as detected; errors and ignored are left out', () => {
    const c = countMutants([
      mutant('1', 'Killed'),
      mutant('2', 'Timeout'),
      mutant('3', 'Survived'),
      mutant('4', 'NoCoverage'),
      mutant('5', 'CompileError'),
      mutant('6', 'Ignored'),
    ]);
    expect(c).toEqual({
      mutants_total: 6,
      killed: 1,
      survived: 1,
      no_coverage: 1,
      timeout: 1,
      other: 2,
    });
    expect(mutationScore(c)).toBe(0.5);
    expect(mutationScore(c, 1)).toBe(0.6667);
  });

  test('no valid mutants gives score 0', () => {
    expect(mutationScore(countMutants([mutant('1', 'CompileError')]))).toBe(0);
  });

  test('requirement status', () => {
    expect(requirementStatus({ mutants_traced: 0, killed: 0, survived: 0 })).toBe('unprotected');
    expect(requirementStatus({ mutants_traced: 2, killed: 0, survived: 2 })).toBe('unprotected');
    expect(requirementStatus({ mutants_traced: 2, killed: 1, survived: 1 })).toBe('at_risk');
    expect(requirementStatus({ mutants_traced: 2, killed: 2, survived: 0 })).toBe('protected');
  });

  test('a requirement with no traced mutant is still listed', () => {
    const scores = aggregateScores(report, manifest.tests, ['REQ-EX-001', 'REQ-EX-002']);
    expect(scores.requirements.find((r) => r.requirement_id === 'REQ-EX-002')).toEqual({
      requirement_id: 'REQ-EX-002',
      mutants_traced: 0,
      killed: 0,
      survived: 0,
      score: 0,
      status: 'unprotected',
    });
  });

  test('a mutant covered by tests of two requirements counts for both', () => {
    const tests = [
      { ...manifest.tests[0]!, requirement_id: 'REQ-EX-001', jest_full_name: 'a' },
      { ...manifest.tests[1]!, requirement_id: 'REQ-EX-002', jest_full_name: 'b' },
    ];
    const r: MutationReport = {
      files: { 'f.js': { mutants: [mutant('1', 'Survived', ['t1', 't2'])] } },
      testFiles: {
        't.js': {
          tests: [
            { id: 't1', name: 'a' },
            { id: 't2', name: 'b' },
          ],
        },
      },
    };
    const reqs = aggregateScores(r, tests).requirements;
    expect(reqs.map((x) => [x.requirement_id, x.mutants_traced, x.survived])).toEqual([
      ['REQ-EX-001', 1, 1],
      ['REQ-EX-002', 1, 1],
    ]);
  });
});
