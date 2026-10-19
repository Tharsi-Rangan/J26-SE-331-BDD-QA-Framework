import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, test } from 'vitest';
import type { Gap, GapType } from '../src/gap.js';
import { buildRecommendations, routeFor } from '../src/recommend.js';
import type { Summary } from '../src/scores.js';
import type { Survivor, Trace } from '../src/trace.js';

const golden = path.resolve(
  import.meta.dirname,
  '../../contracts/fixtures/golden/example-registration',
);

// 20 valid mutants, so each killed survivor adds 0.05 to the score.
const summary: Summary = {
  mutants_total: 20,
  killed: 14,
  survived: 4,
  no_coverage: 2,
  timeout: 0,
  other: 0,
  equivalent_filtered: 0,
  mutation_score: 0.7,
  mutation_score_filtered: 0.7,
};

const covered = (req = 'REQ-A-001', scn = 'SCN-A-001-01', tst = 'TST-A-001-01-01'): Trace => ({
  test_ids: [tst],
  scenario_ids: [scn],
  requirement_ids: [req],
  signal: 'coverage',
  confidence: 1,
});
const none: Trace = { test_ids: [], scenario_ids: [], requirement_ids: [], signal: 'none' };

const surv = (
  id: string,
  type: GapType,
  trace: Trace,
  extra: Partial<Survivor> & { evidence?: string } = {},
): Survivor => {
  const { evidence = 'if (x > 10) {', ...rest } = extra;
  const gap: Gap = { type, evidence, explanation: 'x' };
  return {
    mutant_id: id,
    file: 'src/m.js',
    location: {
      start: { line: Number(id) + 1, column: 1 },
      end: { line: Number(id) + 1, column: 9 },
    },
    mutator: 'ConditionalExpression',
    status: trace.signal === 'none' ? 'NoCoverage' : 'Survived',
    equivalent: false,
    trace,
    gap,
    ...rest,
  };
};

describe('c4 routeFor', () => {
  test('weak_assertion and incomplete_mock go to C3', () => {
    expect(routeFor(surv('1', 'weak_assertion', covered()), 'weak_assertion')).toBe('C3');
    expect(routeFor(surv('1', 'incomplete_mock', covered()), 'incomplete_mock')).toBe('C3');
  });

  test('untested_branch and missing_boundary go to C2', () => {
    expect(routeFor(surv('1', 'untested_branch', covered()), 'untested_branch')).toBe('C2');
    expect(routeFor(surv('1', 'missing_boundary', covered()), 'missing_boundary')).toBe('C2');
  });

  test('missing_test: C2 with no scenario, C3 with a scenario, C1 with a weak embedding link', () => {
    expect(routeFor(surv('1', 'missing_test', none), 'missing_test')).toBe('C2');
    const scn: Trace = {
      ...none,
      requirement_ids: ['REQ-A-001'],
      scenario_ids: ['SCN-A-001-01'],
      signal: 'embedding',
      confidence: 0.8,
    };
    expect(routeFor(surv('1', 'missing_test', scn), 'missing_test')).toBe('C3');
    expect(routeFor(surv('1', 'missing_test', { ...scn, confidence: 0.3 }), 'missing_test')).toBe(
      'C1',
    );
  });
});

