import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, test } from 'vitest';
import { buildSurvivors, testsByStrykerId, traceMutant, unmatchedTestNames } from '../src/trace.js';
import type { ManifestTest, MutationReport, StrykerMutant, TestManifest } from '../src/types.js';

const golden = path.resolve(
  import.meta.dirname,
  '../../contracts/fixtures/golden/example-registration',
);
const readJson = <T>(rel: string) =>
  JSON.parse(fs.readFileSync(path.join(golden, rel), 'utf8')) as T;
const report = readJson<MutationReport>('c4/raw/mutation.json');
const manifest = readJson<TestManifest>('c3/test_manifest.json');
const goldenSurvivors = readJson<{ survivors: Record<string, unknown>[] }>(
  'c4/adequacy_report.json',
).survivors;

const mt = (test_id: string, scenario_id: string, requirement_id: string): ManifestTest => ({
  test_id,
  scenario_id,
  requirement_id,
  file: 'c3/runnable_tests/x.test.js',
  jest_full_name: test_id,
});

const mutant = (
  id: string,
  status: StrykerMutant['status'],
  coveredBy?: string[],
  killedBy?: string[],
): StrykerMutant => ({
  id,
  status,
  mutatorName: 'StringLiteral',
  location: { start: { line: 3, column: 1 }, end: { line: 3, column: 9 } },
  coveredBy,
  killedBy,
});

// Tests of 2 requirements. The 2 REQ-B-001 tests are in the same scenario.
const byId = new Map([
  ['0', mt('TST-A-001-01-01', 'SCN-A-001-01', 'REQ-A-001')],
  ['1', mt('TST-B-001-01-01', 'SCN-B-001-01', 'REQ-B-001')],
  ['2', mt('TST-B-001-01-02', 'SCN-B-001-01', 'REQ-B-001')],
]);

describe('c4 traceMutant', () => {
  test('one mutant covered by tests of two requirements traces to both', () => {
    expect(traceMutant(mutant('1', 'Survived', ['2', '0', '1']), byId)).toEqual({
      test_ids: ['TST-A-001-01-01', 'TST-B-001-01-01', 'TST-B-001-01-02'],
      scenario_ids: ['SCN-A-001-01', 'SCN-B-001-01'],
      requirement_ids: ['REQ-A-001', 'REQ-B-001'],
      signal: 'coverage',
      confidence: 0.5,
    });
  });

  test('killedBy counts as a link and IDs are not repeated', () => {
    const t = traceMutant(mutant('1', 'Killed', ['1'], ['1', '2']), byId);
    expect(t.test_ids).toEqual(['TST-B-001-01-01', 'TST-B-001-01-02']);
    expect(t.scenario_ids).toEqual(['SCN-B-001-01']);
    expect(t.confidence).toBe(1);
  });

  test('a NoCoverage mutant has signal none and no IDs', () => {
    expect(traceMutant(mutant('1', 'NoCoverage'), byId)).toEqual({
      test_ids: [],
      scenario_ids: [],
      requirement_ids: [],
      signal: 'none',
    });
  });

  test('StrykerJS test IDs with no manifest test are left out', () => {
    expect(traceMutant(mutant('1', 'Survived', ['9']), byId).signal).toBe('none');
    expect(traceMutant(mutant('1', 'Survived', ['9', '0']), byId).test_ids).toEqual([
      'TST-A-001-01-01',
    ]);
  });
});

describe('c4 buildSurvivors', () => {
  test('golden example: survivors match the golden adequacy report (without gap)', () => {
    const survivors = buildSurvivors(report, testsByStrykerId(report, manifest.tests));
    const expected = goldenSurvivors.map(({ gap: _gap, ...s }) => s);
    expect(survivors).toEqual(expected);
  });

  test('lists Survived and NoCoverage only, and marks equivalent mutants', () => {
    const r: MutationReport = {
      files: {
        'src/a.js': {
          mutants: [
            mutant('1', 'Killed', ['0'], ['0']),
            mutant('2', 'Survived', ['0']),
            mutant('3', 'NoCoverage'),
            mutant('4', 'Timeout', ['0']),
          ],
        },
      },
    };
    const survivors = buildSurvivors(r, byId, new Set(['2']));
    expect(survivors.map((s) => [s.mutant_id, s.status, s.equivalent])).toEqual([
      ['2', 'Survived', true],
      ['3', 'NoCoverage', false],
    ]);
    expect(survivors[0]).not.toHaveProperty('replacement');
  });
});

describe('c4 unmatchedTestNames', () => {
  test('golden example: every StrykerJS test name is in the manifest', () => {
    expect(unmatchedTestNames(report, manifest.tests)).toEqual([]);
  });

  test('reports a name that C3 wrote differently', () => {
    const r: MutationReport = {
      files: {},
      testFiles: { 'x.test.js': { tests: [{ id: '0', name: 'TST-A-001-01-01 extra' }] } },
    };
    expect(unmatchedTestNames(r, [...byId.values()])).toEqual(['TST-A-001-01-01 extra']);
  });
});
