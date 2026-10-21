import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, test } from 'vitest';
import { run } from '../src/index.js';
import { readC3Inputs } from '../src/input/reader.js';
import type { ScenarioPlan } from '../src/assert/plan.js';
import { FakeModelClient } from '../src/model/index.js';
import {
  classifyFailure,
  isBroken,
  referentialProblems,
  semanticScore,
  syntaxError,
  type TestVerification,
  type VerificationWorkFile,
} from '../src/verify/verify.js';

const GOLDEN = fileURLToPath(
  new URL('../../contracts/fixtures/golden/example-registration', import.meta.url),
);
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
const model = () =>
  new FakeModelClient((req) => {
    const u = req.messages[1]!.content;
    if (u.includes('Mocked dependency:')) return JSON.stringify(B);
    return JSON.stringify(u.includes('Age at and around') ? A2 : A1);
  });

async function goldenRun(patch?: (src: string) => string) {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-v-'));
  fs.cpSync(GOLDEN, out, { recursive: true });
  for (const d of ['c3', 'c4']) fs.rmSync(path.join(out, d), { recursive: true, force: true });
  if (patch) {
    const f = path.join(out, 'subject-src/src/registration.js');
    fs.writeFileSync(f, patch(fs.readFileSync(f, 'utf8')));
  }
  await run({ in: out, out, generatedAt: FIXED_TIME, model: model() });
  const v = JSON.parse(
    fs.readFileSync(path.join(out, 'c3/work/verification.json'), 'utf8'),
  ) as VerificationWorkFile;
  const m = JSON.parse(fs.readFileSync(path.join(out, 'c3/test_manifest.json'), 'utf8'));
  return { out, v, m };
}

