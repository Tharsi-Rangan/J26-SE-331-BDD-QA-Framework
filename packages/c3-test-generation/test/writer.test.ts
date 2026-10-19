import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, test } from 'vitest';
import { run } from '../src/index.js';
import { readC3Inputs } from '../src/input/reader.js';
import type { C3ScenarioInput } from '../src/input/types.js';
import { FakeModelClient } from '../src/model/index.js';
import { makeSandbox, removeSandbox, runJest } from '../src/runner/jest.js';
import {
  caseLabel,
  jestConfig,
  rowValue,
  testId,
  writeJestTests,
} from '../src/writer/jest-writer.js';
import type { ScenarioPlan } from '../src/assert/plan.js';

const GOLDEN = fileURLToPath(
  new URL('../../contracts/fixtures/golden/example-registration', import.meta.url),
);
const VALIDATE = fileURLToPath(new URL('../../contracts/scripts/validate.mjs', import.meta.url));
const FIXED_TIME = '2026-10-19T10:00:00+05:30';

const BEHAVIOUR = {
  steps: ['S1'],
  kind: 'returns_input',
  value: { id: 'u1' },
  error_message: null,
  summary: "save() returns the given user with id 'u1'.",
  rationale: 'S1 says the repository is available, so save succeeds.',
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
      when: { column: 'result', equals: 'rejected' },
      category: 'state_change',
      target: 'userRepository.save',
      change: 'not_called',
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
const model = (a2: object = A2) =>
  new FakeModelClient((req) => {
    const u = req.messages[1]!.content;
    if (u.includes('Mocked dependency:')) return JSON.stringify(BEHAVIOUR);
    return JSON.stringify(u.includes('Age at and around') ? a2 : A1);
  });

/** A run folder: the golden inputs (c1, c2, manifest, subject) with no C3 output yet. */
function freshRun(): string {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-w-'));
  fs.cpSync(GOLDEN, out, { recursive: true });
  fs.rmSync(path.join(out, 'c3'), { recursive: true, force: true });
  fs.rmSync(path.join(out, 'c4'), { recursive: true, force: true });
  return out;
}

describe('C3-10 helpers', () => {
  const [plain, outline] = readC3Inputs(GOLDEN).scenarios as [C3ScenarioInput, C3ScenarioInput];

  test('test ids embed the scenario id and the Examples row', () => {
    expect(testId('SCN-EX-001-01')).toBe('TST-EX-001-01-01');
    expect(testId('SCN-EX-001-02', 6)).toBe('TST-EX-001-02-06');
  });

  test('row values keep C2 types; quoted columns are strings', () => {
    expect(rowValue(outline, 1, 'age', false)).toBe(17); // number from scenario_metadata.json
    expect(rowValue(outline, 1, 'age', true)).toBe('17'); // "<age>" was in quotes
    expect(rowValue(outline, 1, 'result', false)).toBe('rejected');
  });

  test('case labels', () => {
    expect(caseLabel(outline, 2)).toBe('age=18, result=accepted');
    expect(caseLabel(plain)).toBe('a user registers with age 30 and email "amal@example.com"');
  });

  test('jest config runs from the run folder and finds the subject node_modules', () => {
    const cfg = jestConfig(readC3Inputs(GOLDEN));
    expect(cfg).toContain("rootDir: '..'");
    expect(cfg).toContain("modulePaths: ['<rootDir>/subject-src/node_modules']");
  });
});

describe('C3-10 golden example end to end (real Jest)', () => {
  let out: string;
  beforeAll(async () => {
    out = freshRun();
    await run({ in: out, out, generatedAt: FIXED_TIME, model: model() });
  });
  afterAll(() => fs.rmSync(out, { recursive: true, force: true }));

  test('one file per requirement with the contract names', () => {
    const src = fs.readFileSync(path.join(out, 'c3/runnable_tests/REQ-EX-001.test.js'), 'utf8');
    expect(src.split('\n')[0]).toBe('// @requirement REQ-EX-001');
    expect(src).toContain('jest.mock("../../subject-src/src/userRepository");');
    expect(src).toContain(
      'const { ValidationError, registerUser } = require("../../subject-src/src/registration");',
    );
    expect(src.match(/^describe\(/gm)).toHaveLength(1);
    expect(src).toContain('describe("[REQ-EX-001] User registration age limit", () => {');
    expect(src).toContain('test.each([');
    expect(src).toContain('["TST-EX-001-02-01", "age=17, result=rejected", 17, "rejected"],');
  });

  test('test_manifest.json: 7 tests, BV refs, strategies, categories, mock ids; validate.mjs passes with all links', () => {
    const m = JSON.parse(fs.readFileSync(path.join(out, 'c3/test_manifest.json'), 'utf8'));
    expect(m.tests.map((t: any) => t.test_id)).toEqual([
      'TST-EX-001-01-01',
      'TST-EX-001-02-01',
      'TST-EX-001-02-02',
      'TST-EX-001-02-03',
      'TST-EX-001-02-04',
      'TST-EX-001-02-05',
      'TST-EX-001-02-06',
    ]);
    expect(m.tests[0]).toMatchObject({
      strategy: 'factory',
      assertion_categories: ['state_change', 'equality'],
      mock_decision_ids: ['MD-001'],
    });
    expect(m.tests[1]).toMatchObject({
      strategy: 'parametrised',
      examples_row: 1,
      boundary_ref: 'BV-01',
      assertion_categories: ['exception', 'state_change'],
      mock_decision_ids: ['MD-002'],
    });
    expect(m.runner).toEqual({
      name: 'jest',
      version: '29.7.0',
      config_path: 'c3/jest.config.cjs',
      test_root: 'c3/runnable_tests',
    });
    expect(m.producer.model).toBe('fake-model@fake');
    const res = spawnSync(process.execPath, [VALIDATE, out], { encoding: 'utf8' });
    expect(res.stdout).toContain('c3/test_manifest.json matches c3-test-manifest.schema.json');
    expect(res.stdout).toContain('C3 -> C2 links and Jest names checked');
    expect(res.status).toBe(0);
  });

  test('Jest runs all 7 tests, they pass, and every Jest full name equals the manifest name', () => {
    const sb = makeSandbox({ runDir: out, subjectRoot: path.join(out, 'subject-src') });
    try {
      const r = runJest(sb);
      expect(r.suiteErrors).toEqual([]);
      expect(r.tests.map((t) => t.status)).toEqual(Array(7).fill('passed'));
      const m = JSON.parse(fs.readFileSync(path.join(out, 'c3/test_manifest.json'), 'utf8'));
      expect(r.tests.map((t) => t.fullName).sort()).toEqual(
        m.tests.map((t: any) => t.jest_full_name).sort(),
      );
    } finally {
      removeSandbox(sb);
    }
  });

  test('the generated tests catch an off-by-one bug (age > 64): only the age-65 row fails', () => {
    const buggy = path.join(os.tmpdir(), `c3-buggy-${process.pid}`);
    fs.cpSync(path.join(out, 'subject-src'), buggy, { recursive: true });
    const f = path.join(buggy, 'src/registration.js');
    fs.writeFileSync(f, fs.readFileSync(f, 'utf8').replace('age > 65', 'age > 64'));
    const sb = makeSandbox({ runDir: out, subjectRoot: buggy });
    try {
      const failed = runJest(sb)
        .tests.filter((t) => t.status === 'failed')
        .map((t) => t.fullName);
      expect(failed).toEqual([
        '[REQ-EX-001] User registration age limit [SCN-EX-001-02][TST-EX-001-02-05] Age at and around the limits :: age=65, result=accepted',
      ]);
    } finally {
      removeSandbox(sb);
      fs.rmSync(buggy, { recursive: true, force: true });
    }
  });

  test('same input -> same test files (NFR4)', async () => {
    const again = freshRun();
    try {
      await run({ in: again, out: again, generatedAt: FIXED_TIME, model: model() });
      for (const f of [
        'c3/runnable_tests/REQ-EX-001.test.js',
        'c3/test_manifest.json',
        'c3/jest.config.cjs',
      ])
        expect(fs.readFileSync(path.join(again, f), 'utf8')).toBe(
          fs.readFileSync(path.join(out, f), 'utf8'),
        );
    } finally {
      fs.rmSync(again, { recursive: true, force: true });
    }
  });
});

describe('C3-10 scenarios without a usable plan', () => {
  test('a failed plan gets no test and is listed for C3-13 (stub)', async () => {
    const out = freshRun();
    try {
      await run({ in: out, out, generatedAt: FIXED_TIME, model: model({ act: 'nonsense(' }) });
      const m = JSON.parse(fs.readFileSync(path.join(out, 'c3/test_manifest.json'), 'utf8'));
      expect(m.tests.map((t: any) => t.scenario_id)).toEqual(['SCN-EX-001-01']);
      const src = fs.readFileSync(path.join(out, 'c3/runnable_tests/REQ-EX-001.test.js'), 'utf8');
      expect(src).not.toContain('SCN-EX-001-02');
    } finally {
      fs.rmSync(out, { recursive: true, force: true });
    }
  });
});

describe('C3-10 require lines for other export styles and mocks', () => {
  const sc = readC3Inputs(GOLDEN).scenarios[0]!;
  const plan = (act: string): ScenarioPlan => ({
    scenario_id: sc.scenarioId,
    requirement_id: sc.requirementId,
    source: 'model',
    attempts: 1,
    problems: [],
    function_under_test: ['makeBadge'],
    act,
    act_code: act,
    params: {},
    quoted_columns: [],
    assertions: [{ then: 'T1', category: 'equality', actual: 'result', expected: 'x' }],
    cases: [{ assertions: [0], categories: ['equality'] }],
    rule_categories: [],
    category_agreement: 1,
  });
  const base = {
    inputs: {
      runId: 'RUN-X',
      inDir: '.',
      scenarios: [{ ...sc, subject: { ...sc.subject, modulePath: 'lib/make-badge.js' } }],
      skipped: [],
    },
    strategies: [],
    behaviour: {
      prompt_version: '0',
      model: null,
      records: [
        {
          decision_id: 'MD-001',
          scenario_id: sc.scenarioId,
          source: 'model' as const,
          kind: 'returns' as const,
          value: 1760000000000,
          attempts: 1,
          problems: [],
          warnings: [],
        },
      ],
    },
  };

  test('module.exports = fn -> const fn = require(...); a global (Date.now) mock is a spy restored after each test', () => {
    const w = writeJestTests({
      ...base,
      plans: { prompt_version: '0', model: null, plans: [plan('makeBadge({ text: ["a", "b"] })')] },
      mockFile: {
        decisions: [
          {
            decision_id: 'MD-001',
            scenario_id: sc.scenarioId,
            module_path: 'lib/make-badge.js',
            dependency: {
              import_specifier: 'Date',
              symbol: 'now',
              kind: 'global_object',
              side_effect: 'time',
            },
            decision: 'mock',
            rule_id: 'R-04',
            reason: 'clock',
          },
        ],
      } as never,
      exports: new Map([
        [
          'lib/make-badge.js',
          [{ name: 'makeBadge', style: 'module' as const, line: 1, dependencies: [] }],
        ],
      ]),
    });
    const src = w.files.get('c3/runnable_tests/REQ-EX-001.test.js')!;
    expect(src).toContain('const makeBadge = require("../../subject-src/lib/make-badge");');
    expect(src).not.toContain('jest.mock(');
    expect(src).toContain('afterEach(() => jest.restoreAllMocks());');
    expect(src).toContain('jest.spyOn(Date, "now").mockReturnValue(1760000000000);');
  });
});
