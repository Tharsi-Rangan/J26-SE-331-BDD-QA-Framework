import type { ManifestTest, MutationReport, StrykerMutant } from './types.js';

// Score formulas are fixed in packages/contracts/README.md ("Key rules"). Keep them in step.

export interface Counts {
  mutants_total: number;
  killed: number;
  survived: number;
  no_coverage: number;
  timeout: number;
  /** CompileError + RuntimeError + Ignored + Pending: not part of the score. */
  other: number;
}

export interface Summary extends Counts {
  equivalent_filtered: number;
  mutation_score: number;
  mutation_score_filtered: number;
}

export interface ModuleScore extends Counts {
  file: string;
  mutation_score: number;
}

export type RequirementStatus = 'protected' | 'at_risk' | 'unprotected';

export interface RequirementScore {
  requirement_id: string;
  mutants_traced: number;
  killed: number;
  survived: number;
  score: number;
  status: RequirementStatus;
}

export interface Scores {
  summary: Summary;
  modules: ModuleScore[];
  requirements: RequirementScore[];
}

export const round4 = (x: number) => Math.round(x * 10000) / 10000;

export const allMutants = (report: MutationReport): StrykerMutant[] =>
  Object.values(report.files).flatMap((f) => f.mutants);

export function countMutants(mutants: StrykerMutant[]): Counts {
  const n = (st: string) => mutants.filter((m) => m.status === st).length;
  const c = {
    mutants_total: mutants.length,
    killed: n('Killed'),
    survived: n('Survived'),
    no_coverage: n('NoCoverage'),
    timeout: n('Timeout'),
  };
  return { ...c, other: c.mutants_total - c.killed - c.survived - c.no_coverage - c.timeout };
}

/** StrykerJS score: detected / valid, where detected = killed + timeout and valid excludes errors and ignored. */
export function mutationScore(c: Counts, equivalent = 0): number {
  const detected = c.killed + c.timeout;
  const valid = detected + c.survived + c.no_coverage - equivalent;
  return valid > 0 ? round4(detected / valid) : 0;
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

export function requirementStatus(
  r: Pick<RequirementScore, 'mutants_traced' | 'killed' | 'survived'>,
): RequirementStatus {
  if (r.mutants_traced === 0 || r.killed === 0) return 'unprotected';
  return r.survived === 0 ? 'protected' : 'at_risk';
}

/**
 * Overall, per-module and per-requirement scores.
 * A mutant is traced to a requirement when a test of that requirement covers or kills it.
 * `requirementIds` lists requirements to report even when no mutant traces to them.
 */
export function aggregateScores(
  report: MutationReport,
  tests: ManifestTest[],
  requirementIds: string[] = [],
  equivalentIds: Set<string> = new Set(),
): Scores {
  const mutants = allMutants(report);
  const counts = countMutants(mutants);
  const summary: Summary = {
    ...counts,
    equivalent_filtered: equivalentIds.size,
    mutation_score: mutationScore(counts),
    mutation_score_filtered: mutationScore(counts, equivalentIds.size),
  };

  const modules = Object.entries(report.files).map(([file, f]) => {
    const c = countMutants(f.mutants);
    return { file, ...c, mutation_score: mutationScore(c) };
  });

  const byId = testsByStrykerId(report, tests);
  const perReq = new Map<string, StrykerMutant[]>(requirementIds.map((id) => [id, []]));
  for (const t of tests) if (!perReq.has(t.requirement_id)) perReq.set(t.requirement_id, []);
  for (const m of mutants) {
    const reqs = new Set(
      [...(m.coveredBy ?? []), ...(m.killedBy ?? [])]
        .map((id) => byId.get(id)?.requirement_id)
        .filter((r): r is string => !!r),
    );
    for (const r of reqs) perReq.get(r)!.push(m);
  }
  const requirements = [...perReq.entries()].map(([requirement_id, ms]) => {
    const killed = ms.filter((m) => m.status === 'Killed' || m.status === 'Timeout').length;
    const survived = ms.filter((m) => m.status === 'Survived').length;
    const r = {
      requirement_id,
      mutants_traced: ms.length,
      killed,
      survived,
      score: killed + survived > 0 ? round4(killed / (killed + survived)) : 0,
    };
    return { ...r, status: requirementStatus(r) };
  });

  return { summary, modules, requirements };
}