describe('C3-11 checks', () => {
  test('syntactic: a parse error is reported with its line', () => {
    expect(syntaxError('test("x", () => { expect(1).toBe(1); });')).toBeUndefined();
    expect(syntaxError('test("x", () => {\n  expect(1).toBe(1;\n});')).toMatch(/^line 2: /);
  });

  test('referential: module, export names and internal mocks must exist in the subject', () => {
    const root = path.join(GOLDEN, 'subject-src');
    const exportsList = [
      { name: 'registerUser', style: 'named' as const, line: 1, dependencies: [] },
      { name: 'ValidationError', style: 'named' as const, line: 1, dependencies: [] },
    ];
    const req = {
      repoPath: 'subject-src',
      module: 'src/registration.js',
      names: ['registerUser', 'ValidationError'],
      mocks: [
        {
          specifier: './userRepository',
          subjectPath: 'src/userRepository.js',
          kind: 'internal_module',
        },
      ],
    };
    expect(referentialProblems(req, exportsList, root)).toEqual([]);
    expect(referentialProblems({ ...req, names: ['register'] }, exportsList, root)).toEqual([
      'register is not an export of src/registration.js',
    ]);
    expect(referentialProblems({ ...req, module: 'src/nope.js' }, exportsList, root)[0]).toMatch(
      /not found/,
    );
  });

  test('semantic score: category agreement + values that appear in the steps', () => {
    const sc = readC3Inputs(GOLDEN).scenarios[0]!;
    const plan = (expected: unknown, category = 'state_change'): ScenarioPlan => ({
      scenario_id: sc.scenarioId,
      requirement_id: sc.requirementId,
      source: 'model',
      attempts: 1,
      problems: [],
      function_under_test: ['registerUser'],
      act: 'x',
      act_code: 'x',
      params: {},
      quoted_columns: [],
      assertions: [
        {
          then: 'T1',
          category: category as never,
          actual: 'result.age',
          expected,
          target: 't',
          change: 'called',
        },
      ],
      cases: [{ assertions: [0], categories: [category as never] }],
      rule_categories: [{ then: 'T1', category: 'state_change' }],
      category_agreement: 1,
    });
    // "Then the user is saved with age 30": rule says state_change
    expect(semanticScore(sc, plan(30))).toBe(1); // agrees, nothing invented (state_change has no args here)
    expect(semanticScore(sc, plan(30, 'equality'))).toBe(0.5); // disagrees; 30 is in the steps
    expect(semanticScore(sc, plan(31, 'equality'))).toBe(0); // disagrees; 31 is invented
  });

  test('semantic score: invented field names (not in the steps or the act) lower it', () => {
    const sc = readC3Inputs(GOLDEN).scenarios[0]!;
    const plan = (args: unknown[]): ScenarioPlan => ({
      scenario_id: sc.scenarioId,
      requirement_id: sc.requirementId,
      source: 'model',
      attempts: 1,
      problems: [],
      function_under_test: ['registerUser'],
      act: 'registerUser({ age: 30, email: "amal@example.com" })',
      act_code: 'x',
      params: {},
      quoted_columns: [],
      assertions: [
        {
          then: 'T1',
          category: 'state_change',
          target: 'userRepository.save',
          change: 'called_with',
          args,
        },
      ],
      cases: [{ assertions: [0], categories: ['state_change'] }],
      rule_categories: [{ then: 'T1', category: 'state_change' }],
      category_agreement: 1,
    });
    expect(semanticScore(sc, plan([{ age: 30, email: 'amal@example.com' }]))).toBe(1);
    expect(semanticScore(sc, plan([{ id: null, registered: true }]))).toBe(0.5); // agrees, but both fields invented
  });

  test('failure classification: expect() failure, error in the subject, error in the test', () => {
    const f = 'c3/runnable_tests/REQ-EX-001.test.js';
    expect(
      classifyFailure(['Error: expect(received).toBe(expected)\n\nExpected: 30'], f, 'subject-src'),
    ).toBe('assertion_failed');
    expect(
      classifyFailure(
        [
          'Error: age out of range\n    at registerUser (/tmp/sb/subject-src/src/registration.js:8:11)\n    at Object.<anonymous> (/tmp/sb/c3/runnable_tests/REQ-EX-001.test.js:5:3)',
        ],
        f,
        'subject-src',
      ),
    ).toBe('subject_error');
    expect(
      classifyFailure(
        [
          'TypeError: userRepository.save.mockReset is not a function\n    at Object.<anonymous> (/tmp/sb/c3/runnable_tests/REQ-EX-001.test.js:9:25)',
        ],
        f,
        'subject-src',
      ),
    ).toBe('test_error');
    expect(classifyFailure(['ReferenceError: registerUsr is not defined'], f, 'subject-src')).toBe(
      'test_error',
    );
  });

  test('isBroken: only failures inside the test count', () => {
    const t = (o: Partial<TestVerification>): TestVerification => ({
      test_id: 'TST-X-001-01-01',
      scenario_id: 'SCN-X-001-01',
      syntactic: 'pass',
      referential: 'pass',
      traceability: 'pass',
      semantic: { status: 'pass', score: 1 },
      run: 'passed',
      problems: [],
      ...o,
    });
    expect(isBroken(t({}))).toBe(false);
    expect(isBroken(t({ run: 'assertion_failed' }))).toBe(false);
    expect(isBroken(t({ run: 'subject_error' }))).toBe(false);
    expect(isBroken(t({ run: 'test_error' }))).toBe(true);
    expect(isBroken(t({ run: 'suite_error' }))).toBe(true);
    expect(isBroken(t({ referential: 'fail' }))).toBe(true);
    expect(isBroken(t({ semantic: { status: 'fail', score: 0.2 } }))).toBe(false); // low score -> confidence, not repair
  });
});

describe('C3-11 on the golden example (real Jest)', () => {
  let correct: Awaited<ReturnType<typeof goldenRun>>;
  let buggy: Awaited<ReturnType<typeof goldenRun>>;
  beforeAll(async () => {
    correct = await goldenRun();
    buggy = await goldenRun((s) => s.replace('age > 65', 'age > 64'));
  });
  afterAll(() => {
    for (const r of [correct, buggy]) fs.rmSync(r.out, { recursive: true, force: true });
  });

  test('correct code: all 7 tests pass all 4 checks; the manifest carries the results', () => {
    expect(correct.v.subject_run).toBe(true);
    expect(correct.v.tests.map((t) => t.run)).toEqual(Array(7).fill('passed'));
    for (const t of correct.m.tests) {
      expect(t.verification.syntactic).toBe('pass');
      expect(t.verification.referential).toBe('pass');
      expect(t.verification.traceability).toBe('pass');
      expect(t.verification.semantic.status).toBe('pass');
      expect(typeof t.verification.semantic.score).toBe('number');
    }
  });

  test('buggy code: the age-65 test is a possible bug found (subject_error), not a broken test', () => {
    const t = buggy.v.tests.find((x) => x.test_id === 'TST-EX-001-02-05')!;
    expect(t.run).toBe('subject_error');
    expect(t.message).toMatch(/age out of range/);
    expect(isBroken(t)).toBe(false);
    expect(buggy.v.tests.filter((x) => x.run !== 'passed').map((x) => x.test_id)).toEqual([
      'TST-EX-001-02-05',
    ]);
  });
});
