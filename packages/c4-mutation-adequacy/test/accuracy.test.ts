import { describe, expect, test } from 'vitest';
import { accuracyMarkdown, traceAccuracy, type TruthLabel } from '../src/accuracy.js';
import type { Survivor, Trace } from '../src/trace.js';

const surv = (
  id: string,
  trace: Partial<Trace>,
  gap: string | null,
  equivalent = false,
): Survivor => ({
  mutant_id: id,
  file: 'src/m.js',
  location: { start: { line: 1, column: 1 }, end: { line: 1, column: 5 } },
  mutator: 'ConditionalExpression',
  status: 'Survived',
  equivalent,
  trace: { test_ids: [], scenario_ids: [], requirement_ids: [], signal: 'coverage', ...trace },
  gap: gap ? { type: gap as never, evidence: 'x', explanation: 'x' } : null,
});

const label = (id: string, req: string, scn: string, tests: string[], gap: string): TruthLabel => ({
  mutant_id: id,
  requirement_id: req,
  scenario_id: scn,
  test_ids: tests,
  gap_type: gap,
});

describe('c4 traceAccuracy', () => {
  test('counts each field on its own', () => {
    const r = traceAccuracy(
      [
        surv(
          '1',
          {
            requirement_ids: ['REQ-A-001', 'REQ-B-001'],
            scenario_ids: ['SCN-A-001-01', 'SCN-B-001-01'],
            test_ids: ['T2', 'T1'],
          },
          'weak_assertion',
        ),
        surv('2', {}, 'missing_test'),
      ],
      [
        label('1', 'REQ-A-001', 'SCN-B-001-01', ['T1', 'T2'], 'untested_branch'),
        label('2', 'REQ-A-001', 'none', [], 'missing_test'),
      ],
    );
    expect(r.n).toBe(2);
    expect(r.accuracy).toEqual({ requirement: 0.5, scenario: 1, tests: 1, gap_type: 0.5 });
    expect(r.gapConfusion).toEqual({
      untested_branch: { weak_assertion: 1 },
      missing_test: { missing_test: 1 },
    });
  });

  test('requirement uses only the first requirement of C4', () => {
    const r = traceAccuracy(
      [surv('1', { requirement_ids: ['REQ-B-001', 'REQ-A-001'] }, 'weak_assertion')],
      [label('1', 'REQ-A-001', 'none', [], 'weak_assertion')],
    );
    expect(r.rows[0].correct.requirement).toBe(false);
  });

  test('an equivalent survivor counts as the equivalent gap type', () => {
    const r = traceAccuracy(
      [surv('1', {}, null, true)],
      [label('1', 'none', 'none', [], 'equivalent')],
    );
    expect(r.rows[0].c4.gap_type).toBe('equivalent');
    expect(r.accuracy.gap_type).toBe(1);
  });

  test('lists survivors and labels that do not match', () => {
    const r = traceAccuracy(
      [surv('1', {}, 'missing_test'), surv('2', {}, 'missing_test')],
      [
        label('2', 'none', 'none', [], 'missing_test'),
        label('9', 'none', 'none', [], 'missing_test'),
      ],
    );
    expect(r.n).toBe(1);
    expect(r.unmatched).toEqual({ survivors: ['1'], labels: ['9'] });
  });

  test('the Markdown has the table, the confusion matrix and the wrong rows', () => {
    const md = accuracyMarkdown(
      traceAccuracy(
        [surv('1', {}, 'weak_assertion')],
        [label('1', 'none', 'none', [], 'untested_branch')],
      ),
      'T',
    );
    expect(md).toContain('| gap_type | 0 / 1 | 0 |');
    expect(md).toContain('| untested_branch | 0 | 1 |');
    expect(md).toContain('| 1 | gap_type | weak_assertion | untested_branch |');
  });
});
