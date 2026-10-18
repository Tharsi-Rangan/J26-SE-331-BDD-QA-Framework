import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/llm-client.js', () => ({
  generateWithLlm: vi.fn(),
}));

import { generateWithLlm } from '../src/llm-client.js';
import { run } from '../src/index.js';

const mockedGenerateWithLlm = vi.mocked(generateWithLlm);

let tempDir: string;
let inputDir: string;
let outputDir: string;

function createInput(
  requirements: Array<{
    requirement_id: string;
    final_text: string;
    bdd_ready: boolean;
  }>,
): void {
  const c1Dir = path.join(inputDir, 'c1');
  fs.mkdirSync(c1Dir, { recursive: true });

  fs.writeFileSync(
    path.join(c1Dir, 'validated_requirements.json'),
    JSON.stringify(
      {
        contract: 'c1.validated-requirements',
        schema_version: '1.0.0',
        run_id: 'RUN-FIXTURE-TEST-1',
        requirements,
      },
      null,
      2,
    ),
    'utf8',
  );
}

function validFeature(requirementId: string): string {
  const exampleId = requirementId.replace(/^REQ-/, '');

  return [
    `@${requirementId}`,
    'Feature: Example requirement',
    '',
    `  @SCN-${exampleId}-01`,
    '  @type:positive',
    '  Scenario: Perform the required action',
    '    Given the user is ready',
    '    When the user performs the action',
    '    Then the action succeeds',
  ].join('\n');
}

beforeEach(() => {
  tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'c2-pipeline-'));
  inputDir = path.join(tempDir, 'input');
  outputDir = path.join(tempDir, 'output');

  fs.mkdirSync(inputDir, { recursive: true });
  fs.mkdirSync(outputDir, { recursive: true });

  process.env.LLM_MODEL = 'test-model';
  process.env.C2_GENERATION_MODE = 'llm_only_baseline';
  mockedGenerateWithLlm.mockReset();
});

afterEach(() => {
  fs.rmSync(tempDir, { recursive: true, force: true });
  delete process.env.LLM_MODEL;
  delete process.env.C2_GENERATION_MODE;
});

