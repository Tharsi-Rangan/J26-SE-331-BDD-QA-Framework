import { describe, expect, it } from 'vitest';
import { extractNumericRange, extractNumericRanges } from '../src/constraint-extractor.js';
import {
  buildVerificationResult,
  checkBvaCoverage,
  checkCompleteness,
  checkEpCoverage,
  type ScenarioForVerification,
} from '../src/verification-layers.js';

function makeScenario(): ScenarioForVerification {
  return {
    scenario_id: 'SCN-EX-001-01',
    requirement_id: 'REQ-EX-001',
    scenario_name: 'Age at and around the limits',
    scenario_type: 'boundary',
    is_outline: true,
    constraints: [
      {
        constraint_id: 'CON-01',
        parameter: 'age',
        kind: 'range',
        min: 18,
        max: 65,
        min_inclusive: true,
        max_inclusive: true,
        step: 1,
      },
    ],
    equivalence_partitions: [
      {
        partition_id: 'EP-01',
        constraint_id: 'CON-01',
        validity: 'invalid',
        representative: 17,
      },
      {
        partition_id: 'EP-02',
        constraint_id: 'CON-01',
        validity: 'valid',
        representative: 41,
      },
      {
        partition_id: 'EP-03',
        constraint_id: 'CON-01',
        validity: 'invalid',
        representative: 66,
      },
    ],
    boundary_values: [
      {
        boundary_id: 'BV-01',
        constraint_id: 'CON-01',
        position: 'below_min',
        value: 17,
        expected: 'reject',
      },
      {
        boundary_id: 'BV-02',
        constraint_id: 'CON-01',
        position: 'min',
        value: 18,
        expected: 'accept',
      },
      {
        boundary_id: 'BV-03',
        constraint_id: 'CON-01',
        position: 'above_min',
        value: 19,
        expected: 'accept',
      },
      {
        boundary_id: 'BV-04',
        constraint_id: 'CON-01',
        position: 'below_max',
        value: 64,
        expected: 'accept',
      },
      {
        boundary_id: 'BV-05',
        constraint_id: 'CON-01',
        position: 'max',
        value: 65,
        expected: 'accept',
      },
      {
        boundary_id: 'BV-06',
        constraint_id: 'CON-01',
        position: 'above_max',
        value: 66,
        expected: 'reject',
      },
    ],
    examples: [
      {
        row_index: 1,
        values: { age: 17, result: 'rejected' },
        boundary_ref: 'BV-01',
        partition_ref: 'EP-01',
      },
      {
        row_index: 2,
        values: { age: 18, result: 'accepted' },
        boundary_ref: 'BV-02',
      },
      {
        row_index: 3,
        values: { age: 19, result: 'accepted' },
        boundary_ref: 'BV-03',
      },
      {
        row_index: 4,
        values: { age: 41, result: 'accepted' },
        partition_ref: 'EP-02',
      },
      {
        row_index: 5,
        values: { age: 64, result: 'accepted' },
        boundary_ref: 'BV-04',
      },
      {
        row_index: 6,
        values: { age: 65, result: 'accepted' },
        boundary_ref: 'BV-05',
      },
      {
        row_index: 7,
        values: { age: 66, result: 'rejected' },
        boundary_ref: 'BV-06',
        partition_ref: 'EP-03',
      },
    ],
    verification: {
      syntax: 'pass',
      requirement_consistency: { status: 'skipped' },
      ep_coverage: 'skipped',
      bva_coverage: 'skipped',
      completeness: 'skipped',
      fully_verified: false,
    },
  };
}

const featureText = [
  '@REQ-EX-001',
  'Feature: Age validation',
  '',
  '  @SCN-EX-001-01',
  '  @type:boundary',
  '  Scenario Outline: Age at and around the limits',
  '    Given the registration form is available',
  '    When the user registers with age <age>',
  '    Then the result is "<result>"',
  '',
  '    Examples:',
  '      | age | result   |',
  '      | 17  | rejected |',
  '      | 18  | accepted |',
  '      | 19  | accepted |',
  '      | 41  | accepted |',
  '      | 64  | accepted |',
  '      | 65  | accepted |',
  '      | 66  | rejected |',
].join('\n');

describe('C2 verification layers', () => {
  it('passes EP coverage when all partitions are represented', () => {
    expect(checkEpCoverage(makeScenario())).toBe('pass');
  });

  it('fails EP coverage when a partition is missing', () => {
    const scenario = makeScenario();
    scenario.examples = scenario.examples?.filter((example) => example.partition_ref !== 'EP-02');

    expect(checkEpCoverage(scenario)).toBe('fail');
  });

  it('does not trust a partition reference when its value is wrong', () => {
    const scenario = makeScenario();
    const example = scenario.examples?.find((item) => item.partition_ref === 'EP-01');

    if (example) {
      example.values.age = 99;
    }

    expect(checkEpCoverage(scenario)).toBe('fail');
  });

  it('fails EP coverage when a partition representative is not used', () => {
    const scenario = makeScenario();
    const example = scenario.examples?.find((item) => item.partition_ref === 'EP-02');

    if (example) {
      example.values.age = 30;
    }

    expect(checkEpCoverage(scenario)).toBe('fail');
  });

  it('passes BVA coverage when all boundaries are represented', () => {
    expect(checkBvaCoverage(makeScenario())).toBe('pass');
  });

  it('fails BVA coverage when a boundary is missing', () => {
    const scenario = makeScenario();
    scenario.examples = scenario.examples?.filter((example) => example.boundary_ref !== 'BV-05');

    expect(checkBvaCoverage(scenario)).toBe('fail');
  });

  it('does not trust a boundary reference when its value is wrong', () => {
    const scenario = makeScenario();
    const example = scenario.examples?.find((item) => item.boundary_ref === 'BV-02');

    if (example) {
      example.values.age = 99;
    }

    expect(checkBvaCoverage(scenario)).toBe('fail');
  });

  it('checks scenario completeness against feature text', () => {
    expect(checkCompleteness(makeScenario(), featureText)).toBe('pass');
  });

  it('fails completeness when the outline has no examples', () => {
    const scenario = makeScenario();
    scenario.examples = [];

    expect(checkCompleteness(scenario, featureText)).toBe('fail');
  });

  it('fails completeness when the feature Examples table is missing', () => {
    const featureWithoutExamples = featureText
      .split('\n')
      .filter((line) => !line.trim().startsWith('Examples:') && !line.trim().startsWith('|'))
      .join('\n');

    expect(checkCompleteness(makeScenario(), featureWithoutExamples)).toBe('fail');
  });

  it('never fully verifies a scenario without cross-encoder verification', () => {
    const result = buildVerificationResult(makeScenario(), featureText);

    expect(result.requirement_consistency.status).toBe('skipped');
    expect(result.ep_coverage).toBe('pass');
    expect(result.bva_coverage).toBe('pass');
    expect(result.completeness).toBe('pass');
    expect(result.fully_verified).toBe(false);
  });
});

