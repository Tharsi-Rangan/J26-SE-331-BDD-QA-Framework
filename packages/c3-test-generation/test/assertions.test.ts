import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test, vi } from 'vitest';
import { run } from '../src/index.js';
import { readC3Inputs } from '../src/input/reader.js';
import {
  assertionPrompt,
  checkAssertionAnswer,
  mockLocalName,
  planAssertions,
  planContext,
  planScenario,
  ruleCategory,
  type PlanContext,
  type ScenarioPlan,
} from '../src/assert/plan.js';
import { renderCase } from '../src/assert/templates.js';
import { checkExpression, renderValue, replacePlaceholders } from '../src/assert/expr.js';
import { buildMockDecisions } from '../src/mock/decisions.js';
import { FakeModelClient } from '../src/model/index.js';
import { scanModule } from '../src/scan/scanner.js';

const GOLDEN = fileURLToPath(
  new URL('../../contracts/fixtures/golden/example-registration', import.meta.url),
);
const FIXED_TIME = '2026-10-19T10:00:00+05:30';

function goldenContexts(): PlanContext[] {
  const inputs = readC3Inputs(GOLDEN);
  const s = inputs.scenarios[0]!.subject;
  const scan = scanModule(path.join(GOLDEN, 'subject-src'), s.modulePath);
  const { file, targets } = buildMockDecisions(
    inputs,
    new Map([[`${s.subjectId}|${s.modulePath}`, scan]]),
    { generatedAt: FIXED_TIME },
  );
  return inputs.scenarios.map((sc) =>
    planContext(sc, scan.exports, targets.get(sc.scenarioId)!.exports, file),
  );
}

/** Answers a good model gives for the 2 golden scenarios. */
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
      change: 'called_times',
      times: 1,
    },
  ],
};
const goodModel = () =>
  new FakeModelClient((req) =>
    JSON.stringify(req.messages[1]!.content.includes('Age at and around') ? A2 : A1),
  );

describe('C3-08 rule-based category guess', () => {
  test.each([
    ['the registration result is "rejected"', 'exception'],
    ['a validation error is shown', 'exception'],
    ['the user is saved with age 30', 'state_change'],
    ['the email is not sent', 'state_change'],
    ['the discount is between 5 and 10 percent', 'range'],
    ['at least 3 items are returned', 'range'],
    ['the path is absolute', 'equality'],
    ['the value is "text/html" with no parameters', 'equality'],
  ])('%s -> %s', (text, cat) => {
    expect(ruleCategory(text)).toBe(cat);
  });
});

describe('C3-08 expression helpers', () => {
  test('quoted placeholders become string parameters, bare ones typed parameters', () => {
    const r = replacePlaceholders(
      'f({ age: <age> }, "<path>")',
      new Map([
        ['age', 'age'],
        ['path', 'path'],
      ]),
    );
    expect(r.code).toBe('f({ age: age }, path)');
    expect(r.used.get('path')!.quoted).toBe(true);
    expect(r.used.get('age')!.quoted).toBe(false);
  });

  test('unknown names, syntax errors and statements are rejected', () => {
    expect(checkExpression('fetch("x")', new Set()).problems.join()).toMatch(
      /unknown name\(s\): fetch/,
    );
    expect(checkExpression('f(', new Set(['f'])).ok).toBe(false);
    expect(checkExpression('a = 1, b', new Set(['a', 'b'])).ok).toBe(true); // still one expression
    expect(checkExpression('require("fs")', new Set()).problems.join()).toMatch(/require/);
    expect(checkExpression('process.exit(1)', new Set()).problems.join()).toMatch(/process/);
  });

  test('C3-14 pilot: the call of a returned function keeps the export as its callee', () => {
    const c = checkExpression('compileTrust(2)("10.0.0.1", 0)', new Set(['compileTrust']));
    expect(c.ok).toBe(true);
    expect(c.callee).toBe('compileTrust');
    expect(checkExpression('compileETag(true)', new Set(['compileETag'])).callee).toBe(
      'compileETag',
    );
  });

  test('renderValue keeps JSON literals and turns "<col>" into the parameter', () => {
    const p = new Map([['age', 'age']]);
    expect(renderValue({ age: '<age>', email: 'a@b.c' }, p)).toBe('{ age: age, email: "a@b.c" }');
    expect(renderValue('age is <age>', p)).toBe('`age is ${age}`');
    expect(renderValue([1, true, null], p)).toBe('[1, true, null]');
  });

  test('mock local names', () => {
    expect(mockLocalName('./userRepository')).toBe('userRepository');
    expect(mockLocalName('../lib/make-badge.js')).toBe('makeBadge');
    expect(mockLocalName('node:fs')).toBe('fs');
  });
});

