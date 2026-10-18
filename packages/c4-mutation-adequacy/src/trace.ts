import type { Gap } from './gap.js';
import type {
  ManifestTest,
  MutantStatus,
  MutationReport,
  Position,
  StrykerMutant,
} from './types.js';

export type TraceSignal = 'coverage' | 'embedding' | 'coverage+embedding' | 'none';

/** Mutant -> test -> scenario -> requirement links (the `trace` object of the C4 contract). */
export interface Trace {
  test_ids: string[];
  scenario_ids: string[];
  requirement_ids: string[];
  signal: TraceSignal;
  confidence?: number;
}

export interface Survivor {
  mutant_id: string;
  file: string;
  location: { start: Position; end: Position };
  mutator: string;
  replacement?: string;
  status: MutantStatus;
  equivalent: boolean;
  trace: Trace;
  gap?: Gap | null;
}

/** Map StrykerJS test id -> manifest test, joined on the exact Jest full name. */
export function testsByStrykerId(
  report: MutationReport,
  tests: ManifestTest[],
): Map<string, ManifestTest> {
  const byName = new Map(tests.map((t) => [t.jest_full_name, t]));
  const out = new Map<string, ManifestTest>();
  for (const file of Object.values(report.testFiles ?? {})) {
    for (const t of file.tests) {
      const m = byName.get(t.name);
      if (m) out.set(t.id, m);
    }
  }
  return out;
}

/** StrykerJS test names with no manifest test. Each one is a C3 `jest_full_name` that does not match. */
export function unmatchedTestNames(report: MutationReport, tests: ManifestTest[]): string[] {
  const names = new Set(tests.map((t) => t.jest_full_name));
  return Object.values(report.testFiles ?? {})
    .flatMap((f) => f.tests.map((t) => t.name))
    .filter((n) => !names.has(n));
}

const sortedUnique = (ids: string[]) => [...new Set(ids)].sort();

/**
 * Trace one mutant through the tests that cover or kill it (coverage signal).
 * Confidence is 1 for one requirement and goes down when the mutant links to more requirements.
 */
export function traceMutant(m: StrykerMutant, byStrykerId: Map<string, ManifestTest>): Trace {
  const tests = [...(m.coveredBy ?? []), ...(m.killedBy ?? [])]
    .map((id) => byStrykerId.get(id))
    .filter((t): t is ManifestTest => !!t);
  if (tests.length === 0)
    return { test_ids: [], scenario_ids: [], requirement_ids: [], signal: 'none' };
  const requirement_ids = sortedUnique(tests.map((t) => t.requirement_id));
  return {
    test_ids: sortedUnique(tests.map((t) => t.test_id)),
    scenario_ids: sortedUnique(tests.map((t) => t.scenario_id)),
    requirement_ids,
    signal: 'coverage',
    confidence: Math.round((1 / requirement_ids.length) * 10000) / 10000,
  };
}

/** Every `Survived` and `NoCoverage` mutant with its trace, in the C4 contract shape. */
export function buildSurvivors(
  report: MutationReport,
  byStrykerId: Map<string, ManifestTest>,
  equivalentIds: Set<string> = new Set(),
): Survivor[] {
  return Object.entries(report.files).flatMap(([file, f]) =>
    f.mutants
      .filter((m) => m.status === 'Survived' || m.status === 'NoCoverage')
      .map((m) => ({
        mutant_id: m.id,
        file,
        location: m.location,
        mutator: m.mutatorName,
        ...(m.replacement !== undefined && { replacement: m.replacement }),
        status: m.status,
        equivalent: equivalentIds.has(m.id),
        trace: traceMutant(m, byStrykerId),
      })),
  );
}
