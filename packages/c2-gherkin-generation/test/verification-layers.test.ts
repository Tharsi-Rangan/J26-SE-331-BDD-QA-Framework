import { describe, expect, it } from 'vitest';
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
        representative: 30,
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
        values: { age: 30, result: 'accepted' },
        partition_ref: 'EP-02',
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
  '      | 30  | accepted |',
].join('\n');

describe('C2 verification layers', () => {
  it('passes EP coverage when all partitions are represented', () => {
    expect(checkEpCoverage(makeScenario())).toBe('pass');
  });

  it('fails EP coverage when a partition is missing', () => {
    const scenario = makeScenario();

    scenario.examples = scenario.examples?.filter((example) => example.values.age !== 30);

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

  it('fails EP coverage when an invalid representative is accepted', () => {
    const scenario = makeScenario();
    const invalidRepresentative = scenario.examples?.find((example) => example.values.age === 17);

    if (invalidRepresentative) {
      invalidRepresentative.values.result = 'accepted';
    }

    expect(checkEpCoverage(scenario)).toBe('fail');
  });

  it('fails EP coverage when a valid representative is rejected', () => {
    const scenario = makeScenario();
    const validRepresentative = scenario.examples?.find((example) => example.values.age === 30);

    if (validRepresentative) {
      validRepresentative.values.result = 'rejected';
    }

    expect(checkEpCoverage(scenario)).toBe('fail');
  });

  it('requires other constrained parameters to be valid for EP attribution', () => {
    const scenario = makeScenario();
    scenario.constraints.push({
      constraint_id: 'CON-02',
      parameter: 'quantity',
      min: 1,
      max: 10,
    });
    scenario.examples?.forEach((example) => {
      example.values.quantity = 5;
    });

    const invalidAgeRepresentative = scenario.examples?.find(
      (example) => example.values.age === 17,
    );
    if (invalidAgeRepresentative) {
      invalidAgeRepresentative.values.quantity = 0;
    }

    expect(checkEpCoverage(scenario)).toBe('fail');
  });

  it('rejects an invalid partition whose representative is inside the range', () => {
    const scenario = makeScenario();
    const invalidPartition = scenario.equivalence_partitions.find(
      (partition) => partition.partition_id === 'EP-01',
    );

    if (invalidPartition) {
      invalidPartition.representative = 18;
    }

    expect(checkEpCoverage(scenario)).toBe('fail');
  });

  it('rejects a valid partition whose representative is outside the range', () => {
    const scenario = makeScenario();
    const validPartition = scenario.equivalence_partitions.find(
      (partition) => partition.partition_id === 'EP-02',
    );

    if (validPartition) {
      validPartition.representative = 17;
    }

    scenario.examples?.push({
      row_index: 8,
      values: { age: 17, result: 'rejected' },
    });

    expect(checkEpCoverage(scenario)).toBe('fail');
  });

  it('passes EP coverage for multiple constrained parameters in one row', () => {
    const scenario = makeScenario();

    scenario.constraints.push({
      constraint_id: 'CON-02',
      parameter: 'quantity',
      kind: 'range',
      min: 1,
      max: 10,
      min_inclusive: true,
      max_inclusive: true,
      step: 1,
    });

    scenario.equivalence_partitions.push({
      partition_id: 'EP-03',
      constraint_id: 'CON-02',
      validity: 'valid',
      representative: 5,
    });

    scenario.examples = [
      {
        row_index: 1,
        values: { age: 17, quantity: 5, result: 'rejected' },
        partition_ref: 'EP-01',
      },
      {
        row_index: 2,
        values: { age: 18, quantity: 5, result: 'accepted' },
      },
      {
        row_index: 3,
        values: { age: 30, quantity: 5, result: 'accepted' },
        partition_ref: 'EP-02',
      },
    ];

    expect(checkEpCoverage(scenario)).toBe('pass');
  });

  it('fails EP coverage when a partition for the second parameter is missing', () => {
    const scenario = makeScenario();

    scenario.constraints.push({
      constraint_id: 'CON-02',
      parameter: 'quantity',
      kind: 'range',
      min: 1,
      max: 10,
      min_inclusive: true,
      max_inclusive: true,
      step: 1,
    });

    scenario.equivalence_partitions.push(
      {
        partition_id: 'EP-03',
        constraint_id: 'CON-02',
        validity: 'valid',
        representative: 5,
      },
      {
        partition_id: 'EP-04',
        constraint_id: 'CON-02',
        validity: 'invalid',
        representative: 0,
      },
    );

    scenario.examples = [
      {
        row_index: 1,
        values: { age: 17, quantity: 5, result: 'rejected' },
      },
      {
        row_index: 2,
        values: { age: 18, quantity: 5, result: 'accepted' },
      },
      {
        row_index: 3,
        values: { age: 30, quantity: 5, result: 'accepted' },
      },
    ];

    // quantity=0 is never present in the Examples rows.
    expect(checkEpCoverage(scenario)).toBe('fail');
  });

  it('passes BVA coverage when all boundaries are represented', () => {
    expect(checkBvaCoverage(makeScenario())).toBe('pass');
  });

  it('fails BVA coverage when a boundary is missing', () => {
    const scenario = makeScenario();

    scenario.examples = scenario.examples?.filter((example) => example.values.age !== 18);

    expect(checkBvaCoverage(scenario)).toBe('fail');
  });

  it('fails BVA coverage when a boundary has the wrong expected result', () => {
    const scenario = makeScenario();
    const minimumExample = scenario.examples?.find((example) => example.values.age === 18);

    if (minimumExample) {
      minimumExample.values.result = 'rejected';
    }

    expect(checkBvaCoverage(scenario)).toBe('fail');
  });

  it('requires other constrained parameters to be valid for boundary attribution', () => {
    const scenario = makeScenario();

    scenario.constraints.push({
      constraint_id: 'CON-02',
      parameter: 'quantity',
      kind: 'range',
      min: 1,
      max: 10,
      min_inclusive: true,
      max_inclusive: true,
    });

    scenario.examples?.forEach((example) => {
      example.values.quantity = 5;
    });

    const belowMinimumAge = scenario.examples?.find((example) => example.values.age === 17);

    if (belowMinimumAge) {
      belowMinimumAge.values.quantity = 0;
    }

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

  it('passes BVA coverage for multiple constrained parameters in one row', () => {
    const scenario = makeScenario();

    scenario.constraints.push({
      constraint_id: 'CON-02',
      parameter: 'quantity',
      kind: 'range',
      min: 1,
      max: 10,
      min_inclusive: true,
      max_inclusive: true,
      step: 1,
    });

    scenario.boundary_values.push({
      boundary_id: 'BV-03',
      constraint_id: 'CON-02',
      position: 'min',
      value: 1,
      expected: 'accept',
    });

    scenario.examples = [
      {
        row_index: 1,
        values: { age: 17, quantity: 1, result: 'rejected' },
        boundary_ref: 'BV-01',
      },
      {
        row_index: 2,
        values: { age: 18, quantity: 1, result: 'accepted' },
        boundary_ref: 'BV-02',
      },
      {
        row_index: 3,
        values: { age: 30, quantity: 1, result: 'accepted' },
      },
    ];

    expect(checkBvaCoverage(scenario)).toBe('pass');
  });

  it('fails BVA coverage when a boundary for the second parameter is missing', () => {
    const scenario = makeScenario();

    scenario.constraints.push({
      constraint_id: 'CON-02',
      parameter: 'quantity',
      kind: 'range',
      min: 1,
      max: 10,
      min_inclusive: true,
      max_inclusive: true,
      step: 1,
    });

    scenario.boundary_values.push(
      {
        boundary_id: 'BV-03',
        constraint_id: 'CON-02',
        position: 'min',
        value: 1,
        expected: 'accept',
      },
      {
        boundary_id: 'BV-04',
        constraint_id: 'CON-02',
        position: 'below_min',
        value: 0,
        expected: 'reject',
      },
    );

    scenario.examples = [
      {
        row_index: 1,
        values: { age: 17, quantity: 1, result: 'rejected' },
      },
      {
        row_index: 2,
        values: { age: 18, quantity: 1, result: 'accepted' },
      },
      {
        row_index: 3,
        values: { age: 30, quantity: 1, result: 'accepted' },
      },
    ];

    // quantity=0 is never present in the Examples rows.
    expect(checkBvaCoverage(scenario)).toBe('fail');
  });

  it('checks scenario completeness against feature text', () => {
    expect(checkCompleteness(makeScenario(), featureText)).toBe('pass');
  });

  it('passes completeness for a regular Scenario without an Examples table', () => {
    const scenario: ScenarioForVerification = {
      scenario_id: 'SCN-EX-001-02',
      requirement_id: 'REQ-EX-001',
      scenario_name: 'Register with valid details',
      is_outline: false,
      constraints: [],
      equivalence_partitions: [],
      boundary_values: [],
      examples: [],
    };
    const regularScenario = [
      '  @SCN-EX-001-02',
      '  @type:positive',
      '  Scenario: Register with valid details',
      '    Given valid registration details',
      '    When the user submits the form',
      '    Then registration succeeds',
    ].join('\n');

    expect(checkCompleteness(scenario, regularScenario)).toBe('pass');
  });

  it('checks only the matching Scenario Outline table in a multi-outline feature', () => {
    const scenario: ScenarioForVerification = {
      ...makeScenario(),
      scenario_id: 'SCN-EX-001-02',
      scenario_name: 'Validate a second age range',
      constraints: [
        {
          constraint_id: 'CON-02',
          parameter: 'age',
          min: 10,
          max: 20,
        },
      ],
      equivalence_partitions: [],
      boundary_values: [],
      examples: [
        { row_index: 1, values: { age: 9, result: 'rejected' } },
        { row_index: 2, values: { age: 10, result: 'accepted' } },
      ],
    };
    const multiOutlineFeature = [
      '@REQ-EX-001',
      'Feature: Multiple validation outlines',
      '',
      '  @SCN-EX-001-01',
      '  @type:boundary',
      '  Scenario Outline: Age at and around the limits',
      '    When the user registers with age <age>',
      '    Then the result is "<result>"',
      '    Examples:',
      '      | age | result   |',
      '      | 17  | rejected |',
      '      | 18  | accepted |',
      '',
      '  @SCN-EX-001-02',
      '  @type:boundary',
      '  Scenario Outline: Validate a second age range',
      '    When the user registers with age <age>',
      '    Then the result is "<result>"',
      '    Examples:',
      '      | age | result   |',
      '      | 9   | rejected |',
      '      | 10  | accepted |',
    ].join('\n');

    expect(checkCompleteness(scenario, multiOutlineFeature)).toBe('pass');
  });

  it('checks rows in every named Examples block of the matching outline', () => {
    const scenario: ScenarioForVerification = {
      ...makeScenario(),
      scenario_id: 'SCN-EX-001-01',
      scenario_name: 'Age in named groups',
      constraints: [{ constraint_id: 'CON-01', parameter: 'age', min: 18, max: 20 }],
      equivalence_partitions: [],
      boundary_values: [],
      examples: [
        { row_index: 1, values: { age: 18, result: 'accepted' } },
        { row_index: 2, values: { age: 20, result: 'accepted' } },
      ],
    };
    const featureWithNamedBlocks = [
      '@REQ-EX-001',
      'Feature: Named examples',
      '  @SCN-EX-001-01',
      '  @type:boundary',
      '  Scenario Outline: Age in named groups',
      '    When age is <age>',
      '    Then the result is "<result>"',
      '    @first-group',
      '    Examples: First group',
      '      | age | result   |',
      '      | 18  | accepted |',
      '    @second-group',
      '    Examples: Second group',
      '      | age | result   |',
      '      | 20  | accepted |',
    ].join('\n');

    expect(checkCompleteness(scenario, featureWithNamedBlocks)).toBe('pass');
    scenario.examples![1].values.age = 19;
    expect(checkCompleteness(scenario, featureWithNamedBlocks)).toBe('fail');
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

    expect(checkCompleteness(scenarioWithoutExamples(), featureWithoutExamples)).toBe('fail');
  });

  it('fails completeness when a constrained parameter is absent from the table', () => {
    const scenario = makeScenario();

    scenario.constraints.push({
      constraint_id: 'CON-02',
      parameter: 'quantity',
      kind: 'range',
      min: 1,
      max: 10,
      min_inclusive: true,
      max_inclusive: true,
      step: 1,
    });

    scenario.examples?.forEach((example) => {
      example.values.quantity = 5;
    });

    expect(checkCompleteness(scenario, featureText)).toBe('fail');
  });

  it('fails completeness when a metadata row omits a constrained parameter', () => {
    const scenario = makeScenario();

    scenario.constraints.push({
      constraint_id: 'CON-02',
      parameter: 'quantity',
      kind: 'range',
      min: 1,
      max: 10,
      min_inclusive: true,
      max_inclusive: true,
      step: 1,
    });

    scenario.examples?.forEach((example) => {
      example.values.quantity = 5;
    });

    delete scenario.examples?.[1].values.quantity;

    expect(checkCompleteness(scenario, featureText)).toBe('fail');
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

function scenarioWithoutExamples(): ScenarioForVerification {
  const scenario = makeScenario();
  scenario.examples = [];
  return scenario;
}
