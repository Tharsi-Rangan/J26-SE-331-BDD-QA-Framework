import type { GapType } from './gap.js';
import { round4, type Summary } from './scores.js';
import type { Survivor } from './trace.js';

export type Route = 'C1' | 'C2' | 'C3';

/** One item of `recommendations` in the C4 contract. */
export interface Recommendation {
  rec_id: string;
  rank: number;
  route_to: Route;
  gap_type: GapType;
  target: { requirement_id?: string; scenario_id?: string; test_id?: string };
  mutant_ids: string[];
  action: string;
  predicted_impact: number;
  status: 'open' | 'applied' | 'rejected';
}

/** Below this trace confidence, C4 does not trust the requirement link of an untested mutant. */
const WEAK_LINK = 0.5;

/** Order of gap types when two recommendations have the same predicted impact. */
const GAP_ORDER: GapType[] = [
  'missing_test',
  'untested_branch',
  'missing_boundary',
  'weak_assertion',
  'incomplete_mock',
];

interface Group {
  gap_type: GapType;
  route_to: Route;
  target: Recommendation['target'];
  survivors: Survivor[];
}

/**
 * The stage that must fix the gap.
 * C1 when no requirement clearly covers the code, C2 when a scenario is missing, C3 when the test is weak.
 */
export function routeFor(s: Survivor, gap: GapType): Route {
  if (gap === 'missing_test') {
    if (s.trace.requirement_ids.length === 0) return 'C2';
    if (s.trace.signal === 'embedding' && (s.trace.confidence ?? 0) < WEAK_LINK) return 'C1';
    return s.trace.scenario_ids.length > 0 ? 'C3' : 'C2';
  }
  return gap === 'weak_assertion' || gap === 'incomplete_mock' ? 'C3' : 'C2';
}

const lines = (g: Group) =>
  [...new Set(g.survivors.map((s) => `${s.file}:${s.location.start.line}`))].join(', ');

const quote = (code: string) => '`' + code + '`';

/** A message-only change that a `toThrow(ErrorClass)` check does not see. */
const isMessageGap = (g: Group) =>
  g.survivors.every(
    (s) =>
      s.mutator === 'StringLiteral' &&
      /\)\.toThrow\(\s*[A-Za-z_$][\w$]*\s*\)/.test(s.gap?.evidence ?? ''),
  );

function actionFor(g: Group): string {
  const { requirement_id: req, scenario_id: scn, test_id: tst } = g.target;
  const evidence = g.survivors[0].gap?.evidence ?? '';
  switch (g.gap_type) {
    case 'missing_test':
      if (g.route_to === 'C1')
        return `No requirement clearly covers ${lines(g)}. Add this behaviour to ${req} or mark the code as out of scope.`;
      if (g.route_to === 'C3') return `Generate a test for ${scn} that runs ${lines(g)}.`;
      return `Add a scenario to ${req} that runs ${lines(g)} and checks its result.`;
    case 'untested_branch':
      return `Add a scenario to ${req} that takes the branch ${quote(evidence)} at ${lines(g)} and checks its result.`;
    case 'missing_boundary':
      return `Add Examples rows to ${scn ?? req} at the exact limit of ${quote(evidence)} (${lines(g)}).`;
    case 'incomplete_mock':
      return `In ${tst}, check the call ${quote(evidence)} with toHaveBeenCalledWith, or make the mock return a value that depends on the input.`;
    case 'weak_assertion':
      if (isMessageGap(g))
        return `In ${tst}, add the error message to ${quote(evidence)}. If ${req} does not define the message, ask C1 to add it or mark the mutant as not relevant.`;
      return `In ${tst}, make ${quote(evidence)} check the value that ${lines(g)} produces.`;
  }
}

/**
 * Group the survivors with a gap by gap type and target, then rank the groups.
 * `predicted_impact` is the gain in `mutation_score_filtered` when the tests kill every mutant of the group.
 * When a survivor has no requirement and the subject has exactly one, C4 targets that requirement.
 */
export function buildRecommendations(
  survivors: Survivor[],
  summary: Summary,
  subjectRequirementIds: string[],
): Recommendation[] {
  const groups = new Map<string, Group>();
  for (const s of survivors) {
    if (!s.gap) continue;
    const req =
      s.trace.requirement_ids[0] ??
      (subjectRequirementIds.length === 1 ? subjectRequirementIds[0] : undefined);
    if (!req) continue;
    const route_to = routeFor(s, s.gap.type);
    const target: Recommendation['target'] = {
      requirement_id: req,
      ...(s.trace.scenario_ids[0] !== undefined && { scenario_id: s.trace.scenario_ids[0] }),
      ...(s.trace.test_ids[0] !== undefined && { test_id: s.trace.test_ids[0] }),
    };
    const key = [s.gap.type, route_to, target.requirement_id, target.scenario_id].join('|');
    const g = groups.get(key) ?? { gap_type: s.gap.type, route_to, target, survivors: [] };
    g.survivors.push(s);
    groups.set(key, g);
  }

  const valid =
    summary.killed +
    summary.timeout +
    summary.survived +
    summary.no_coverage -
    summary.equivalent_filtered;
  const impact = (g: Group) => (valid > 0 ? round4(g.survivors.length / valid) : 0);

  return [...groups.values()]
    .map((g) => ({ g, impact: impact(g) }))
    .sort(
      (a, b) =>
        b.impact - a.impact ||
        GAP_ORDER.indexOf(a.g.gap_type) - GAP_ORDER.indexOf(b.g.gap_type) ||
        (a.g.target.requirement_id ?? '').localeCompare(b.g.target.requirement_id ?? '') ||
        (a.g.target.scenario_id ?? '').localeCompare(b.g.target.scenario_id ?? ''),
    )
    .map(({ g, impact }, i) => ({
      rec_id: `REC-${String(i + 1).padStart(3, '0')}`,
      rank: i + 1,
      route_to: g.route_to,
      gap_type: g.gap_type,
      target: g.target,
      mutant_ids: g.survivors.map((s) => s.mutant_id),
      action: actionFor(g),
      predicted_impact: impact,
      status: 'open' as const,
    }));
}
