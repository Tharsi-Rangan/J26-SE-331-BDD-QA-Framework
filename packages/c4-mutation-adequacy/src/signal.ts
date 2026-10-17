import { cosine, type Embedder } from './embedding.js';
import type { Survivor } from './trace.js';
import type { MutationReport, ScenarioMetadata } from './types.js';

export type TraceSignalMode = 'coverage_only' | 'embedding_assisted' | 'full';
export const TRACE_SIGNAL_MODES: TraceSignalMode[] = [
  'coverage_only',
  'embedding_assisted',
  'full',
];

/** Source lines above and below the mutant that go into its embedding text. */
const CONTEXT_LINES = 2;

/** Requirement and scenario texts that C4 compares with the mutated code. */
export interface TraceTexts {
  requirements: Map<string, string>;
  scenarios: { scenario_id: string; requirement_id: string; text: string }[];
}

/** Requirement text = the text C2 used (or the feature name) plus the names of its scenarios. */
export function traceTexts(meta: ScenarioMetadata): TraceTexts {
  const requirements = new Map<string, string>();
  for (const f of meta.features) {
    const names = meta.scenarios
      .filter((s) => s.requirement_id === f.requirement_id)
      .map((s) => s.scenario_name);
    requirements.set(
      f.requirement_id,
      [f.requirement_text_used ?? f.feature_name, ...names].join('\n'),
    );
  }
  const scenarios = meta.scenarios.map((s) => ({
    scenario_id: s.scenario_id,
    requirement_id: s.requirement_id,
    text: s.scenario_name,
  }));
  return { requirements, scenarios };
}

/** The mutated source lines with some context, plus the mutator and its replacement. */
export function mutantText(s: Survivor, source = ''): string {
  const lines = source.split('\n');
  const from = Math.max(0, s.location.start.line - 1 - CONTEXT_LINES);
  const code = lines.slice(from, s.location.end.line + CONTEXT_LINES).join('\n');
  return `${code}\n${s.mutator}${s.replacement !== undefined ? ` -> ${s.replacement}` : ''}`;
}

const round4 = (n: number) => Math.round(n * 10000) / 10000;

/** Share of the top similarity in the sum. Equal similarities give 1/n, the coverage-only value. */
function topShare(sims: number[]): number {
  const pos = sims.map((x) => Math.max(0, x));
  const sum = pos.reduce((a, b) => a + b, 0);
  return round4(sum === 0 ? 1 / sims.length : Math.max(...pos) / sum);
}

/**
 * Apply the embedding signal to the coverage traces.
 * `embedding_assisted` ranks the requirements of a mutant that links to more than one;
 * `full` also traces mutants with no coverage to the most similar requirement.
 */
export async function applyTraceSignal(
  survivors: Survivor[],
  mode: TraceSignalMode,
  report: MutationReport,
  texts: TraceTexts,
  embed: Embedder,
): Promise<Survivor[]> {
  if (mode === 'coverage_only') return survivors;
  const ties = survivors.filter((s) => s.trace.requirement_ids.length > 1);
  const uncovered = mode === 'full' ? survivors.filter((s) => s.trace.signal === 'none') : [];
  if (ties.length + uncovered.length === 0 || texts.requirements.size === 0) return survivors;

  const reqIds = [...texts.requirements.keys()];
  const scenarios = uncovered.length > 0 ? texts.scenarios : [];
  const targets = [...ties, ...uncovered];
  const vectors = await embed([
    ...reqIds.map((id) => texts.requirements.get(id)!),
    ...scenarios.map((s) => s.text),
    ...targets.map((s) => mutantText(s, report.files[s.file]?.source)),
  ]);
  const reqVec = new Map(reqIds.map((id, i) => [id, vectors[i]]));
  const scnVec = scenarios.map((s, i) => ({ ...s, vec: vectors[reqIds.length + i] }));
  const mutVec = new Map(targets.map((s, i) => [s, vectors[reqIds.length + scenarios.length + i]]));
  const sim = (s: Survivor, id: string) => {
    const v = reqVec.get(id);
    return v ? cosine(mutVec.get(s)!, v) : 0;
  };

  return survivors.map((s) => {
    if (ties.includes(s)) {
      const ranked = s.trace.requirement_ids
        .map((id) => ({ id, sim: sim(s, id) }))
        .sort((a, b) => b.sim - a.sim || a.id.localeCompare(b.id));
      return {
        ...s,
        trace: {
          ...s.trace,
          requirement_ids: ranked.map((r) => r.id),
          signal: 'coverage+embedding',
          confidence: topShare(ranked.map((r) => r.sim)),
        },
      };
    }
    if (uncovered.includes(s)) {
      const sims = reqIds.map((id) => sim(s, id));
      const best = reqIds[sims.indexOf(Math.max(...sims))];
      const scn = scnVec
        .filter((x) => x.requirement_id === best)
        .map((x) => ({ id: x.scenario_id, sim: cosine(mutVec.get(s)!, x.vec) }))
        .sort((a, b) => b.sim - a.sim)[0];
      return {
        ...s,
        trace: {
          test_ids: [],
          scenario_ids: scn ? [scn.id] : [],
          requirement_ids: [best],
          signal: 'embedding',
          confidence: topShare(sims),
        },
      };
    }
    return s;
  });
}
