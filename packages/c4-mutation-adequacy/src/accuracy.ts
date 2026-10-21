import type { Survivor } from './trace.js';

/** One label of `ground-truth.json` (docs/trace-annotation-guideline.md). `none` means no link. */
export interface TruthLabel {
  mutant_id: string;
  requirement_id: string;
  scenario_id: string;
  test_ids: string[];
  gap_type: string;
}

export type AccuracyField = 'requirement' | 'scenario' | 'tests' | 'gap_type';
export const ACCURACY_FIELDS: AccuracyField[] = ['requirement', 'scenario', 'tests', 'gap_type'];

/** C4's answer and the truth for one survivor, as compared strings. */
export interface AccuracyRow {
  mutant_id: string;
  c4: Record<AccuracyField, string>;
  truth: Record<AccuracyField, string>;
  correct: Record<AccuracyField, boolean>;
}

export interface AccuracyResult {
  /** Survivors that have a ground-truth label. */
  n: number;
  /** Survivors with no label, and labels with no survivor. */
  unmatched: { survivors: string[]; labels: string[] };
  accuracy: Record<AccuracyField, number>;
  /** truth gap type -> C4 gap type -> count. */
  gapConfusion: Record<string, Record<string, number>>;
  rows: AccuracyRow[];
}

const round4 = (n: number) => Math.round(n * 10000) / 10000;
const ids = (xs: string[]) => (xs.length ? [...xs].sort().join(', ') : 'none');

/**
 * Compare C4's survivors with the ground truth.
 * Requirement: C4's first requirement must equal the truth. Scenario: the truth must be one of C4's scenarios.
 * Tests: same set. Gap type: an equivalent survivor counts as `equivalent`.
 */
export function traceAccuracy(survivors: Survivor[], truth: TruthLabel[]): AccuracyResult {
  const byId = new Map(truth.map((t) => [t.mutant_id, t]));
  const matched = survivors.filter((s) => byId.has(s.mutant_id));
  const survivorIds = new Set(survivors.map((s) => s.mutant_id));

  const rows = matched.map((s): AccuracyRow => {
    const t = byId.get(s.mutant_id)!;
    const c4 = {
      requirement: s.trace.requirement_ids[0] ?? 'none',
      scenario: ids(s.trace.scenario_ids),
      tests: ids(s.trace.test_ids),
      gap_type: s.equivalent ? 'equivalent' : (s.gap?.type ?? 'none'),
    };
    const tr = {
      requirement: t.requirement_id,
      scenario: t.scenario_id,
      tests: ids(t.test_ids),
      gap_type: t.gap_type,
    };
    return {
      mutant_id: s.mutant_id,
      c4,
      truth: tr,
      correct: {
        requirement: c4.requirement === tr.requirement,
        scenario:
          tr.scenario === 'none'
            ? s.trace.scenario_ids.length === 0
            : s.trace.scenario_ids.includes(tr.scenario),
        tests: c4.tests === tr.tests,
        gap_type: c4.gap_type === tr.gap_type,
      },
    };
  });

  const gapConfusion: AccuracyResult['gapConfusion'] = {};
  for (const r of rows) {
    const line = (gapConfusion[r.truth.gap_type] ??= {});
    line[r.c4.gap_type] = (line[r.c4.gap_type] ?? 0) + 1;
  }
  const share = (f: AccuracyField) =>
    rows.length ? round4(rows.filter((r) => r.correct[f]).length / rows.length) : 0;

  return {
    n: rows.length,
    unmatched: {
      survivors: survivors.filter((s) => !byId.has(s.mutant_id)).map((s) => s.mutant_id),
      labels: truth.filter((t) => !survivorIds.has(t.mutant_id)).map((t) => t.mutant_id),
    },
    accuracy: {
      requirement: share('requirement'),
      scenario: share('scenario'),
      tests: share('tests'),
      gap_type: share('gap_type'),
    },
    gapConfusion,
    rows,
  };
}

/** A Markdown results table, the gap-type confusion matrix and the wrong rows. */
export function accuracyMarkdown(r: AccuracyResult, title: string): string {
  const gaps = [
    ...new Set([
      ...Object.keys(r.gapConfusion),
      ...Object.values(r.gapConfusion).flatMap((x) => Object.keys(x)),
    ]),
  ].sort();
  const wrong = r.rows.filter((x) => ACCURACY_FIELDS.some((f) => !x.correct[f]));
  return [
    `# ${title}`,
    '',
    `Survivors compared: ${r.n}.`,
    '',
    '| Field | Correct | Accuracy |',
    '|---|---|---|',
    ...ACCURACY_FIELDS.map(
      (f) => `| ${f} | ${r.rows.filter((x) => x.correct[f]).length} / ${r.n} | ${r.accuracy[f]} |`,
    ),
    '',
    '## Gap type: truth (rows) against C4 (columns)',
    '',
    `| Truth | ${gaps.join(' | ')} |`,
    `|---|${gaps.map(() => '---').join('|')}|`,
    ...Object.keys(r.gapConfusion)
      .sort()
      .map((t) => `| ${t} | ${gaps.map((g) => r.gapConfusion[t][g] ?? 0).join(' | ')} |`),
    '',
    `## Survivors with at least one wrong field (${wrong.length})`,
    '',
    '| Mutant | Field | C4 | Truth |',
    '|---|---|---|---|',
    ...wrong.flatMap((x) =>
      ACCURACY_FIELDS.filter((f) => !x.correct[f]).map(
        (f) => `| ${x.mutant_id} | ${f} | ${x.c4[f]} | ${x.truth[f]} |`,
      ),
    ),
    '',
  ].join('\n');
}
