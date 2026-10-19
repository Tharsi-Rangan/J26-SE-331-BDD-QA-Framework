// C3-09 strategy selection (FR5). Rule-based, so the same scenario always gets the same strategy and reason.
//   S-01 parametrised   a Scenario Outline: one test.each row per Examples row, with C2's values as-is
//                       (C2's boundary_ref / partition_ref go into test_manifest.json)
//   S-02 factory        any other scenario: one test whose input is built from the Given/When step values
// property_based (fast-check over a C2 numeric range) is planned for PP2: the writer cannot build it yet, so no
// rule picks it; a plain scenario with a numeric range says so in its reason.
import type { C3ScenarioInput } from './input/types.js';

export const STRATEGY_RULES_VERSION = '0.1.0';
export type Strategy = 'parametrised' | 'factory' | 'property_based';

export interface StrategyChoice {
  scenario_id: string;
  strategy: Strategy;
  rule_id: 'S-01' | 'S-02';
  reason: string;
}

interface RangeConstraint {
  constraint_id?: string;
  parameter?: string;
  kind?: string;
  data_type?: string;
  min?: number;
  max?: number;
}

/** Numeric range constraints C2 attached to the scenario. */
function numericRanges(sc: C3ScenarioInput): RangeConstraint[] {
  return ((sc.metadata.constraints ?? []) as RangeConstraint[]).filter(
    (c) =>
      c.kind === 'range' &&
      (c.data_type === 'integer' || c.data_type === 'number' || c.data_type === 'decimal') &&
      (typeof c.min === 'number' || typeof c.max === 'number'),
  );
}

export function chooseStrategy(sc: C3ScenarioInput): StrategyChoice {
  const base = { scenario_id: sc.scenarioId };
  if (sc.isOutline) {
    const bv = sc.examples.filter((r) => r.boundaryRef).length;
    const ep = sc.examples.filter((r) => r.partitionRef).length;
    const refs = bv || ep ? ` (${bv} boundary value and ${ep} partition rows from C2)` : '';
    return {
      ...base,
      strategy: 'parametrised',
      rule_id: 'S-01',
      reason: `Scenario Outline with ${sc.examples.length} Examples rows${refs}; one test.each row per Examples row, C2 values used as-is.`,
    };
  }
  const ranges = numericRanges(sc);
  return {
    ...base,
    strategy: 'factory',
    rule_id: 'S-02',
    reason: ranges.length
      ? `Plain scenario: one test built from the Given/When step values. ${ranges[0]!.parameter ?? 'A parameter'} has a numeric range (${ranges[0]!.constraint_id ?? 'C2'}), so it is a property-based candidate for PP2.`
      : 'Plain scenario: one test built from the Given/When step values.',
  };
}

export function chooseStrategies(scenarios: C3ScenarioInput[]): {
  rules_version: string;
  choices: StrategyChoice[];
} {
  return {
    rules_version: STRATEGY_RULES_VERSION,
    choices: scenarios.map((s) => chooseStrategy(s)),
  };
}
