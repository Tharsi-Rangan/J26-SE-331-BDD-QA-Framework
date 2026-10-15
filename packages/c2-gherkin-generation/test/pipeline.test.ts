
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, test, vi } from 'vitest';

vi.mock('../src/llm-client.js', () => ({
  generateWithLlm: vi.fn(),
}));

import { generateWithLlm } from '../src/llm-client.js';
import { run } from '../src/index.js';

const mockedGenerate = vi.mocked(generateWithLlm);

let tempDir = '';

function createInput(requirements: Array<Record<string, unknown>>) {
  tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'c2-pipeline-'));

  const inputDir = path.join(tempDir, 'input');
  fs.mkdirSync(path.join(inputDir, 'c1'), { recursive: true });

  fs.writeFileSync(
    path.join(inputDir, 'c1', 'validated_requirements.json'),
    JSON.stringify({
      contract: 'c1.validated-requirements',
      schema_version: '1.0.0',
      run_id: 'RUN-FIXTURE-TEST-1',
      requirements,
    }),
  );

  return {
    in: inputDir,
    out: path.join(tempDir, 'output'),
  };
}

function requirement(
  requirementId: string,
  finalText: string,
  bddReady: boolean,
) {
  return {
    requirement_id: requirementId,
    original_text: 'Original text must not be used.',
    final_text: finalText,
    bdd_ready: bddReady,
  };
}

const validFeature = [
  '@REQ-EX-001',
  'Feature: Registration',
  '',
  '  @SCN-EX-001-01',
  '  @type:positive',
  '  Scenario: Register a valid user',
  '    Given a valid registration request',
  '    When the user submits the request',
  '    Then the registration succeeds',
].join('\n');

afterEach(() => {
  vi.clearAllMocks();

  if (tempDir && fs.existsSync(tempDir)) {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }

  tempDir = '';
});

describe('C2 generation pipeline', () => {
  test('uses final_text and skips non-BDD-ready requirements', async () => {
    process.env.LLM_MODEL = 'test-model';

    mockedGenerate.mockResolvedValue(validFeature);

    const options = createInput([
      requirement(
        'REQ-EX-001',
        'The final approved requirement text.',
        true,
      ),
      requirement(
        'REQ-EX-002',
        'This requirement is not ready.',
        false,
      ),
    ]);

    await run(options);

    expect(mockedGenerate).toHaveBeenCalledOnce();

    const prompt = mockedGenerate.mock.calls[0][0]
      .map((message) => message.content)
      .join('\n');

    expect(prompt).toContain('The final approved requirement text.');
    expect(prompt).not.toContain('Original text must not be used.');
    expect(prompt).not.toContain('This requirement is not ready.');

    const outputFeature = fs.readFileSync(
      path.join(options.out, 'c2', 'features', 'REQ-EX-001.feature'),
      'utf8',
    );

    expect(outputFeature).toContain('Feature: Registration');
    expect(
      fs.existsSync(
        path.join(options.out, 'c2', 'features', 'REQ-EX-002.feature'),
      ),
    ).toBe(false);

    const metadata = JSON.parse(
      fs.readFileSync(
        path.join(options.out, 'c2', 'scenario_metadata.json'),
        'utf8',
      ),
    );

    expect(metadata.run_id).toBe('RUN-FIXTURE-TEST-1');
    expect(metadata.producer.model).toBe('test-model');
    expect(metadata.features).toHaveLength(1);
    expect(metadata.scenarios).toHaveLength(1);
    expect(metadata.scenarios[0].generation.mode).toBe('llm_only_baseline');
    expect(metadata.scenarios[0].verification.fully_verified).toBe(false);
  });

  test('rejects a model response without the requirement tag', async () => {
    process.env.LLM_MODEL = 'test-model';

    mockedGenerate.mockResolvedValue(
      validFeature.replace('@REQ-EX-001\n', ''),
    );

    const options = createInput([
      requirement('REQ-EX-001', 'Approved requirement.', true),
    ]);

    await expect(run(options)).rejects.toThrow(
      'missing its requirement tag',
    );
  });
});