describe('c4 buildRecommendations', () => {
  test('groups survivors with the same gap and scenario, and ranks by predicted impact', () => {
    const recs = buildRecommendations(
      [
        surv('1', 'missing_boundary', covered()),
        surv('2', 'untested_branch', covered()),
        surv('3', 'untested_branch', covered()),
        surv('4', 'untested_branch', covered('REQ-A-001', 'SCN-A-001-02', 'TST-A-001-02-01')),
      ],
      summary,
      ['REQ-A-001'],
    );
    expect(
      recs.map((r) => [
        r.rec_id,
        r.rank,
        r.gap_type,
        r.target.scenario_id,
        r.mutant_ids,
        r.predicted_impact,
      ]),
    ).toEqual([
      ['REC-001', 1, 'untested_branch', 'SCN-A-001-01', ['2', '3'], 0.1],
      ['REC-002', 2, 'untested_branch', 'SCN-A-001-02', ['4'], 0.05],
      ['REC-003', 3, 'missing_boundary', 'SCN-A-001-01', ['1'], 0.05],
    ]);
    expect(recs.every((r) => r.status === 'open' && r.route_to === 'C2')).toBe(true);
  });

  test('equal impact: missing_test ranks before weak_assertion', () => {
    const recs = buildRecommendations(
      [surv('1', 'weak_assertion', covered()), surv('2', 'missing_test', none)],
      summary,
      ['REQ-A-001'],
    );
    expect(recs.map((r) => r.gap_type)).toEqual(['missing_test', 'weak_assertion']);
  });

  test('an untraced survivor targets the only subject requirement, or is skipped', () => {
    const s = surv('2', 'missing_test', none);
    expect(buildRecommendations([s], summary, ['REQ-A-001'])[0]).toMatchObject({
      route_to: 'C2',
      target: { requirement_id: 'REQ-A-001' },
      action: 'Add a scenario to REQ-A-001 that runs src/m.js:3 and checks its result.',
    });
    expect(buildRecommendations([s], summary, ['REQ-A-001', 'REQ-B-001'])).toEqual([]);
  });

  test('survivors without a gap give no recommendation', () => {
    const s = { ...surv('1', 'weak_assertion', covered()), equivalent: true, gap: null };
    expect(buildRecommendations([s], summary, ['REQ-A-001'])).toEqual([]);
  });

  test('predicted impact leaves equivalent mutants out of the score', () => {
    const recs = buildRecommendations(
      [surv('1', 'weak_assertion', covered())],
      { ...summary, equivalent_filtered: 4 },
      [],
    );
    expect(recs[0].predicted_impact).toBe(0.0625);
  });

  test('each gap type has its own action text', () => {
    const recs = buildRecommendations(
      [
        surv('1', 'incomplete_mock', covered(), { evidence: 'repo.save(x);' }),
        surv('2', 'weak_assertion', covered(), {
          mutator: 'ArithmeticOperator',
          evidence: 'expect(f(3)).toBe(6);',
        }),
      ],
      summary,
      [],
    );
    expect(recs.map((r) => r.action)).toEqual([
      'In TST-A-001-01-01, make `expect(f(3)).toBe(6);` check the value that src/m.js:3 produces.',
      'In TST-A-001-01-01, check the call `repo.save(x);` with toHaveBeenCalledWith, or make the mock return a value that depends on the input.',
    ]);
  });
});

describe('c4 recommendations on the golden example', () => {
  test('REC-001 matches the golden report except for the action wording', () => {
    const goldenRec = (
      JSON.parse(fs.readFileSync(path.join(golden, 'c4/adequacy_report.json'), 'utf8')) as {
        recommendations: Record<string, unknown>[];
      }
    ).recommendations[0];
    const s = surv(
      '12',
      'weak_assertion',
      {
        test_ids: ['TST-EX-001-02-01', 'TST-EX-001-02-06'],
        scenario_ids: ['SCN-EX-001-02'],
        requirement_ids: ['REQ-EX-001'],
        signal: 'coverage',
        confidence: 1,
      },
      {
        mutator: 'StringLiteral',
        evidence:
          "expect(() => registerUser({ age, email: 'test@example.com' })).toThrow(ValidationError);",
      },
    );
    const goldenSummary: Summary = {
      ...summary,
      mutants_total: 14,
      killed: 13,
      survived: 1,
      no_coverage: 0,
    };
    const [rec] = buildRecommendations([s], goldenSummary, ['REQ-EX-001']);
    const { action, ...rest } = rec;
    const { action: _goldenAction, ...goldenRest } = goldenRec;
    expect(rest).toEqual(goldenRest);
    expect(action).toContain('add the error message');
    expect(action).toContain('ask C1');
  });
});
