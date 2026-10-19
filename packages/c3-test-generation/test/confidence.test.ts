import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';
import { run } from '../src/index.js';
import { FakeModelClient } from '../src/model/index.js';
import { confidenceOf, THRESHOLD, WEIGHTS, type Signals } from '../src/route/confidence.js';

const GOLDEN = fileURLToPath(
  new URL('../../contracts/fixtures/golden/example-registration', import.meta.url),
);
const VALIDATE = fileURLToPath(new URL('../../contracts/scripts/validate.mjs', import.meta.url));
const FIXED_TIME = '2026-10-19T10:00:00+05:30';
const B = {
  steps: ['S1'],
  kind: 'returns_input',
  value: { id: 'u1' },
  error_message: null,
  summary: "save() returns the given user with id 'u1'.",
  rationale: 'S1 says the repository is available.',
};
const A1 = {
  act: 'registerUser({ age: 30, email: "amal@example.com" })',
  assertions: [
    {
      then: 'T1',
      category: 'state_change',
      target: 'userRepository.save',
      change: 'called_with',
      args: [{ age: 30, email: 'amal@example.com' }],
    },
    { then: 'T1', category: 'equality', actual: 'result.age', expected: 30 },
  ],
};
/** Compiles and runs, but invents a value (not in any step) and uses a category the Then step contradicts. */
const INVENTED1 = {
  act: 'registerUser({ age: 30, email: "amal@example.com" })',
  assertions: [
    { then: 'T1', category: 'equality', actual: 'result.email', expected: 'admin@site.org' },
  ],
};
const A2 = {
  act: 'registerUser({ age: <age>, email: "test@example.com" })',
  assertions: [
    {
      then: 'T1',
      when: { column: 'result', equals: 'rejected' },
      category: 'exception',
      error: 'ValidationError',
    },
    {
      then: 'T1',
      when: { column: 'result', equals: 'accepted' },
      category: 'state_change',
      target: 'userRepository.save',
      change: 'called_with',
      args: [{ age: '<age>', email: 'test@example.com' }],
    },
  ],
};
const model = (a1: object, a2: object | string) =>
  new FakeModelClient((req) => {
    const u = req.messages[1]!.content;
    if (u.includes('Mocked dependency:')) return JSON.stringify(B);
    if (u.includes('Age at and around')) return typeof a2 === 'string' ? a2 : JSON.stringify(a2);
    return JSON.stringify(a1);
  });

async function goldenRun(m: FakeModelClient) {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-c-'));
  fs.cpSync(GOLDEN, out, { recursive: true });
  for (const d of ['c3', 'c4']) fs.rmSync(path.join(out, d), { recursive: true, force: true });
  await run({ in: out, out, generatedAt: FIXED_TIME, model: m });
  const read = (f: string) => JSON.parse(fs.readFileSync(path.join(out, f), 'utf8'));
  const validate = spawnSync(process.execPath, [VALIDATE, out], { encoding: 'utf8' });
  const res = {
    out,
    report: read('c3/generation_confidence_report.json'),
    manifest: read('c3/test_manifest.json'),
    validate,
    files: (dir: string) =>
      fs.existsSync(path.join(out, dir)) ? fs.readdirSync(path.join(out, dir)) : [],
    text: (f: string) => fs.readFileSync(path.join(out, f), 'utf8'),
  };
  return res;
}

describe('C3-13 formula', () => {
  test('weights add up to 1; all good = 1; threshold 0.8', () => {
    expect(Object.values(WEIGHTS).reduce((a, b) => a + b, 0)).toBeCloseTo(1, 10);
    const all: Signals = {
      all_deterministic_checks_pass: true,
      semantic_score: 1,
      runs_clean: true,
      no_repair_needed: true,
      c2_fully_verified: true,
      mock_behaviour_from_model: true,
    };
    expect(confidenceOf(all)).toBe(1);
    expect(THRESHOLD).toBe(0.8);
  });

  test('a clean test needs semantic >= 0.34; a repaired one >= 0.67', () => {
    const s = (semantic: number, repaired = false): Signals => ({
      all_deterministic_checks_pass: true,
      semantic_score: semantic,
      runs_clean: true,
      no_repair_needed: !repaired,
      c2_fully_verified: true,
      mock_behaviour_from_model: true,
    });
    expect(confidenceOf(s(0.33))).toBeLessThan(THRESHOLD);
    expect(confidenceOf(s(0.34))).toBeGreaterThanOrEqual(THRESHOLD);
    expect(confidenceOf(s(0.66, true))).toBeLessThan(THRESHOLD);
    expect(confidenceOf(s(0.67, true))).toBeGreaterThanOrEqual(THRESHOLD);
  });
});

