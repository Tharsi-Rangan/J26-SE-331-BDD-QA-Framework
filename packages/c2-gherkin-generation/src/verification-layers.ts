import { AstBuilder, GherkinClassicTokenMatcher, Parser } from '@cucumber/gherkin';
import {
  IdGenerator,
  type GherkinDocument,
  type Scenario as GherkinScenario,
} from '@cucumber/messages';

export type CheckStatus = 'pass' | 'fail' | 'skipped';

export interface Constraint {
  constraint_id: string;
  parameter: string;
  kind?: string;
  type?: string;
  data_type?: 'integer' | 'number' | 'string' | 'date' | 'boolean';
  min?: number;
  max?: number;
  min_inclusive?: boolean;
  max_inclusive?: boolean;
  step?: number | null;
  source_phrase?: string;
}

export interface BoundaryValue {
  boundary_id?: string;
  constraint_id: string;
  position?: string;
  value: unknown;
  expected: 'accept' | 'reject';
}

export interface EquivalencePartition {
  constraint_id: string;
  partition_id?: string;
  representative_value?: unknown;
  representative?: unknown;
  validity?: 'valid' | 'invalid';
  description?: string;
  valid?: boolean;
  expected?: 'accept' | 'reject';
}

export interface ExampleRow {
  row_index?: number;
  values: Record<string, unknown>;
  boundary_ref?: string;
  partition_ref?: string;
}

export interface ScenarioForVerification {
  scenario_id?: string;
  requirement_id?: string;
  gherkin?: string;
  feature_text?: string;
  scenario_text?: string;
  scenario_name?: string;
  scenario_type?: string;
  is_outline?: boolean;
  constraints: Constraint[];
  boundary_values: BoundaryValue[];
  equivalence_partitions: EquivalencePartition[];
  examples?: ExampleRow[];
  verification?: {
    syntax?: CheckStatus;
    requirement_consistency?: { status: CheckStatus };
    ep_coverage?: CheckStatus;
    bva_coverage?: CheckStatus;
    completeness?: CheckStatus;
    fully_verified?: boolean;
    notes?: string;
  };
}

export interface VerificationResult {
  requirement_consistency: {
    status: CheckStatus;
    notes: string;
  };
  ep_coverage: CheckStatus;
  bva_coverage: CheckStatus;
  completeness: CheckStatus;
  fully_verified: boolean;
  notes: string[];
}

function getFeatureScenarios(document: GherkinDocument): GherkinScenario[] {
  const scenarios: GherkinScenario[] = [];

  for (const child of document.feature?.children ?? []) {
    if (child.scenario) scenarios.push(child.scenario);
    for (const ruleChild of child.rule?.children ?? []) {
      if (ruleChild.scenario) scenarios.push(ruleChild.scenario);
    }
  }

  return scenarios;
}

export function isInsideConstraint(value: unknown, constraint: Constraint): boolean {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return false;
  }

  if (typeof constraint.min === 'number') {
    const minInclusive = constraint.min_inclusive !== false;

    if (minInclusive ? value < constraint.min : value <= constraint.min) {
      return false;
    }
  }

  if (typeof constraint.max === 'number') {
    const maxInclusive = constraint.max_inclusive !== false;

    if (maxInclusive ? value > constraint.max : value >= constraint.max) {
      return false;
    }
  }

  return true;
}

function hasSameValue(actual: unknown, expected: unknown): boolean {
  if (actual === expected) {
    return true;
  }

  if (typeof actual === 'number' && typeof expected === 'string' && expected.trim() !== '') {
    return actual === Number(expected);
  }

  if (typeof actual === 'string' && typeof expected === 'number' && actual.trim() !== '') {
    return Number(actual) === expected;
  }

  return false;
}

function getPartitionRepresentative(partition: EquivalencePartition): unknown {
  if (partition.representative_value !== undefined) {
    return partition.representative_value;
  }

  return partition.representative;
}

function matchesExpectedOutcome(actual: unknown, expected: 'accept' | 'reject'): boolean {
  if (typeof actual !== 'string') {
    return false;
  }

  const normalized = actual.trim().toLowerCase();

  if (expected === 'accept') {
    return normalized === 'accepted' || normalized === 'accept';
  }

  return normalized === 'rejected' || normalized === 'reject';
}

