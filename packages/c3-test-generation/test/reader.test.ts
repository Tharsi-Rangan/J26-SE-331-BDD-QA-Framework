import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, test } from 'vitest';
import { C3InputError, readC3Inputs } from '../src/input/reader.js';

const GOLDEN = fileURLToPath(
  new URL('../../contracts/fixtures/golden/example-registration', import.meta.url),
);

// Each test that changes files works on its own copy of the golden example.
const copies: string[] = [];
function copyGolden(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-reader-'));
  fs.cpSync(GOLDEN, dir, { recursive: true });
  copies.push(dir);
  return dir;
}
function editJson(dir: string, rel: string, change: (data: any) => void): void {
  const file = path.join(dir, rel);
  const data = JSON.parse(fs.readFileSync(file, 'utf8'));
  change(data);
  fs.writeFileSync(file, JSON.stringify(data, null, 2));
}
function editText(dir: string, rel: string, change: (text: string) => string): void {
  const file = path.join(dir, rel);
  fs.writeFileSync(file, change(fs.readFileSync(file, 'utf8')));
}
afterEach(() => {
  for (const dir of copies.splice(0)) fs.rmSync(dir, { recursive: true, force: true });
});

describe('C3-03 readC3Inputs on the golden example', () => {
  const inputs = readC3Inputs(GOLDEN);

  test('keeps both fully verified scenarios and skips none', () => {
    expect(inputs.runId).toBe('RUN-FIXTURE-EX-1');
    expect(inputs.scenarios.map((s) => s.scenarioId)).toEqual(['SCN-EX-001-01', 'SCN-EX-001-02']);
    expect(inputs.skipped).toEqual([]);
  });

  test('joins scenario -> requirement -> subject', () => {
    const s = inputs.scenarios[0]!;
    expect(s.requirementId).toBe('REQ-EX-001');
    expect(s.subject).toMatchObject({
      subjectId: 'SUB-EX-1',
      modulePath: 'src/registration.js',
      exports: ['registerUser'],
    });
  });

  test('reads steps as Given/When/Then from the .feature file', () => {
    expect(inputs.scenarios[0]!.steps).toEqual([
      { keyword: 'Given', text: 'the user repository is available', line: 8 },
      {
        keyword: 'When',
        text: 'a user registers with age 30 and email "amal@example.com"',
        line: 9,
      },
      { keyword: 'Then', text: 'the user is saved with age 30', line: 10 },
    ]);
  });

  test('reads the 6 Examples rows of the boundary outline, linked to C2 boundary values', () => {
    const outline = inputs.scenarios[1]!;
    expect(outline.isOutline).toBe(true);
    expect(outline.scenarioType).toBe('boundary');
    expect(outline.examples.map((r) => r.values.age)).toEqual(['17', '18', '19', '64', '65', '66']);
    expect(outline.examples[0]).toMatchObject({
      rowIndex: 1,
      values: { age: '17', result: 'rejected' },
    });
    expect(outline.examples[0]!.boundaryRef).toMatch(/^BV-\d{2}$/);
  });
});

describe('C3-03 readC3Inputs filters and errors', () => {
  test('skips a scenario C2 did not fully verify, and says which check failed', () => {
    const dir = copyGolden();
    editJson(dir, 'c2/scenario_metadata.json', (d) => {
      d.scenarios[0].verification.fully_verified = false;
      d.scenarios[0].verification.completeness = 'fail';
    });
    const inputs = readC3Inputs(dir);
    expect(inputs.scenarios.map((s) => s.scenarioId)).toEqual(['SCN-EX-001-02']);
    expect(inputs.skipped).toEqual([
      {
        scenarioId: 'SCN-EX-001-01',
        requirementId: 'REQ-EX-001',
        reason: 'not fully verified by C2 (failed: completeness)',
      },
    ]);
  });

  test('And/But steps take the type of the step before them', () => {
    const dir = copyGolden();
    editText(dir, 'c2/features/REQ-EX-001.feature', (t) =>
      t.replace(
        'Then the user is saved with age 30',
        'Then the user is saved with age 30\n    And no error is shown',
      ),
    );
    const steps = readC3Inputs(dir).scenarios[0]!.steps;
    expect(steps.at(-1)).toEqual({ keyword: 'Then', text: 'no error is shown', line: 11 });
  });

  test('clear error when scenario_metadata.json is missing', () => {
    const dir = copyGolden();
    fs.rmSync(path.join(dir, 'c2/scenario_metadata.json'));
    expect(() => readC3Inputs(dir)).toThrow(/missing c2\/scenario_metadata\.json/);
  });

  test('clear error when a requirement has no subject in the manifest', () => {
    const dir = copyGolden();
    editJson(dir, 'subject-manifest.json', (d) => {
      d.subjects[0].requirement_ids = [];
    });
    expect(() => readC3Inputs(dir)).toThrow(/REQ-EX-001 has no subject/);
  });

  test('reports every disagreement between .feature and metadata at once', () => {
    const dir = copyGolden();
    editText(dir, 'c2/features/REQ-EX-001.feature', (t) =>
      t.replace('@type:positive', '@type:negative').replace('| 66  | rejected |\n', ''),
    );
    try {
      readC3Inputs(dir);
      expect.unreachable('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(C3InputError);
      const problems = (err as C3InputError).problems.join('\n');
      expect(problems).toMatch(
        /SCN-EX-001-01: scenario_type "positive" but the \.feature has @type:negative/,
      );
      expect(problems).toMatch(
        /SCN-EX-001-02: metadata has 6 examples but the \.feature has 5 rows/,
      );
    }
  });

  test('clear error on a Gherkin syntax error', () => {
    const dir = copyGolden();
    editText(dir, 'c2/features/REQ-EX-001.feature', (t) => t.replace('Feature:', 'Featur:'));
    expect(() => readC3Inputs(dir)).toThrow(/REQ-EX-001\.feature: Gherkin syntax error/);
  });
});
