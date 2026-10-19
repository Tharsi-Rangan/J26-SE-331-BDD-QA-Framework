// C3-08 fixed templates: typed assertion slots -> Jest code. The model never writes these lines.
//   equality     expect(<actual>).toBe(<expected>)  (toEqual for objects/arrays/row values; toBeFalsy for false, toBeNull for null)
//   exception    expect(() => <act>).toThrow(<Error>)   (async: await expect(<act>).rejects.toThrow(...))
//   state_change expect(<mock>).toHaveBeenCalledWith(...) / .toHaveBeenCalled() / .not.toHaveBeenCalled() / .toHaveBeenCalledTimes(n)
//   range        expect(<actual>).toBeGreaterThanOrEqual(<min>); expect(<actual>).toBeLessThanOrEqual(<max>)
import { isPrimitiveLiteral, renderValue } from './expr.js';
import type { AssertionSlot, PlanCase, ScenarioPlan } from './plan.js';

/** Why each template choice was made (documented in the README; the PP1 demo shows it). */
export const TEMPLATE_NOTES = {
  falsy:
    'expected false -> toBeFalsy(): JavaScript predicates often return undefined for "no", which the requirement also means.',
};

function equality(a: AssertionSlot, params: ReadonlyMap<string, string>): string {
  const actual = a.actual ?? 'result';
  if (a.expected === false) return `expect(${actual}).toBeFalsy();`;
  if (a.expected === null) return `expect(${actual}).toBeNull();`;
  const exp = renderValue(a.expected, params);
  return isPrimitiveLiteral(exp)
    ? `expect(${actual}).toBe(${exp});`
    : `expect(${actual}).toEqual(${exp});`;
}

function range(a: AssertionSlot, params: ReadonlyMap<string, string>): string[] {
  const actual = a.actual ?? 'result';
  const out: string[] = [];
  if (a.min != null)
    out.push(
      `expect(${actual}).${a.min_inclusive === false ? 'toBeGreaterThan' : 'toBeGreaterThanOrEqual'}(${renderValue(a.min, params)});`,
    );
  if (a.max != null)
    out.push(
      `expect(${actual}).${a.max_inclusive === false ? 'toBeLessThan' : 'toBeLessThanOrEqual'}(${renderValue(a.max, params)});`,
    );
  return out;
}

function stateChange(a: AssertionSlot, params: ReadonlyMap<string, string>): string {
  const t = a.target!;
  switch (a.change) {
    case 'called_with':
      return `expect(${t}).toHaveBeenCalledWith(${(a.args ?? []).map((v) => renderValue(v, params)).join(', ')});`;
    case 'called':
      return `expect(${t}).toHaveBeenCalled();`;
    case 'not_called':
      return `expect(${t}).not.toHaveBeenCalled();`;
    case 'called_times':
      return `expect(${t}).toHaveBeenCalledTimes(${a.times ?? 1});`;
    default:
      throw new Error(`unknown state change ${String(a.change)}`);
  }
}

function errorArg(a: AssertionSlot): string {
  if (a.error) return a.error;
  if (a.message) return JSON.stringify(a.message);
  return '';
}

/**
 * The body of one test (one case of a plan), as lines without indentation.
 * Throwing cases run the act inside expect(); the others store it in `result` first.
 */
export function renderCase(plan: ScenarioPlan, c: PlanCase): string[] {
  if (!plan.act_code) throw new Error(`${plan.scenario_id}: no act (plan ${plan.source})`);
  const params = new Map(Object.entries(plan.params));
  const slots = c.assertions.map((i) => plan.assertions[i]!);
  const act = plan.act_code;
  const lines: string[] = [];
  const exc = slots.filter((a) => a.category === 'exception');
  if (exc.length) {
    for (const a of exc) {
      lines.push(
        plan.await
          ? `await expect(${act}).rejects.toThrow(${errorArg(a)});`
          : `expect(() => ${act}).toThrow(${errorArg(a)});`,
      );
      if (a.error && a.message)
        lines.push(
          plan.await
            ? `await expect(${act}).rejects.toThrow(${JSON.stringify(a.message)});`
            : `expect(() => ${act}).toThrow(${JSON.stringify(a.message)});`,
        );
    }
  } else {
    lines.push(`const result = ${plan.await ? 'await ' : ''}${act};`);
  }
  for (const a of slots) {
    if (a.category === 'equality') lines.push(equality(a, params));
    else if (a.category === 'range') lines.push(...range(a, params));
    else if (a.category === 'state_change') lines.push(stateChange(a, params));
  }
  return lines;
}