export function checkEpCoverage(scenario: ScenarioForVerification): CheckStatus {
  if (scenario.constraints.length === 0 || scenario.equivalence_partitions.length === 0) {
    return 'skipped';
  }

  const examples = scenario.examples ?? [];

  if (examples.length === 0) {
    return 'fail';
  }

  const everyPartitionCovered = scenario.equivalence_partitions.every((partition) => {
    const constraint = scenario.constraints.find(
      (item) => item.constraint_id === partition.constraint_id,
    );

    if (!constraint) {
      return false;
    }

    const representative = getPartitionRepresentative(partition);

    if (representative === undefined) {
      return false;
    }

    const representativeIsValid = isInsideConstraint(representative, constraint);
    const declaredValidity =
      partition.validity ??
      (partition.valid === true ? 'valid' : partition.valid === false ? 'invalid' : undefined);

    if (declaredValidity === undefined) {
      return false;
    }

    if (declaredValidity === 'valid' && !representativeIsValid) {
      return false;
    }

    if (declaredValidity === 'invalid' && representativeIsValid) {
      return false;
    }

    return examples.some((example) => {
      const representativeIsPresent = hasSameValue(
        example.values[constraint.parameter],
        representative,
      );
      const otherConstraintsAreValid = scenario.constraints.every((otherConstraint) =>
        otherConstraint.constraint_id === constraint.constraint_id
          ? true
          : isInsideConstraint(example.values[otherConstraint.parameter], otherConstraint),
      );

      return (
        representativeIsPresent &&
        otherConstraintsAreValid &&
        matchesExpectedOutcome(
          example.values.result,
          declaredValidity === 'valid' ? 'accept' : 'reject',
        )
      );
    });
  });

  return everyPartitionCovered ? 'pass' : 'fail';
}

export function checkBvaCoverage(scenario: ScenarioForVerification): CheckStatus {
  if (scenario.constraints.length === 0 || scenario.boundary_values.length === 0) {
    return 'skipped';
  }

  const examples = scenario.examples ?? [];

  if (examples.length === 0) {
    return 'fail';
  }

  const allBoundariesVerified = scenario.boundary_values.every((boundary) => {
    const constraint = scenario.constraints.find(
      (item) => item.constraint_id === boundary.constraint_id,
    );

    if (!constraint) {
      return false;
    }

    const matchingRows = examples.filter((example) => {
      const value = example.values[constraint.parameter];

      return value !== undefined && hasSameValue(value, boundary.value);
    });

    if (matchingRows.length === 0) {
      return false;
    }

    // Other constrained parameters must be valid to isolate this boundary.
    const isolatedRows = matchingRows.filter((example) =>
      scenario.constraints.every((otherConstraint) => {
        if (otherConstraint.constraint_id === constraint.constraint_id) {
          return true;
        }

        return isInsideConstraint(example.values[otherConstraint.parameter], otherConstraint);
      }),
    );

    if (isolatedRows.length === 0) {
      return false;
    }

    return isolatedRows.every((example) =>
      matchesExpectedOutcome(example.values.result, boundary.expected),
    );
  });

  return allBoundariesVerified ? 'pass' : 'fail';
}