describe('numeric range constraint extraction', () => {
  it('associates two different ranges with their named parameters', () => {
    const analysis = extractNumericRanges(
      'Age must be from 18 to 65 and quantity must be between 1 and 10.',
    );

    expect(analysis.constraints).toMatchObject([
      { constraint_id: 'CON-01', parameter: 'age', min: 18, max: 65 },
      { constraint_id: 'CON-02', parameter: 'quantity', min: 1, max: 10 },
    ]);
    expect(
      analysis.equivalence_partitions.filter((partition) => partition.constraint_id === 'CON-02'),
    ).toHaveLength(3);
    expect(
      analysis.boundary_values.filter((boundary) => boundary.constraint_id === 'CON-02'),
    ).toHaveLength(6);
  });

  it('preserves explicit exclusive range endpoints in EP and BVA metadata', () => {
    const analysis = extractNumericRanges('Age must be from 18 to 65 exclusive.');

    expect(analysis.constraints[0]).toMatchObject({
      parameter: 'age',
      min: 18,
      max: 65,
      min_inclusive: false,
      max_inclusive: false,
    });
    expect(analysis.equivalence_partitions).toMatchObject([
      { validity: 'invalid', representative: 18, description: 'age <= 18' },
      { validity: 'valid', representative: 41 },
      { validity: 'invalid', representative: 65, description: 'age >= 65' },
    ]);
    expect(
      analysis.boundary_values.map(({ position, value, expected }) => ({
        position,
        value,
        expected,
      })),
    ).toEqual([
      { position: 'below_min', value: 17, expected: 'reject' },
      { position: 'min', value: 18, expected: 'reject' },
      { position: 'above_min', value: 19, expected: 'accept' },
      { position: 'below_max', value: 64, expected: 'accept' },
      { position: 'max', value: 65, expected: 'reject' },
      { position: 'above_max', value: 66, expected: 'reject' },
    ]);
  });

  it('verifies exclusive endpoint outcomes against their generated BVA expectations', () => {
    const analysis = extractNumericRanges('Age must be from 18 to 20 exclusive.');
    const scenario = makeScenario();
    scenario.constraints = analysis.constraints;
    scenario.equivalence_partitions = analysis.equivalence_partitions;
    scenario.boundary_values = analysis.boundary_values;
    scenario.examples = analysis.boundary_values.map((boundary, index) => ({
      row_index: index + 1,
      values: {
        age: boundary.value,
        result: boundary.expected === 'accept' ? 'accepted' : 'rejected',
      },
    }));

    expect(checkBvaCoverage(scenario)).toBe('pass');

    const minimumEndpoint = scenario.examples.find((example) => example.values.age === 18);
    if (minimumEndpoint) minimumEndpoint.values.result = 'accepted';

    expect(checkBvaCoverage(scenario)).toBe('fail');
  });

  it('preserves separate inclusivity for explicitly qualified endpoints', () => {
    const analysis = extractNumericRanges('Age must be between 18 inclusive and 65 (exclusive).');

    expect(analysis.constraints[0]).toMatchObject({
      min_inclusive: true,
      max_inclusive: false,
    });
    expect(analysis.boundary_values.find((boundary) => boundary.position === 'min')?.expected).toBe(
      'accept',
    );
    expect(analysis.boundary_values.find((boundary) => boundary.position === 'max')?.expected).toBe(
      'reject',
    );
  });

  it('rejects an exclusive integer range with no valid integer value', () => {
    expect(() => extractNumericRanges('Count must be between 1 and 2 exclusive.')).toThrow(
      /contains no representable valid value/i,
    );
  });

  it("does not assign a later parameter's range to an earlier parameter", () => {
    const requirement = 'Age is required; quantity must be between 1 and 10.';

    expect(extractNumericRange(requirement, 'age').constraints).toEqual([]);
    expect(extractNumericRanges(requirement).constraints).toMatchObject([
      { parameter: 'quantity', min: 1, max: 10 },
    ]);
  });

  it('fails when a requirement contains a range with no parameter association', () => {
    expect(() =>
      extractNumericRanges('Age must be from 18 to 65. Between 1 and 10 is the permitted range.'),
    ).toThrow(/could not be explicitly associated with a parameter/i);
  });
});
