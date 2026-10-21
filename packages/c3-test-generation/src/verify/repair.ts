// C3-12 bounded repair loop (FR8, SO4), PP1 version.
// A scenario is repaired only when one of its tests is BROKEN (the failure is in the test itself:
// syntactic/referential/traceability fail, test_error, suite_error). A test that fails because the code under
// test throws or an expect() fails may have found a bug, so it is never "repaired" into passing.
// Each round: the model gets its previous answer and the Jest/check errors, answers again (checked like C3-08),
// all tests are rebuilt and run again. At most MAX_REPAIR_ROUNDS; a scenario still broken after that gets no
// runnable test (never release a broken test) and C3-13 routes it to a stub.
import type { ChatMessage, ModelClient } from '../model/index.js';
import {
  planScenario,
  type AssertionWorkFile,
  type PlanContext,
  type ScenarioPlan,
} from '../assert/plan.js';
import { isBroken, type VerificationWorkFile } from './verify.js';

export const MAX_REPAIR_ROUNDS = 3;

export interface RepairLogEntry {
  scenario_id: string;
  round: number;
  errors: string[];
  answer: 'usable' | 'unusable' | 'no_model';
  fixed: boolean;
}

export interface RepairResult {
  plans: AssertionWorkFile;
  /** scenario_id -> repair rounds used (0..3). */
  rounds: Map<string, number>;
  /** Scenarios still broken after the last round: no runnable test, C3-13 makes a stub. */
  gaveUp: Map<string, string>;
  log: RepairLogEntry[];
}

/** Scenarios with at least one broken test, and the errors to show the model. */
export function brokenScenarios(v: VerificationWorkFile): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const t of v.tests) {
    if (!isBroken(t)) continue;
    const errs = out.get(t.scenario_id) ?? [];
    const msg = [...t.problems, ...(t.message ? [`${t.test_id}: ${t.message}`] : [])];
    for (const m of msg) if (!errs.includes(m)) errs.push(m);
    out.set(t.scenario_id, errs);
  }
  return out;
}

/** The previous answer as the model wrote it (act + assertion slots), for the repair conversation. */
function previousAnswer(p: ScenarioPlan): string {
  return JSON.stringify({ act: p.act, assertions: p.assertions });
}

export function repairMessages(p: ScenarioPlan, errors: string[]): ChatMessage[] {
  return [
    { role: 'assistant', content: previousAnswer(p) },
    {
      role: 'user',
      content:
        'The Jest test built from your answer is broken. The error comes from the test itself, not from the code under test:\n- ' +
        errors.slice(0, 8).join('\n- ') +
        '\nFix "act" or the assertions (for example a wrong property path, a wrong argument shape or a wrong name). ' +
        'Keep checking what the Then steps require. Answer with one corrected JSON object.',
    },
  ];
}

/**
 * Run the repair loop. `rebuild` writes and verifies all tests for a set of plans (C3-10 + C3-11).
 * Returns the final plans: repaired ones replaced, given-up ones marked `failed` with the reason.
 */
export async function repairLoop(
  plans: AssertionWorkFile,
  first: VerificationWorkFile,
  contexts: ReadonlyMap<string, PlanContext>,
  client: ModelClient | undefined,
  rebuild: (plans: AssertionWorkFile) => VerificationWorkFile,
  options: { maxRounds?: number; log?: (line: string) => void } = {},
): Promise<RepairResult> {
  const max = options.maxRounds ?? MAX_REPAIR_ROUNDS;
  const rounds = new Map<string, number>();
  const gaveUp = new Map<string, string>();
  const log: RepairLogEntry[] = [];
  let current = plans;
  let broken = brokenScenarios(first);

  for (let round = 1; round <= max && broken.size && client; round++) {
    const next = new Map(current.plans.map((p) => [p.scenario_id, p]));
    for (const [scId, errors] of broken) {
      rounds.set(scId, round);
      const prev = next.get(scId)!;
      const ctx = contexts.get(scId);
      if (!ctx) {
        log.push({ scenario_id: scId, round, errors, answer: 'unusable', fixed: false });
        continue;
      }
      const p = await planScenario(ctx, client, {
        retries: 0,
        followUp: repairMessages(prev, errors),
        purpose: `C3-12 repair ${round}`,
      });
      log.push({
        scenario_id: scId,
        round,
        errors,
        answer: p.source === 'model' ? 'usable' : 'unusable',
        fixed: false,
      });
      if (p.source === 'model')
        next.set(scId, {
          ...p,
          attempts: prev.attempts + p.attempts,
          problems: [...prev.problems, ...p.problems],
        });
      options.log?.(
        `  round ${round} ${scId}: ${p.source === 'model' ? `new act ${p.act}` : 'answer unusable'}`,
      );
    }
    current = { ...current, plans: current.plans.map((p) => next.get(p.scenario_id) ?? p) };
    const v = rebuild(current);
    const still = brokenScenarios(v);
    for (const e of log.filter((x) => x.round === round)) e.fixed = !still.has(e.scenario_id);
    broken = still;
  }
  if (!client)
    for (const [scId, errors] of broken)
      log.push({ scenario_id: scId, round: 0, errors, answer: 'no_model', fixed: false });

  for (const [scId, errors] of broken) {
    const reason = `still broken after ${rounds.get(scId) ?? 0} repair round(s): ${errors[0] ?? 'unknown error'}`;
    gaveUp.set(scId, reason);
    options.log?.(`  ${scId} gave up: ${reason}`);
  }
  current = {
    ...current,
    plans: current.plans.map((p) =>
      gaveUp.has(p.scenario_id)
        ? { ...p, source: 'failed' as const, problems: [...p.problems, gaveUp.get(p.scenario_id)!] }
        : p,
    ),
  };
  return { plans: current, rounds, gaveUp, log };
}
