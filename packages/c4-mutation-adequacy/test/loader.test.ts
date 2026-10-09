import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, test } from 'vitest';
import { loadInputs } from '../src/loader.js';
import { runStryker, strykerConfig } from '../src/stryker.js';

const golden = path.resolve(
  import.meta.dirname,
  '../../contracts/fixtures/golden/example-registration',
);
const temps: string[] = [];

/** Copy the golden folder to a temp folder and apply `edit` to it. */
function goldenCopy(edit: (dir: string) => void): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'c4-loader-'));
  temps.push(dir);
  fs.cpSync(golden, dir, { recursive: true });
  edit(dir);
  return dir;
}

const editJson = (file: string, change: (d: any) => void) => {
  const d = JSON.parse(fs.readFileSync(file, 'utf8'));
  change(d);
  fs.writeFileSync(file, JSON.stringify(d));
};

afterEach(() => {
  for (const d of temps.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});

describe('c4 loadInputs', () => {
  test('loads the golden example', () => {
    const inputs = loadInputs(golden);
    expect(inputs.manifest.tests).toHaveLength(7);
    expect(inputs.subject.subject_id).toBe('SUB-EX-1');
    expect(inputs.mutate).toEqual(['subject-src/src/registration.js']);
    expect(inputs.jestConfig).toBe('jest.config.js');
  });

  test('builds the same StrykerJS settings as the golden stryker.config.json', () => {
    const want = JSON.parse(fs.readFileSync(path.join(golden, 'stryker.config.json'), 'utf8'));
    const got = strykerConfig(loadInputs(golden));
    expect(got).toMatchObject({
      testRunner: want.testRunner,
      coverageAnalysis: want.coverageAnalysis,
      mutate: want.mutate,
      jest: want.jest,
    });
  });

  test('rejects a manifest that breaks the schema', () => {
    const dir = goldenCopy((d) =>
      editJson(path.join(d, 'c3/test_manifest.json'), (m) => delete m.runner),
    );
    expect(() => loadInputs(dir)).toThrow(/does not match c3-test-manifest/);
  });

  test('rejects an unknown subject', () => {
    const dir = goldenCopy((d) =>
      editJson(path.join(d, 'c3/test_manifest.json'), (m) => (m.subject_id = 'SUB-NOPE')),
    );
    expect(() => loadInputs(dir)).toThrow(/no subject SUB-NOPE/);
  });

  test('rejects a missing test file', () => {
    const dir = goldenCopy((d) => fs.rmSync(path.join(d, 'c3/runnable_tests/REQ-EX-001.test.js')));
    expect(() => loadInputs(dir)).toThrow(/test file not found/);
  });

  test('rejects a missing module under test', () => {
    const dir = goldenCopy(() => {});
    expect(() => loadInputs(dir, path.join(dir, 'no-such-subject'))).toThrow(
      /Module under test not found/,
    );
  });
});

describe('c4 runStryker', () => {
  test(
    'runs StrykerJS on the golden C3 tests and gets the golden result',
    { timeout: 120_000 },
    () => {
      const { report } = runStryker(loadInputs(golden), () => {});
      const mutants = Object.values(report.files).flatMap((f) => f.mutants);
      expect(mutants).toHaveLength(14);
      expect(mutants.filter((m) => m.status === 'Survived').map((m) => m.id)).toEqual(['12']);
      expect(fs.existsSync(path.join(golden, '.stryker-tmp'))).toBe(false);
      expect(fs.existsSync(path.join(golden, 'reports'))).toBe(false);
    },
  );
});