describe('C2 generation pipeline', () => {
  it('uses final_text and skips non-BDD-ready requirements', async () => {
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'The user can register successfully.',
        bdd_ready: true,
      },
      {
        requirement_id: 'REQ-EX-002',
        final_text: 'This requirement is not ready.',
        bdd_ready: false,
      },
    ]);

    mockedGenerateWithLlm.mockResolvedValue(validFeature('REQ-EX-001'));

    await run({ in: inputDir, out: outputDir });

    expect(mockedGenerateWithLlm).toHaveBeenCalledTimes(1);

    const prompt = JSON.stringify(mockedGenerateWithLlm.mock.calls[0][0]);
    expect(prompt).toContain('The user can register successfully.');

    const featurePath = path.join(outputDir, 'c2', 'features', 'REQ-EX-001.feature');

    expect(fs.existsSync(featurePath)).toBe(true);

    const metadata = JSON.parse(
      fs.readFileSync(path.join(outputDir, 'c2', 'scenario_metadata.json'), 'utf8'),
    );

    expect(metadata.features).toHaveLength(1);
    expect(metadata.scenarios[0].verification.syntax).toBe('pass');

    const report = JSON.parse(
      fs.readFileSync(path.join(outputDir, 'c2', 'validation_report.json'), 'utf8'),
    );

    expect(report.total_files).toBe(1);
    expect(report.valid_files).toBe(1);
    expect(report.invalid_files).toBe(0);
  });

  it('rejects a model response without the requirement tag', async () => {
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'The user can register successfully.',
        bdd_ready: true,
      },
    ]);

    mockedGenerateWithLlm.mockResolvedValue(validFeature('REQ-EX-002'));

    await expect(run({ in: inputDir, out: outputDir })).rejects.toThrow(
      'LLM output for REQ-EX-001 is missing its requirement tag',
    );
  });

  it('rejects a requirement tag that only shares the requested ID prefix', async () => {
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'The user can register successfully.',
        bdd_ready: true,
      },
    ]);

    mockedGenerateWithLlm.mockResolvedValue(validFeature('REQ-EX-0012'));

    await expect(run({ in: inputDir, out: outputDir })).rejects.toThrow(
      'LLM output for REQ-EX-001 is missing its requirement tag',
    );
  });

  it('rejects a feature when one of its scenarios is missing C2 trace tags', async () => {
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'The user can register successfully.',
        bdd_ready: true,
      },
    ]);
    mockedGenerateWithLlm.mockResolvedValue(
      `${validFeature('REQ-EX-001')}\n\n  Scenario: An untracked scenario\n    Given an input\n    When submitted\n    Then it succeeds`,
    );

    await expect(run({ in: inputDir, out: outputDir })).rejects.toThrow(
      'only 1 have valid C2 scenario tags',
    );
  });

  it('rejects a scenario ID belonging to another requirement', async () => {
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'The user can register successfully.',
        bdd_ready: true,
      },
    ]);
    mockedGenerateWithLlm.mockResolvedValue(
      validFeature('REQ-EX-002').replace('@REQ-EX-002', '@REQ-EX-001'),
    );

    await expect(run({ in: inputDir, out: outputDir })).rejects.toThrow(
      'does not belong to requirement REQ-EX-001',
    );
  });

  it('does not write empty scenario metadata when no scenario tags are usable', async () => {
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'The user can register successfully.',
        bdd_ready: true,
      },
    ]);

    mockedGenerateWithLlm.mockResolvedValue(
      [
        '@REQ-EX-001',
        'Feature: Example requirement',
        '',
        '  @SCN-EX-001-1',
        '  @type:positive',
        '  Scenario: Perform the required action',
        '    Given the user is ready',
        '    When the user performs the action',
        '    Then the action succeeds',
      ].join('\n'),
    );

    await expect(run({ in: inputDir, out: outputDir })).rejects.toThrow(
      'No usable C2 scenarios were generated',
    );

    expect(fs.existsSync(path.join(outputDir, 'c2', 'validation_report.json'))).toBe(true);
    expect(fs.existsSync(path.join(outputDir, 'c2', 'scenario_metadata.json'))).toBe(false);
  });

  it('records invalid Gherkin and continues with the next requirement', async () => {
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'The first requirement.',
        bdd_ready: true,
      },
      {
        requirement_id: 'REQ-EX-002',
        final_text: 'The second requirement.',
        bdd_ready: true,
      },
    ]);

    mockedGenerateWithLlm
      .mockResolvedValueOnce(
        [
          '@REQ-EX-001',
          'Feature: Invalid example',
          '',
          '  Scenario: Invalid scenario',
          '    Given the user is ready',
          '    When',
        ].join('\n'),
      )
      .mockResolvedValueOnce(validFeature('REQ-EX-002'));

    await run({ in: inputDir, out: outputDir });

    expect(mockedGenerateWithLlm).toHaveBeenCalledTimes(2);

    const report = JSON.parse(
      fs.readFileSync(path.join(outputDir, 'c2', 'validation_report.json'), 'utf8'),
    );

    expect(report.run_id).toBe('RUN-FIXTURE-TEST-1');
    expect(report.total_files).toBe(2);
    expect(report.valid_files).toBe(1);
    expect(report.invalid_files).toBe(1);

    const invalidResult = report.results.find(
      (result: { requirement_id: string }) => result.requirement_id === 'REQ-EX-001',
    );

    expect(invalidResult.valid).toBe(false);
    expect(invalidResult.error).toBeTruthy();

    const validResult = report.results.find(
      (result: { requirement_id: string }) => result.requirement_id === 'REQ-EX-002',
    );

    expect(validResult.valid).toBe(true);

    expect(fs.existsSync(path.join(outputDir, 'c2', 'features', 'REQ-EX-001.feature'))).toBe(false);

    expect(fs.existsSync(path.join(outputDir, 'c2', 'features', 'REQ-EX-002.feature'))).toBe(true);

    const metadata = JSON.parse(
      fs.readFileSync(path.join(outputDir, 'c2', 'scenario_metadata.json'), 'utf8'),
    );

    expect(metadata.features).toHaveLength(1);
    expect(metadata.features[0].requirement_id).toBe('REQ-EX-002');
  });

  it('extracts numeric range metadata and checks boundary coverage', async () => {
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'The age must be from 18 to 65 years inclusive.',
        bdd_ready: true,
      },
    ]);

    mockedGenerateWithLlm.mockResolvedValue(
      [
        '@REQ-EX-001',
        'Feature: Age validation',
        '',
        '  @SCN-EX-001-01',
        '  @type:boundary',
        '  Scenario Outline: Validate age limits',
        '    Given the user is ready',
        '    When the user enters age <age>',
        '    Then the result is "<result>"',
        '',
        '    Examples:',
        '      | age | result   |',
        '      | 17  | rejected |',
        '      | 18  | accepted |',
        '      | 19  | accepted |',
        '      | 64  | accepted |',
        '      | 65  | accepted |',
        '      | 66  | rejected |',
      ].join('\n'),
    );

    await run({ in: inputDir, out: outputDir });

    const metadata = JSON.parse(
      fs.readFileSync(path.join(outputDir, 'c2', 'scenario_metadata.json'), 'utf8'),
    );

    const scenario = metadata.scenarios[0];

    expect(scenario.constraints).toHaveLength(1);
    expect(scenario.constraints[0]).toMatchObject({
      parameter: 'age',
      min: 18,
      max: 65,
    });

    expect(scenario.equivalence_partitions).toHaveLength(3);
    expect(scenario.boundary_values).toHaveLength(6);
    expect(scenario.examples).toHaveLength(6);

    expect(
      scenario.examples.map((example: { values: Record<string, unknown> }) => example.values.age),
    ).toEqual([17, 18, 19, 64, 65, 66]);

    expect(scenario.verification.bva_coverage).toBe('pass');
    expect(scenario.verification.fully_verified).toBe(false);
  });

  it('attaches each extracted constraint only to the scenario that binds its parameter', async () => {
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'Age must be from 18 to 65 and quantity must be between 1 and 10.',
        bdd_ready: true,
      },
    ]);

    mockedGenerateWithLlm.mockResolvedValue(
      [
        '@REQ-EX-001',
        'Feature: Age and quantity validation',
        '',
        '  @SCN-EX-001-01',
        '  @type:boundary',
        '  Scenario Outline: Validate age boundaries',
        '    Given the user is ready',
        '    When the user enters age <age>',
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
        '',
        '  @SCN-EX-001-02',
        '  @type:boundary',
        '  Scenario Outline: Validate quantity boundaries',
        '    Given the user is ready',
        '    When the user enters quantity <quantity>',
        '    Then the result is "<result>"',
        '',
        '    Examples:',
        '      | quantity | result   |',
        '      | 0        | rejected |',
        '      | 1        | accepted |',
        '      | 2        | accepted |',
        '      | 5        | accepted |',
        '      | 9        | accepted |',
        '      | 10       | accepted |',
        '      | 11       | rejected |',
      ].join('\n'),
    );

    await run({ in: inputDir, out: outputDir });

    const metadata = JSON.parse(
      fs.readFileSync(path.join(outputDir, 'c2', 'scenario_metadata.json'), 'utf8'),
    );
    const [ageScenario, quantityScenario] = metadata.scenarios;

    expect(ageScenario.constraints).toMatchObject([{ parameter: 'age', min: 18, max: 65 }]);
    expect(ageScenario.equivalence_partitions).toHaveLength(3);
    expect(ageScenario.boundary_values).toHaveLength(6);

    expect(quantityScenario.constraints).toMatchObject([
      { parameter: 'quantity', min: 1, max: 10 },
    ]);
    expect(quantityScenario.equivalence_partitions).toHaveLength(3);
    expect(quantityScenario.boundary_values).toHaveLength(6);

    expect(ageScenario.verification.bva_coverage).toBe('pass');
    expect(quantityScenario.verification.bva_coverage).toBe('pass');
  });

  it('generates isolated EP and BVA Examples rows in boundary-aware mode', async () => {
    process.env.C2_GENERATION_MODE = 'boundary_aware';
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text:
          'Age must be from 18 to 20 inclusive and quantity must be between 1 and 3 inclusive.',
        bdd_ready: true,
      },
    ]);

    mockedGenerateWithLlm.mockResolvedValue(
      [
        '@REQ-EX-001',
        'Feature: Registration bounds',
        '',
        '  @SCN-EX-001-01',
        '  @type:boundary',
        '  Scenario Outline: Validate age and quantity',
        '    When the user submits age <age> and quantity <quantity>',
        '    Then the result is "<result>"',
        '',
        '    Examples:',
        '      | age | quantity | result   |',
        '      | 18  | 1        | accepted |',
      ].join('\n'),
    );

    await run({ in: inputDir, out: outputDir });

    const metadata = JSON.parse(
      fs.readFileSync(path.join(outputDir, 'c2', 'scenario_metadata.json'), 'utf8'),
    );
    const scenario = metadata.scenarios[0];
    const ageBoundaryRow = scenario.examples.find(
      (example: { values: Record<string, unknown> }) => example.values.age === 17,
    );
    const quantityBoundaryRow = scenario.examples.find(
      (example: { values: Record<string, unknown> }) => example.values.quantity === 0,
    );
    const generatedFeature = fs.readFileSync(
      path.join(outputDir, 'c2', 'features', 'REQ-EX-001.feature'),
      'utf8',
    );

    expect(scenario.examples.length).toBeGreaterThan(1);
    expect(ageBoundaryRow.values).toMatchObject({ age: 17, quantity: 2, result: 'rejected' });
    expect(quantityBoundaryRow.values).toMatchObject({ age: 19, quantity: 0, result: 'rejected' });
    expect(scenario.verification).toMatchObject({
      ep_coverage: 'pass',
      bva_coverage: 'pass',
      completeness: 'pass',
      fully_verified: false,
    });
    expect(scenario.generation.mode).toBe('boundary_aware');
    expect(generatedFeature).toContain('| 17 | 2 | rejected |');
  });

  it('does not claim boundary-aware coverage without a result assertion', async () => {
    process.env.C2_GENERATION_MODE = 'boundary_aware';
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'Age must be from 18 to 65.',
        bdd_ready: true,
      },
    ]);

    mockedGenerateWithLlm.mockResolvedValue(
      [
        '@REQ-EX-001',
        'Feature: Age validation',
        '',
        '  @SCN-EX-001-01',
        '  @type:boundary',
        '  Scenario Outline: Validate age limits',
        '    When the user enters age <age>',
        '    Then age validation completes',
        '',
        '    Examples:',
        '      | age | result   |',
        '      | 18  | accepted |',
      ].join('\n'),
    );

    await expect(run({ in: inputDir, out: outputDir })).rejects.toThrow(
      'Boundary-aware generation requires a <result> assertion',
    );
    expect(fs.existsSync(path.join(outputDir, 'c2', 'scenario_metadata.json'))).toBe(false);
  });

  it.each([
    ['a comment', '    # Then the result is "<result>"'],
    ['a non-asserting step', '    Then process result <result>'],
  ])('rejects a result placeholder appearing only in %s', async (_description, misplacedLine) => {
    process.env.C2_GENERATION_MODE = 'boundary_aware';
    createInput([
      { requirement_id: 'REQ-EX-001', final_text: 'Age must be from 18 to 20.', bdd_ready: true },
    ]);
    mockedGenerateWithLlm.mockResolvedValue(
      [
        '@REQ-EX-001',
        'Feature: Age validation',
        '',
        '  @SCN-EX-001-01',
        '  @type:boundary',
        '  Scenario Outline: Validate age limits',
        '    When the user enters age <age>',
        '    Then age validation completes',
        misplacedLine,
        '    Examples:',
        '      | age | result   |',
        '      | 18  | accepted |',
      ].join('\n'),
    );

    await expect(run({ in: inputDir, out: outputDir })).rejects.toThrow(
      'Boundary-aware generation requires a <result> assertion',
    );
  });

  it('adds coverage rows to each named Examples block while preserving its metadata and rows', async () => {
    process.env.C2_GENERATION_MODE = 'boundary_aware';
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'Age must be from 18 to 20 inclusive.',
        bdd_ready: true,
      },
    ]);
    mockedGenerateWithLlm.mockResolvedValue(
      [
        '@REQ-EX-001',
        'Feature: Age validation',
        '',
        '  @SCN-EX-001-01',
        '  @type:boundary',
        '  Scenario Outline: Validate age limits',
        '    When the user enters age <age>',
        '    Then the result is "<result>"',
        '    @first-group',
        '    Examples: First group',
        '      First-block note.',
        '      | age | result   |',
        '      | 18  | accepted |',
        '    @second-group',
        '    Examples: Second group',
        '      Second-block note.',
        '      | age | result   |',
        '      | 20  | accepted |',
      ].join('\n'),
    );

    await run({ in: inputDir, out: outputDir });

    const output = fs.readFileSync(
      path.join(outputDir, 'c2', 'features', 'REQ-EX-001.feature'),
      'utf8',
    );
    const metadata = JSON.parse(
      fs.readFileSync(path.join(outputDir, 'c2', 'scenario_metadata.json'), 'utf8'),
    );
    const scenario = metadata.scenarios[0];

    expect(output).toContain('@first-group\n    Examples: First group\n      First-block note.');
    expect(output).toContain('@second-group\n    Examples: Second group\n      Second-block note.');
    expect(output).toMatch(
      /Examples: First group[\s\S]*\| 18\s+\| accepted \|[\s\S]*\| 17 \| rejected \|/,
    );
    expect(output).toMatch(
      /Examples: Second group[\s\S]*\| 20\s+\| accepted \|[\s\S]*\| 21 \| rejected \|/,
    );
    expect(scenario.examples).toHaveLength(10);
    expect(scenario.verification).toMatchObject({
      ep_coverage: 'pass',
      bva_coverage: 'pass',
      completeness: 'pass',
    });
  });

  it('keeps boundary augmentation isolated across multiple Scenario Outlines', async () => {
    process.env.C2_GENERATION_MODE = 'boundary_aware';
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'Age must be from 18 to 20 and quantity must be between 1 and 3.',
        bdd_ready: true,
      },
    ]);
    mockedGenerateWithLlm.mockResolvedValue(
      [
        '@REQ-EX-001',
        'Feature: Separate bounds',
        '',
        '  @SCN-EX-001-01',
        '  @type:boundary',
        '  Scenario Outline: Age range',
        '    When age is <age>',
        '    Then the result is "<result>"',
        '    Examples:',
        '      | age | result   |',
        '      | 18  | accepted |',
        '',
        '  @SCN-EX-001-02',
        '  @type:boundary',
        '  Scenario Outline: Quantity range',
        '    When quantity is <quantity>',
        '    Then the result is "<result>"',
        '    Examples:',
        '      | quantity | result   |',
        '      | 1        | accepted |',
      ].join('\n'),
    );

    await run({ in: inputDir, out: outputDir });

    const metadata = JSON.parse(
      fs.readFileSync(path.join(outputDir, 'c2', 'scenario_metadata.json'), 'utf8'),
    );
    const [ageScenario, quantityScenario] = metadata.scenarios;
    expect(
      ageScenario.constraints.map((constraint: { parameter: string }) => constraint.parameter),
    ).toEqual(['age']);
    expect(
      quantityScenario.constraints.map((constraint: { parameter: string }) => constraint.parameter),
    ).toEqual(['quantity']);
    expect(
      ageScenario.examples.every(
        (example: { values: Record<string, unknown> }) =>
          !Object.hasOwn(example.values, 'quantity'),
      ),
    ).toBe(true);
    expect(
      quantityScenario.examples.every(
        (example: { values: Record<string, unknown> }) => !Object.hasOwn(example.values, 'age'),
      ),
    ).toBe(true);
    expect(ageScenario.verification.bva_coverage).toBe('pass');
    expect(quantityScenario.verification.bva_coverage).toBe('pass');
  });

  it('binds and verifies a Rule-contained numeric outline without mixing another outline', async () => {
    process.env.C2_GENERATION_MODE = 'boundary_aware';
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'Age must be from 18 to 20 and quantity must be between 1 and 3.',
        bdd_ready: true,
      },
    ]);
    mockedGenerateWithLlm.mockResolvedValue(
      [
        '@REQ-EX-001',
        'Feature: Rule-contained constraints',
        '',
        '  Rule: Age validation',
        '    @SCN-EX-001-01',
        '    @type:boundary',
        '    Scenario Outline: Validate age in a rule',
        '      When age is <age>',
        '      Then the result is "<result>"',
        '      Examples: Rule age cases',
        '        | age | result   |',
        '        | 18  | accepted |',
        '',
        '  @SCN-EX-001-02',
        '  @type:boundary',
        '  Scenario Outline: Validate quantity outside the rule',
        '    When quantity is <quantity>',
        '    Then the result is "<result>"',
        '    Examples: Quantity cases',
        '      | quantity | result   |',
        '      | 1        | accepted |',
      ].join('\n'),
    );

    await run({ in: inputDir, out: outputDir });

    const metadata = JSON.parse(
      fs.readFileSync(path.join(outputDir, 'c2', 'scenario_metadata.json'), 'utf8'),
    );
    const [ruleScenario, topLevelScenario] = metadata.scenarios;
    const ruleBoundaryRow = ruleScenario.examples.find(
      (example: { values: Record<string, unknown> }) => example.values.age === 17,
    );

    expect(
      ruleScenario.constraints.map((constraint: { parameter: string }) => constraint.parameter),
    ).toEqual(['age']);
    expect(
      topLevelScenario.constraints.map((constraint: { parameter: string }) => constraint.parameter),
    ).toEqual(['quantity']);
    expect(ruleBoundaryRow.values).toMatchObject({ age: 17, result: 'rejected' });
    expect(
      ruleScenario.examples.every(
        (example: { values: Record<string, unknown> }) =>
          !Object.hasOwn(example.values, 'quantity'),
      ),
    ).toBe(true);
    expect(
      topLevelScenario.examples.every(
        (example: { values: Record<string, unknown> }) => !Object.hasOwn(example.values, 'age'),
      ),
    ).toBe(true);
    expect(ruleScenario.verification).toMatchObject({
      ep_coverage: 'pass',
      bva_coverage: 'pass',
      completeness: 'pass',
      fully_verified: false,
    });
    expect(topLevelScenario.verification.completeness).toBe('pass');
  });

  it('generates expected outcomes for mixed inclusive and exclusive endpoints', async () => {
    process.env.C2_GENERATION_MODE = 'boundary_aware';
    createInput([
      {
        requirement_id: 'REQ-EX-001',
        final_text:
          'Age must be from 18 to 20 exclusive and quantity must be between 1 and 3 inclusive.',
        bdd_ready: true,
      },
    ]);
    mockedGenerateWithLlm.mockResolvedValue(
      [
        '@REQ-EX-001',
        'Feature: Registration bounds',
        '',
        '  @SCN-EX-001-01',
        '  @type:boundary',
        '  Scenario Outline: Validate age and quantity',
        '    When the user submits age <age> and quantity <quantity>',
        '    Then the result is "<result>"',
        '    Examples:',
        '      | age | quantity | result   |',
        '      | 19  | 2        | accepted |',
      ].join('\n'),
    );

    await run({ in: inputDir, out: outputDir });

    const metadata = JSON.parse(
      fs.readFileSync(path.join(outputDir, 'c2', 'scenario_metadata.json'), 'utf8'),
    );
    const examples = metadata.scenarios[0].examples;
    const valueRow = (age: number, quantity: number) =>
      examples.find(
        (example: { values: Record<string, unknown> }) =>
          example.values.age === age && example.values.quantity === quantity,
      )?.values;

    expect(valueRow(18, 2)).toMatchObject({ result: 'rejected' });
    expect(valueRow(20, 2)).toMatchObject({ result: 'rejected' });
    expect(valueRow(19, 1)).toMatchObject({ result: 'accepted' });
    expect(valueRow(19, 3)).toMatchObject({ result: 'accepted' });
    expect(metadata.scenarios[0].verification.bva_coverage).toBe('pass');
  });
});