describe('C3-08 prompt', () => {
  const [c1, c2] = goldenContexts();

  test('gives parameter names, not code; lists mocks, steps (S/T ids) and Examples rows', () => {
    const { user } = assertionPrompt(c2!);
    expect(user).toContain('Function under test: registerUser({ age, email })');
    expect(user).toContain('Other exports: class ValidationError');
    expect(user).toContain('  userRepository.save');
    expect(user).toContain('S2: When a user registers with age <age>');
    expect(user).toContain('T1: Then the registration result is "<result>"');
    expect(user).toContain('  1: age=17, result=rejected');
    expect(user).not.toContain('throw new ValidationError'); // no source code of the function
    expect(user).toContain('4. Never check a field that only a mock returns');
    expect(user).toContain('6. Write "when" on the outcome column');
  });

  test('a scenario without mocks says not to use state_change', () => {
    const { user } = assertionPrompt({ ...c1!, mocks: [] });
    expect(user).toContain('none (do not use state_change)');
  });
});

describe('C3-08 answer check', () => {
  const [c1, c2] = goldenContexts();

  test('the good answers have no problems', () => {
    expect(checkAssertionAnswer(A1, c1!).problems).toEqual([]);
    expect(checkAssertionAnswer(A2, c2!).problems).toEqual([]);
  });

  test('act must call the function under test with known names', () => {
    const p = (act: string) => checkAssertionAnswer({ ...A1, act }, c1!).problems.join(' | ');
    expect(p('ValidationError()')).toMatch(/must call the function under test \(registerUser\)/);
    expect(p('registerUser(user)')).toMatch(/unknown name\(s\): user/);
    expect(p('registerUser({ age: <age> })')).toMatch(/no Examples/);
    expect(p('registerUser({ age: 30 }')).toMatch(/not a valid JS expression/);
  });

  test('slot problems are listed', () => {
    const p = (a: object) =>
      checkAssertionAnswer({ ...A1, assertions: [a] }, c1!).problems.join(' | ');
    expect(p({ then: 'T9', category: 'equality', expected: 1 })).toMatch(
      /"then" must be one of T1/,
    );
    expect(p({ then: 'T1', category: 'guess' })).toMatch(/"category" must be one of/);
    expect(p({ then: 'T1', category: 'equality' })).toMatch(/needs "expected"/);
    expect(p({ then: 'T1', category: 'equality', actual: 'age', expected: 1 })).toMatch(
      /unknown name/,
    );
    expect(p({ then: 'T1', category: 'exception', error: 'OopsError' })).toMatch(
      /not an exported class/,
    );
    expect(
      p({ then: 'T1', category: 'state_change', target: 'db.save', change: 'called' }),
    ).toMatch(/"target" must be one of userRepository.save/);
    expect(p({ then: 'T1', category: 'range', actual: 'result.age' })).toMatch(
      /needs "min" or "max"/,
    );
    expect(
      p({ then: 'T1', category: 'equality', expected: 1, when: { column: 'x', equals: 'y' } }),
    ).toMatch(/only for Scenario Outlines/);
  });

  test('rule 4: a result field that only the mock returns is a problem (tautology)', () => {
    const withMockFields: PlanContext = {
      ...c2!,
      mocks: c2!.mocks.map((m) => ({ ...m, mockFields: ['age', 'email', 'id', 'registered'] })),
    };
    const answer = {
      ...A2,
      assertions: [
        A2.assertions[0]!,
        {
          then: 'T1',
          when: { column: 'result', equals: 'accepted' },
          category: 'equality',
          actual: 'result.registered',
          expected: true,
        },
      ],
    };
    expect(checkAssertionAnswer(answer, withMockFields).problems.join()).toMatch(
      /result.registered only comes from the mock userRepository.save \(MD-002\)/,
    );
    // a field the act passes in is fine (the code under test decides what reaches save())
    const ok = {
      ...answer,
      assertions: [
        A2.assertions[0]!,
        { ...answer.assertions[1]!, actual: 'result.age', expected: '<age>' },
      ],
    };
    expect(checkAssertionAnswer(ok, withMockFields).problems).toEqual([]);
  });

  test('rule 4 for called_with: the real Qwen answer with invented args { id: null, registered: true } is rejected', () => {
    // From the real run on 19 Oct: the accepted rows expected save() to get fields that only the mock returns.
    const qwen = {
      act: 'registerUser({ age: <age>, email: "test@example.com" })',
      assertions: [
        {
          then: 'T1',
          when: { column: 'age', equals: '17' },
          category: 'exception',
          error: 'ValidationError',
        },
        ...['18', '19', '64', '65'].map((age) => ({
          then: 'T1',
          when: { column: 'age', equals: age },
          category: 'state_change',
          target: 'userRepository.save',
          change: 'called_with',
          args: [{ id: null, registered: true }],
        })),
        {
          then: 'T1',
          when: { column: 'age', equals: '66' },
          category: 'exception',
          error: 'ValidationError',
        },
      ],
    };
    const withMock: PlanContext = {
      ...c2!,
      mocks: c2!.mocks.map((m) => ({ ...m, mockFields: ['age', 'email', 'id', 'registered'] })),
    };
    const p = checkAssertionAnswer(qwen, withMock).problems.join(' | ');
    expect(p).toMatch(/args field "id" only comes from the mock userRepository.save \(MD-002\)/);
    expect(p).toMatch(/args field "registered" only comes from the mock/);
    // without mock fields it is still caught: no step names id or registered ("registers" is not "registered")
    const p2 = checkAssertionAnswer(qwen, c2!).problems.join(' | ');
    expect(p2).toMatch(/args field "id" is not passed in by the act and no step names it/);
    expect(p2).toMatch(/args field "registered" is not passed in by the act/);
  });

  test('called_with args that the act passes in are fine', () => {
    const withMock: PlanContext = {
      ...c2!,
      mocks: c2!.mocks.map((m) => ({ ...m, mockFields: ['age', 'email', 'id'] })),
    };
    const good = {
      ...A2,
      assertions: [
        A2.assertions[0]!,
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
    expect(checkAssertionAnswer(good, withMock).problems).toEqual([]);
  });

  test('planContext takes mock fields from the C3-07 work file', () => {
    const inputs = readC3Inputs(GOLDEN);
    const sc = inputs.scenarios[1]!;
    const ctx = planContext(
      sc,
      [],
      ['registerUser'],
      {
        decisions: [
          {
            decision_id: 'MD-002',
            scenario_id: sc.scenarioId,
            module_path: 'src/registration.js',
            dependency: {
              import_specifier: './userRepository',
              symbol: 'save',
              kind: 'internal_module',
              side_effect: 'database',
            },
            decision: 'mock',
            rule_id: 'R-03',
            reason: 'database I/O',
          },
        ],
      } as never,
      {
        prompt_version: 'x',
        model: null,
        records: [
          {
            decision_id: 'MD-002',
            scenario_id: sc.scenarioId,
            source: 'model',
            kind: 'returns_input',
            value: { registered: true, id: 1 },
            attempts: 1,
            problems: [],
            warnings: [],
          },
        ],
      },
    );
    expect(ctx.mocks).toEqual([
      {
        target: 'userRepository.save',
        decision_id: 'MD-002',
        summary: undefined,
        mockFields: ['id', 'registered'],
      },
    ]);
  });

  test('state_change with no mocked dependency is a problem', () => {
    const p = checkAssertionAnswer(A1, { ...c1!, mocks: [] }).problems.join();
    expect(p).toMatch(/state_change needs a mocked dependency/);
  });

  test('outlines: when must use a real column value; every row needs an assertion; no result check when throwing', () => {
    const bad = (assertions: object[]) =>
      checkAssertionAnswer({ ...A2, assertions }, c2!).problems.join(' | ');
    expect(bad([{ ...A2.assertions[0], when: { column: 'result', equals: 'denied' } }])).toMatch(
      /"denied" is not in column result \(rejected, accepted\)/,
    );
    expect(bad([A2.assertions[0]!])).toMatch(/row 2 has no assertion/);
    expect(
      bad([
        ...A2.assertions,
        {
          then: 'T1',
          when: { column: 'result', equals: 'rejected' },
          category: 'equality',
          expected: 1,
        },
      ]),
    ).toMatch(/row 1 both throws and checks result/);
  });
});

describe('C3-08 planScenario', () => {
  test('golden: cases per row with categories; agreement with the rule guess is recorded', async () => {
    const work = await planAssertions(goldenContexts(), goodModel());
    const [p1, p2] = work.plans as [ScenarioPlan, ScenarioPlan];
    expect(p1).toMatchObject({ source: 'model', attempts: 1, act_code: A1.act, await: false });
    expect(p1.cases).toEqual([{ assertions: [0, 1], categories: ['state_change', 'equality'] }]);
    expect(p1.category_agreement).toBe(1); // "is saved" -> state_change, and the model used it
    expect(p2.act_code).toBe('registerUser({ age: age, email: "test@example.com" })');
    expect(p2.params).toEqual({ age: 'age', result: 'ex_result' });
    expect(p2.cases.map((c) => [c.row, c.categories])).toEqual([
      [1, ['exception', 'state_change']],
      [2, ['state_change']],
      [3, ['state_change']],
      [4, ['state_change']],
      [5, ['state_change']],
      [6, ['exception', 'state_change']],
    ]);
    // rule says exception for "rejected" rows (agrees) and equality for "accepted" rows (model: state_change)
    expect(p2.category_agreement).toBe(0.333);
  });

  test('bad answer -> one retry listing the problems; two bad answers -> failed plan', async () => {
    const [c1] = goldenContexts();
    const bad = JSON.stringify({ ...A1, act: 'saveUser()' });
    const m1 = new FakeModelClient([bad, JSON.stringify(A1)]);
    const p = await planScenario(c1!, m1);
    expect(p).toMatchObject({ source: 'model', attempts: 2 });
    expect(m1.calls[1]!.messages.at(-1)!.content).toMatch(/unknown name\(s\): saveUser/);

    const m2 = new FakeModelClient(['no idea']);
    const f = await planScenario(c1!, m2);
    expect(f).toMatchObject({ source: 'failed', attempts: 2, cases: [], assertions: [] });
    expect(f.problems[0]).toMatch(/attempt 1: model answer is not valid JSON/);
  });

  test('no model -> every plan failed with the reason', async () => {
    const work = await planAssertions(goldenContexts(), undefined);
    expect(
      work.plans.every((p) => p.source === 'failed' && p.problems[0] === 'no model configured'),
    ).toBe(true);
  });
});

describe('C3-08 templates run against the golden registerUser', () => {
  /**
   * Copy the golden subject to a temp CommonJS folder (the contracts package is "type": "module") and load
   * it with a vi.fn() repository in Node's require cache (what jest.mock does). `patch` can inject a bug.
   */
  function loadGolden(patch: (src: string) => string = (x) => x) {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-golden-'));
    fs.cpSync(path.join(GOLDEN, 'subject-src'), tmp, { recursive: true });
    fs.writeFileSync(path.join(tmp, 'package.json'), '{"type": "commonjs"}');
    const reg = path.join(tmp, 'src/registration.js');
    fs.writeFileSync(reg, patch(fs.readFileSync(reg, 'utf8')));
    const req = createRequire(reg);
    const repoPath = req.resolve('./userRepository');
    const userRepository = { save: vi.fn((u: object) => ({ id: 'u1', ...u })) };
    req.cache[repoPath] = {
      id: repoPath,
      filename: repoPath,
      loaded: true,
      exports: userRepository,
    } as never;
    const mod = req('./registration');
    fs.rmSync(tmp, { recursive: true, force: true });
    return { ...mod, userRepository };
  }

  function runCase(
    plan: ScenarioPlan,
    row?: Record<string, unknown>,
    patch?: (s: string) => string,
  ) {
    const g = loadGolden(patch);
    const c = plan.cases.find((x) => x.row === row?.row) ?? plan.cases[0]!;
    const body = renderCase(plan, c).join('\n');
    const names = [
      'expect',
      'registerUser',
      'ValidationError',
      'userRepository',
      ...Object.values(plan.params),
    ];
    const values = [
      expect,
      g.registerUser,
      g.ValidationError,
      g.userRepository,
      ...Object.keys(plan.params).map((k) => row?.[k]),
    ];
    new Function(...names, body)(...values);
    return body;
  }

  test('golden scenario 1: rendered lines and they pass on the correct code', async () => {
    const [p1] = (await planAssertions(goldenContexts(), goodModel())).plans;
    const body = runCase(p1!);
    expect(body).toBe(
      [
        'const result = registerUser({ age: 30, email: "amal@example.com" });',
        'expect(userRepository.save).toHaveBeenCalledWith({ age: 30, email: "amal@example.com" });',
        'expect(result.age).toBe(30);',
      ].join('\n'),
    );
  });

  test('golden outline: every row passes on the correct code', async () => {
    const [, p2] = (await planAssertions(goldenContexts(), goodModel())).plans;
    const rows = [
      [1, 17, 'rejected'],
      [2, 18, 'accepted'],
      [3, 19, 'accepted'],
      [4, 64, 'accepted'],
      [5, 65, 'accepted'],
      [6, 66, 'rejected'],
    ] as const;
    for (const [row, age, result] of rows) runCase(p2!, { row, age, result });
    expect(renderCase(p2!, p2!.cases[0]!)).toEqual([
      'expect(() => registerUser({ age: age, email: "test@example.com" })).toThrow(ValidationError);',
      'expect(userRepository.save).not.toHaveBeenCalled();',
    ]);
  });

  test('the outline tests catch an off-by-one bug (age > 64 instead of age > 65)', async () => {
    const [, p2] = (await planAssertions(goldenContexts(), goodModel())).plans;
    const bug = (src: string) => src.replace('age > 65', 'age > 64');
    expect(() => runCase(p2!, { row: 5, age: 65, result: 'accepted' })).not.toThrow();
    expect(() => runCase(p2!, { row: 5, age: 65, result: 'accepted' }, bug)).toThrow(
      /age out of range/,
    );
    expect(() => runCase(p2!, { row: 6, age: 66, result: 'rejected' }, bug)).not.toThrow();
  });

  test('equality template choices: toBe, toEqual, toBeFalsy, toBeNull; range template', () => {
    const plan: ScenarioPlan = {
      scenario_id: 'SCN-X-001-01',
      requirement_id: 'REQ-X-001',
      source: 'model',
      attempts: 1,
      problems: [],
      function_under_test: ['f'],
      act: 'f(1)',
      act_code: 'f(1)',
      params: {},
      quoted_columns: [],
      assertions: [
        { then: 'T1', category: 'equality', actual: 'result', expected: 'a' },
        { then: 'T1', category: 'equality', actual: 'result.list', expected: [1, 2] },
        { then: 'T1', category: 'equality', actual: 'result.ok', expected: false },
        { then: 'T1', category: 'equality', actual: 'result.err', expected: null },
        {
          then: 'T1',
          category: 'range',
          actual: 'result.n',
          min: 1,
          max: 5,
          min_inclusive: false,
          max_inclusive: true,
        },
      ],
      cases: [{ assertions: [0, 1, 2, 3, 4], categories: ['equality', 'range'] }],
      rule_categories: [],
      category_agreement: 1,
    };
    expect(renderCase(plan, plan.cases[0]!)).toEqual([
      'const result = f(1);',
      'expect(result).toBe("a");',
      'expect(result.list).toEqual([1, 2]);',
      'expect(result.ok).toBeFalsy();',
      'expect(result.err ?? null).toBeNull();',
      'expect(result.n).toBeGreaterThan(1);',
      'expect(result.n).toBeLessThanOrEqual(5);',
    ]);
    expect(renderCase({ ...plan, await: true }, plan.cases[0]!)[0]).toBe(
      'const result = await f(1);',
    );
  });
});

describe('C3-08 inside c3 run', () => {
  test('writes c3/work/assertion_plan.json', async () => {
    const out = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-ap-'));
    try {
      await run({ in: GOLDEN, out, generatedAt: FIXED_TIME, model: goodModel() });
      const work = JSON.parse(
        fs.readFileSync(path.join(out, 'c3/work/assertion_plan.json'), 'utf8'),
      );
      expect(work.plans.map((p: ScenarioPlan) => p.source)).toEqual(['model', 'model']);
    } finally {
      fs.rmSync(out, { recursive: true, force: true });
    }
  });
});