describe('C3-13 routing on the golden example', () => {
  test('good answers: both scenarios runnable; report, manifest and every link pass validate.mjs', async () => {
    const r = await goldenRun(model(A1, A2));
    try {
      expect(r.report.scenarios.map((s: any) => [s.scenario_id, s.route, s.confidence])).toEqual([
        ['SCN-EX-001-01', 'runnable', 1],
        ['SCN-EX-001-02', 'runnable', 0.9],
      ]);
      expect(r.report.scenarios[1].test_ids).toHaveLength(6);
      expect(r.report.formula).toMatchObject({ threshold: 0.8, calibrated: false });
      expect(r.manifest.stubs).toEqual([]);
      expect(r.validate.stdout).toContain('C3 confidence report routes and links checked');
      expect(r.validate.status).toBe(0);
    } finally {
      fs.rmSync(r.out, { recursive: true, force: true });
    }
  });

  test('an invented value -> low semantic score -> stub with the draft code; its test leaves the runnable file', async () => {
    const r = await goldenRun(model(INVENTED1, A2));
    try {
      const s1 = r.report.scenarios.find((s: any) => s.scenario_id === 'SCN-EX-001-01');
      expect(s1).toMatchObject({ route: 'stub', stub_id: 'STB-EX-001-01' });
      expect(s1.confidence).toBeLessThan(0.8);
      expect(s1.reason).toMatch(/low semantic score \(0\)/);
      expect(r.manifest.tests.map((t: any) => t.scenario_id)).not.toContain('SCN-EX-001-01');
      expect(r.manifest.stubs).toEqual([
        expect.objectContaining({
          stub_id: 'STB-EX-001-01',
          file: 'c3/test_stubs/STB-EX-001-01.stub.js',
        }),
      ]);
      const stub = r.text('c3/test_stubs/STB-EX-001-01.stub.js');
      expect(stub).toContain(
        'test.todo("[SCN-EX-001-01][STB-EX-001-01] Register a user with a valid age :: Confidence',
      );
      expect(stub).toContain('//   Then the user is saved with age 30');
      expect(stub).toContain('//   expect(result.email).toBe("admin@site.org");'); // the draft for a human
      expect(r.text('c3/runnable_tests/REQ-EX-001.test.js')).not.toContain('SCN-EX-001-01');
      expect(r.validate.status).toBe(0);
    } finally {
      fs.rmSync(r.out, { recursive: true, force: true });
    }
  });

  test('no usable plan -> stub below the threshold, validate.mjs still passes', async () => {
    const r = await goldenRun(model(A1, 'not json'));
    try {
      const s2 = r.report.scenarios.find((s: any) => s.scenario_id === 'SCN-EX-001-02');
      expect(s2).toMatchObject({ route: 'stub', stub_id: 'STB-EX-001-02' });
      expect(s2.confidence).toBeLessThan(0.8);
      expect(s2.reason).toMatch(/^No runnable test: attempt 2: model answer is not valid JSON/);
      expect(r.files('c3/test_stubs')).toEqual(['STB-EX-001-02.stub.js']);
      expect(r.validate.status).toBe(0);
    } finally {
      fs.rmSync(r.out, { recursive: true, force: true });
    }
  });

  test('stubs never run: Jest only looks in c3/runnable_tests', async () => {
    const r = await goldenRun(model(A1, 'not json'));
    try {
      expect(r.text('c3/jest.config.cjs')).toContain("roots: ['<rootDir>/c3/runnable_tests']");
    } finally {
      fs.rmSync(r.out, { recursive: true, force: true });
    }
  });
});