export function checkCompleteness(
  scenario: ScenarioForVerification,
  featureText?: string,
): CheckStatus {
  const feature =
    featureText ?? scenario.gherkin ?? scenario.feature_text ?? scenario.scenario_text ?? '';

  if (feature.trim() === '') {
    return 'fail';
  }

  const featureLines = feature.split(/\r?\n/);
  let declarationIndex = -1;

  if (scenario.scenario_id !== undefined) {
    const scenarioTag = `@${scenario.scenario_id}`;
    const tagIndex = featureLines.findIndex((line) => line.trim() === scenarioTag);

    if (tagIndex >= 0) {
      declarationIndex = featureLines.findIndex(
        (line, index) => index > tagIndex && /^\s*Scenario(?: Outline)?:/.test(line),
      );
    }
  }

  if (declarationIndex < 0 && scenario.scenario_name !== undefined) {
    const escapedName = scenario.scenario_name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    declarationIndex = featureLines.findIndex((line) =>
      new RegExp(`^\\s*Scenario(?: Outline)?:\\s*${escapedName}\\s*$`).test(line),
    );
  }

  if (declarationIndex < 0) {
    declarationIndex = featureLines.findIndex((line) => /^\s*Scenario(?: Outline)?:/.test(line));
  }

  if (declarationIndex < 0) {
    return 'fail';
  }

  let endIndex = featureLines.length;
  for (let index = declarationIndex + 1; index < featureLines.length; index += 1) {
    if (
      /^\s*Scenario(?: Outline)?:/.test(featureLines[index]) ||
      /^\s*Rule:/.test(featureLines[index])
    ) {
      endIndex = index;
      break;
    }
  }

  const gherkin = featureLines.slice(declarationIndex, endIndex).join('\n');

  if (!/^\s*Scenario(?: Outline)?:/m.test(gherkin)) {
    return 'fail';
  }

  const isOutline = /^\s*Scenario Outline:/m.test(gherkin);

  if (scenario.is_outline !== undefined && scenario.is_outline !== isOutline) {
    return 'fail';
  }

  if (scenario.scenario_id !== undefined && scenario.scenario_id.trim() === '') {
    return 'fail';
  }

  if (scenario.requirement_id !== undefined && scenario.requirement_id.trim() === '') {
    return 'fail';
  }

  if (
    scenario.constraints.some(
      (constraint) =>
        !constraint.constraint_id ||
        !constraint.parameter ||
        (constraint.min === undefined && constraint.max === undefined),
    )
  ) {
    return 'fail';
  }

  if (
    scenario.boundary_values.some(
      (boundary) =>
        !boundary.constraint_id ||
        boundary.value === undefined ||
        !['accept', 'reject'].includes(boundary.expected),
    )
  ) {
    return 'fail';
  }

  if (
    scenario.equivalence_partitions.some(
      (partition) =>
        !partition.constraint_id || getPartitionRepresentative(partition) === undefined,
    )
  ) {
    return 'fail';
  }

  const examples = scenario.examples ?? [];

  if (!isOutline) {
    return examples.length === 0 && scenario.constraints.length === 0 ? 'pass' : 'fail';
  }

  if (examples.length === 0) {
    return 'fail';
  }

  let astScenario;
  try {
    const builder = new AstBuilder(IdGenerator.uuid());
    const matcher = new GherkinClassicTokenMatcher();
    const document = new Parser(builder, matcher).parse(feature);
    astScenario = getFeatureScenarios(document).find(
      (item) => item.location.line === declarationIndex + 1,
    );
  } catch {
    return 'fail';
  }

  const examplesBlocks = astScenario?.examples ?? [];
  if (examplesBlocks.length === 0) return 'fail';

  const tableRows = examplesBlocks.flatMap((block) => {
    const headers = block.tableHeader?.cells.map((cell) => cell.value) ?? [];
    if (
      headers.length === 0 ||
      block.tableBody.length === 0 ||
      scenario.constraints.some((constraint) => !headers.includes(constraint.parameter))
    ) {
      return null;
    }
    return block.tableBody.map((row) => ({
      headers,
      cells: row.cells.map((cell) => cell.value),
    }));
  });

  if (tableRows.some((row) => row === null) || tableRows.length !== examples.length) {
    return 'fail';
  }

  for (const [rowIndex, example] of examples.entries()) {
    if (!example.values || Object.keys(example.values).length === 0) {
      return 'fail';
    }

    const row = tableRows[rowIndex];
    if (
      !row ||
      row.cells.length !== row.headers.length ||
      row.headers.some(
        (header, columnIndex) =>
          example.values[header] === undefined ||
          String(example.values[header]).trim() !== row.cells[columnIndex],
      )
    ) {
      return 'fail';
    }

    for (const constraint of scenario.constraints) {
      if (example.values[constraint.parameter] === undefined) {
        return 'fail';
      }
    }
  }

  return 'pass';
}

export function buildVerificationResult(
  scenario: ScenarioForVerification,
  featureText?: string,
): VerificationResult {
  const requirementConsistency: VerificationResult['requirement_consistency'] = {
    status: 'skipped',
    notes: 'Cross-encoder requirement consistency is not implemented.',
  };
  const epCoverage = checkEpCoverage(scenario);
  const bvaCoverage = checkBvaCoverage(scenario);
  const completeness = checkCompleteness(scenario, featureText);

  // Consistency is skipped until a real cross-encoder check is configured.
  // Never claim full verification while a required layer is skipped.
  const fullyVerified = false;

  const notes = [requirementConsistency.notes];
  if (epCoverage === 'fail') notes.push('EP coverage is incomplete or inconsistent.');
  if (bvaCoverage === 'fail') notes.push('BVA coverage is incomplete or inconsistent.');
  if (completeness === 'fail') notes.push('Scenario completeness checks failed.');

  return {
    requirement_consistency: requirementConsistency,
    ep_coverage: epCoverage,
    bva_coverage: bvaCoverage,
    completeness,
    fully_verified: fullyVerified,
    notes,
  };
}
