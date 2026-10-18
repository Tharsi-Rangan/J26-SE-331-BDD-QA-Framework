
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

function createInput(requirements: Array<{
  requirement_id: string;
  final_text: string;
  bdd_ready: boolean;
}>): void {
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
  mockedGenerateWithLlm.mockReset();
});

afterEach(() => {
  fs.rmSync(tempDir, { recursive: true, force: true });
  delete process.env.LLM_MODEL;
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

    mockedGenerateWithLlm.mockResolvedValue(
      validFeature('REQ-EX-001'),
    );

    await run({ in: inputDir, out: outputDir });

    expect(mockedGenerateWithLlm).toHaveBeenCalledTimes(1);

    const prompt = JSON.stringify(mockedGenerateWithLlm.mock.calls[0][0]);
    expect(prompt).toContain('The user can register successfully.');

    const featurePath = path.join(
      outputDir,
      'c2',
      'features',
      'REQ-EX-001.feature',
    );

    expect(fs.existsSync(featurePath)).toBe(true);

    const metadata = JSON.parse(
      fs.readFileSync(
        path.join(outputDir, 'c2', 'scenario_metadata.json'),
        'utf8',
      ),
    );

    expect(metadata.features).toHaveLength(1);
    expect(metadata.scenarios[0].verification.syntax).toBe('pass');

    const report = JSON.parse(
      fs.readFileSync(
        path.join(outputDir, 'c2', 'validation_report.json'),
        'utf8',
      ),
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

    mockedGenerateWithLlm.mockResolvedValue(
      validFeature('REQ-EX-002'),
    );

    await expect(
      run({ in: inputDir, out: outputDir }),
    ).rejects.toThrow(
      'LLM output for REQ-EX-001 is missing its requirement tag',
    );
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
      .mockResolvedValueOnce(
        validFeature('REQ-EX-002'),
      );

    await run({ in: inputDir, out: outputDir });

    expect(mockedGenerateWithLlm).toHaveBeenCalledTimes(2);

    const report = JSON.parse(
      fs.readFileSync(
        path.join(outputDir, 'c2', 'validation_report.json'),
        'utf8',
      ),
    );

    expect(report.run_id).toBe('RUN-FIXTURE-TEST-1');
    expect(report.total_files).toBe(2);
    expect(report.valid_files).toBe(1);
    expect(report.invalid_files).toBe(1);

    const invalidResult = report.results.find(
      (result: { requirement_id: string }) =>
        result.requirement_id === 'REQ-EX-001',
    );

    expect(invalidResult.valid).toBe(false);
    expect(invalidResult.error).toBeTruthy();

    const validResult = report.results.find(
      (result: { requirement_id: string }) =>
        result.requirement_id === 'REQ-EX-002',
    );

    expect(validResult.valid).toBe(true);

    expect(
      fs.existsSync(
        path.join(outputDir, 'c2', 'features', 'REQ-EX-001.feature'),
      ),
    ).toBe(false);

    expect(
      fs.existsSync(
        path.join(outputDir, 'c2', 'features', 'REQ-EX-002.feature'),
      ),
    ).toBe(true);

    const metadata = JSON.parse(
      fs.readFileSync(
        path.join(outputDir, 'c2', 'scenario_metadata.json'),
        'utf8',
      ),
    );

    expect(metadata.features).toHaveLength(1);
    expect(metadata.features[0].requirement_id).toBe('REQ-EX-002');
  });
});
