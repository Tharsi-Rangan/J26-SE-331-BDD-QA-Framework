// C3-05 rule table for mock / no_mock decisions (FR3, SO1).
// The decision ALWAYS comes from a rule, never from the model (contract: "the model only fills behaviour").
// Rules are checked in order; the first one that matches decides. Change RULES_VERSION when a rule changes.
import { LOGGING, packageName, type SideEffect } from '../scan/side-effects.js';
import type { ScannedDependency } from '../scan/types.js';

export const RULES_VERSION = '0.1.0';

/** What a rule looks at for one (scenario, dependency) pair. */
export interface RuleContext {
  dep: ScannedDependency;
  /** The function under test calls it (directly or through local helpers). */
  usedByTarget: boolean;
  /** It runs as soon as the test does require(module). */
  usedAtLoad: boolean;
}

export interface MockRule {
  id: string; // R-nn
  decision: 'mock' | 'no_mock';
  /** The condition in plain words (shown in docs and the PP1 demo). */
  when: string;
  matches(ctx: RuleContext): boolean;
  reason(ctx: RuleContext): string;
}

const effect = (ctx: RuleContext): SideEffect => ctx.dep.sideEffect;
const isLogging = (ctx: RuleContext) => LOGGING.has(packageName(ctx.dep.importSpecifier));
const name = (ctx: RuleContext) =>
  ctx.dep.symbol === 'default'
    ? `'${ctx.dep.importSpecifier}'`
    : `${ctx.dep.importSpecifier}.${ctx.dep.symbol}`;
const basis = (ctx: RuleContext) => ctx.dep.sideEffectBasis;

export const RULES: readonly MockRule[] = [
  {
    id: 'R-01',
    decision: 'mock',
    when: 'the dependency talks to the network',
    matches: (c) => effect(c) === 'network',
    reason: (c) =>
      `${name(c)} talks to the network (${basis(c)}); a test must not depend on a live server.`,
  },
  {
    id: 'R-02',
    decision: 'no_mock',
    when: 'the dependency only writes log or warning output',
    matches: (c) => isLogging(c),
    reason: (c) =>
      `${name(c)} only writes log/warning output (${basis(c)}); it does not change the result, so it stays real.`,
  },
  {
    id: 'R-03',
    decision: 'mock',
    when: 'the dependency uses a database',
    matches: (c) => effect(c) === 'database',
    reason: (c) =>
      `${name(c)} performs database I/O (${basis(c)}); tests must not touch a real database.`,
  },
  {
    id: 'R-04',
    decision: 'mock',
    when: 'the dependency reads the clock or random numbers',
    matches: (c) => effect(c) === 'time' || effect(c) === 'random',
    reason: (c) =>
      `${name(c)} gives a different ${effect(c) === 'time' ? 'time' : 'number'} on every run (${basis(c)}); the test fixes it so the result is repeatable.`,
  },
  {
    id: 'R-05',
    decision: 'mock',
    when: 'the function under test reads or writes files, processes or the environment',
    matches: (c) => effect(c) === 'io' && c.usedByTarget,
    reason: (c) =>
      `${name(c)} does file/process I/O inside the function under test (${basis(c)}); the test gives it fixed data instead of the real machine.`,
  },
  {
    id: 'R-06',
    decision: 'no_mock',
    when: 'the I/O happens only while the module loads (reading the project’s own files)',
    matches: (c) => effect(c) === 'io' && !c.usedByTarget && c.usedAtLoad,
    reason: (c) =>
      `${name(c)} only runs while the module loads (${basis(c)}), reading files that are part of the checked-out project, so it stays real.`,
  },
  {
    id: 'R-07',
    decision: 'no_mock',
    when: 'the dependency has no side effect',
    matches: (c) => effect(c) === 'none',
    reason: (c) =>
      `${name(c)} has no side effect (${basis(c)}); its real behaviour is part of what the requirement checks.`,
  },
  {
    id: 'R-08',
    decision: 'no_mock',
    when: 'the side effect is unknown (kept real and flagged for review)',
    matches: () => true,
    reason: (c) =>
      `${name(c)} has an unknown side effect (${basis(c)}); it stays real so no behaviour is hidden. Flagged for review.`,
  },
];

/** Apply the rule table to one dependency. Always returns a rule (R-08 catches everything). */
export function decide(ctx: RuleContext): { rule: MockRule; reason: string } {
  const rule = RULES.find((r) => r.matches(ctx))!;
  return { rule, reason: rule.reason(ctx) };
}
