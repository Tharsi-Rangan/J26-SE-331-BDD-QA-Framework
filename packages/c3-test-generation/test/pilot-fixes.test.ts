// C3-14 fix-3: the three kinds of false alarm found in Qwen run 1 on Express-5 (lib/utils.js).
// The "run 1" answers below are the ones Qwen gave (see the generated tests in the pilot run).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';
import {
  assertionPrompt,
  checkAssertionAnswer,
  inventedResultFields,
  outcomeLabel,
  planContext,
  ungroundedStrings,
  unquoteValue,
  unusedStepValues,
} from '../src/assert/plan.js';
import { readC3Inputs } from '../src/input/reader.js';
import { buildMockDecisions } from '../src/mock/decisions.js';
import { renderCase } from '../src/assert/templates.js';
import { renderValue } from '../src/assert/expr.js';
import type { C3ScenarioInput, ExampleRow, ScenarioStep } from '../src/input/types.js';
import { scanModule } from '../src/scan/scanner.js';
import type { ScannedExport } from '../src/scan/types.js';

const EXPORTS: ScannedExport[] = [
  {
    name: 'normalizeTypes',
    style: 'named',
    line: 4,
    dependencies: [],
    valueKind: 'function',
    params: ['types'],
    doc: 'Normalize `types`, for example "html" becomes "text/html". | @param {Array} types | @return {Array}',
  },
  {
    name: 'compileETag',
    style: 'named',
    line: 5,
    dependencies: [],
    valueKind: 'function',
    params: ['val'],
    doc: 'Compile "etag" value to function. | @param {Boolean|String|Function} val | @return {Function}',
  },
  {
    name: 'normalizeType',
    style: 'named',
    line: 1,
    dependencies: [],
    valueKind: 'function',
    params: ['type'],
    doc: 'Normalize the given `type`, for example "html" becomes "text/html". | @param {String} type | @return {Object}',
  },
  {
    name: 'compileTrust',
    style: 'named',
    line: 2,
    dependencies: [],
    valueKind: 'function',
    params: ['val'],
    doc: 'Compile "proxy trust" value to function. | @param {Boolean|String|Number|Array|Function} val | @return {Function}',
  },
  {
    name: 'setCharset',
    style: 'named',
    line: 3,
    dependencies: [],
    valueKind: 'function',
    params: ['type', 'charset'],
    doc: 'Set the charset in a given Content-Type string. | @param {String} type | @param {String} charset | @return {String}',
  },
];

function scenario(
  name: string,
  steps: [ScenarioStep['keyword'], string][],
  examples: ExampleRow[] = [],
): C3ScenarioInput {
  return {
    scenarioId: 'SCN-EXPRESS-002-02',
    requirementId: 'REQ-EXPRESS-002',
    scenarioName: name,
    featureName: 'Express pilot',
    scenarioType: examples.length ? 'boundary' : 'positive',
    isOutline: examples.length > 0,
    featureFile: 'c2/features/REQ-EXPRESS-002.feature',
    line: 3,
    steps: steps.map(([keyword, text], i) => ({ keyword, text, line: 4 + i })),
    examples,
    metadata: {} as C3ScenarioInput['metadata'],
    subject: {
      subjectId: 'SUB-EXPRESS-5',
      projectCode: 'EXPRESS',
      modulePath: 'lib/utils.js',
      exports: EXPORTS.map((e) => e.name),
      source: {},
    },
  };
}

const QUALITY = scenario('Parse the quality of a full type', [
  ['Given', 'the type "text/html; q=0.5"'],
  ['When', 'the type is normalized'],
  ['Then', 'the value is "text/html" and the quality is 0.5'],
]);
const HOPS = scenario(
  'Trust a number of hops',
  [
    ['Given', 'the trust setting 2'],
    ['When', 'hop <hop> is checked'],
    ['Then', 'the trust result is <trusted>'],
  ],
  [
    { rowIndex: 1, values: { hop: '0', trusted: 'true' } },
    { rowIndex: 2, values: { hop: '5', trusted: 'false' } },
  ],
);
const CHARSET = scenario('Set the charset of a type', [
  ['Given', 'the type "text/html" and the charset "utf-8"'],
  ['When', 'the charset is set'],
  ['Then', 'the type is "text/html; charset=utf-8"'],
]);

describe('C3-14 fix-3: quote marks copied into the value (run 1: 3 false alarms)', () => {
  test('a step value wrapped in quotes is unwrapped; other strings are kept', () => {
    expect(unquoteValue('"text/html; charset=utf-8"', CHARSET)).toBe('text/html; charset=utf-8');
    expect(unquoteValue(['"utf-8"', { t: '"text/html"' }], CHARSET)).toEqual([
      'utf-8',
      { t: 'text/html' },
    ]);
    expect(unquoteValue('"not in the steps"', CHARSET)).toBe('"not in the steps"');
    expect(unquoteValue('text/html', CHARSET)).toBe('text/html');
  });

  test('run 1 answer for setCharset now renders toBe("text/html; charset=utf-8")', () => {
    const ctx = planContext(CHARSET, EXPORTS, ['setCharset']);
    const raw = {
      act: 'setCharset("text/html", "utf-8")',
      assertions: [
        {
          then: 'T1',
          category: 'equality',
          actual: 'result',
          expected: '"text/html; charset=utf-8"',
        },
      ],
    };
    const c = checkAssertionAnswer(raw, ctx);
    expect(c.problems).toEqual([]);
    expect(c.assertions[0]!.expected).toBe('text/html; charset=utf-8');
    const plan = {
      scenario_id: CHARSET.scenarioId,
      act: c.act,
      act_code: c.actCode,
      quoted_columns: c.quoted,
      params: {},
      assertions: c.assertions,
      cases: c.cases,
    };
    expect(renderCase(plan as never, c.cases[0]!).join('\n')).toContain(
      'expect(result).toBe("text/html; charset=utf-8");',
    );
  });
});

describe('C3-14 fix-3: a Given/When value missing from the act (run 1: 2 false alarms)', () => {
  test('"the trust setting 2" must reach the call', () => {
    expect(unusedStepValues(HOPS, 'compileTrust(<hop>)')).toEqual([{ value: '2', step: 'S1' }]);
    expect(unusedStepValues(HOPS, 'compileTrust(2)("10.0.0.1", <hop>)')).toEqual([]);
  });

  test('quoted values and numbers inside quotes; placeholders are not values', () => {
    expect(unusedStepValues(CHARSET, 'setCharset("text/html")')).toEqual([
      { value: '"utf-8"', step: 'S1' },
    ]);
    expect(unusedStepValues(QUALITY, 'normalizeType("text/html; q=0.5")')).toEqual([]);
  });

  test('run 1 answer compileTrust(<hop>) is rejected with the reason; the retry can fix it', () => {
    const ctx = planContext(HOPS, EXPORTS, ['compileTrust']);
    const run1 = {
      act: 'compileTrust(<hop>)',
      assertions: [{ then: 'T1', category: 'equality', actual: 'result', expected: '<trusted>' }],
    };
    expect(checkAssertionAnswer(run1, ctx).problems.join('\n')).toMatch(
      /"act" does not use the step value\(s\) 2 \(S1\).*rule 7/,
    );
    const fixed = { ...run1, act: 'compileTrust(2)("10.0.0.1", <hop>)' };
    expect(checkAssertionAnswer(fixed, ctx).problems).toEqual([]);
  });
});

describe('C3-14 fix-3: invented result fields (run 1: result.type, result.q)', () => {
  const ctx = planContext(QUALITY, EXPORTS, ['normalizeType']);

  test('only Then-step words count; words inside quotes are values, not names', () => {
    expect(inventedResultFields('result.type', QUALITY, ctx)).toEqual(['type']);
    expect(inventedResultFields('result.q', QUALITY, ctx)).toEqual(['q']);
    expect(inventedResultFields('result.value', QUALITY, ctx)).toEqual([]);
    expect(inventedResultFields('result.quality', QUALITY, ctx)).toEqual([]);
    expect(inventedResultFields('result.length', QUALITY, ctx)).toEqual([]);
    expect(inventedResultFields('result.value.trim()', QUALITY, ctx)).toEqual([]); // a method, not a field
    expect(inventedResultFields('typeof result', QUALITY, ctx)).toEqual([]);
  });

  test('a short form of a Then word is allowed (params for "parameters")', () => {
    const sc = scenario('Expand a short type name', [
      ['Given', 'the type "html"'],
      ['When', 'the type is normalized'],
      ['Then', 'the value is "text/html" with no parameters'],
    ]);
    const c = planContext(sc, EXPORTS, ['normalizeType']);
    expect(inventedResultFields('result.params', sc, c)).toEqual([]);
    expect(inventedResultFields('result.p', sc, c)).toEqual(['p']);
  });

  test('run 1 answer is rejected; result.value + result.quality is accepted', () => {
    const run1 = {
      act: 'normalizeType("text/html; q=0.5")',
      assertions: [
        { then: 'T1', category: 'equality', actual: 'result.type', expected: 'text/html' },
        { then: 'T1', category: 'equality', actual: 'result.q', expected: 0.5 },
      ],
    };
    const p = checkAssertionAnswer(run1, ctx).problems.join('\n');
    expect(p).toMatch(/field\(s\) type that no step names/);
    expect(p).toMatch(/field\(s\) q that no step names/);
    const good = {
      ...run1,
      assertions: [
        { then: 'T1', category: 'equality', actual: 'result.value', expected: 'text/html' },
        { then: 'T1', category: 'equality', actual: 'result.quality', expected: 0.5 },
      ],
    };
    expect(checkAssertionAnswer(good, ctx).problems).toEqual([]);
  });
});

describe('C3-14 fix-3: the documented interface (JSDoc) goes into the prompt', () => {
  test('the prompt shows "@return {Function}" for compileTrust and the new rules 7-9', () => {
    const { user } = assertionPrompt(planContext(HOPS, EXPORTS, ['compileTrust']));
    expect(user).toContain(
      'Documented interface of compileTrust (its JSDoc): Compile "proxy trust" value to function. | @param {Boolean|String|Number|Array|Function} val | @return {Function}',
    );
    expect(user).toMatch(/7\. Every value written in the Given\/When steps is used in "act"/);
    expect(user).toMatch(/8\. "actual" may only use field names that the steps use/);
    expect(user).toMatch(/9\. Write string values without the quote marks/);
  });

  test('the scanner keeps description, @param and @return; drops @api and @private', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-doc-'));
    try {
      fs.writeFileSync(
        path.join(dir, 'm.js'),
        [
          '/**',
          ' * Check if `path` looks absolute.',
          ' *',
          ' * @param {String} path',
          ' * @return {Boolean}',
          ' * @api private',
          ' */',
          'exports.isAbsolute = function (path) { return path[0] === "/"; };',
          '',
          '/** Add two numbers. @private */',
          'function add(a, b) { return a + b; }',
          '',
          '// not a JSDoc comment',
          'function plain() {}',
          'module.exports.add = add;',
          'module.exports.plain = plain;',
        ].join('\n'),
      );
      const scan = scanModule(dir, 'm.js');
      const doc = Object.fromEntries(scan.exports.map((e) => [e.name, e.doc]));
      expect(doc.isAbsolute).toBe(
        'Check if `path` looks absolute. | @param {String} path | @return {Boolean}',
      );
      expect(doc.add).toBe('Add two numbers. @private');
      expect(doc.plain).toBeUndefined();
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});

// ---------------------------------------------------------------- fix-4 (run 2: 6 false alarms + 1 stub)

const ETAG = scenario(
  'Select the ETag function from the setting',
  [
    ['Given', 'the ETag setting <setting>'],
    ['When', 'the ETag function is compiled'],
    ['Then', 'the function is "<kind>"'],
  ],
  [
    { rowIndex: 1, values: { setting: 'true', kind: 'weak' } },
    { rowIndex: 2, values: { setting: 'weak', kind: 'weak' } },
    { rowIndex: 3, values: { setting: 'false', kind: 'none' } },
  ],
);
const TYPES = scenario('Normalize a list of types', [
  ['Given', 'the types "html" and "json"'],
  ['When', 'the types are normalized'],
  ['Then', '2 normalized types are returned'],
]);
const SHORT = scenario('Expand a short type name', [
  ['Given', 'the type "html"'],
  ['When', 'the type is normalized'],
  ['Then', 'the value is "text/html" with no parameters'],
]);
const LIST = scenario('Trust a list of addresses', [
  ['Given', 'the trust setting "127.0.0.1, 10.0.0.1"'],
  ['When', 'the address "10.0.0.1" is checked'],
  ['Then', 'the address is trusted'],
]);
const eq = (actual: string, expected: unknown, extra: object = {}) => ({
  then: 'T1',
  category: 'equality',
  actual,
  expected,
  ...extra,
});
const problemsOf = (sc: C3ScenarioInput, target: string, act: string, assertions: object[]) =>
  checkAssertionAnswer({ act, assertions }, planContext(sc, EXPORTS, [target])).problems.join('\n');

describe('C3-14 fix-4: the false alarms of run 2', () => {
  test('a documented Object result is not compared whole with a string (002-01)', () => {
    expect(
      problemsOf(SHORT, 'normalizeType', 'normalizeType("html")', [eq('result', 'text/html')]),
    ).toMatch(/documented result is Object, so all of result cannot equal "text\/html".*rule 8/);
    expect(
      problemsOf(SHORT, 'normalizeType', 'normalizeType("html")', [
        eq('result.value', 'text/html'),
      ]),
    ).toBe('');
  });

  test('keys of an expected object must be named by the Then step (002-02)', () => {
    const p = problemsOf(QUALITY, 'normalizeType', 'normalizeType("text/html; q=0.5")', [
      eq('result', { type: 'text/html', quality: 0.5 }),
    ]);
    expect(p).toMatch(/"expected" uses field\(s\) type that no step names/);
    expect(
      problemsOf(QUALITY, 'normalizeType', 'normalizeType("text/html; q=0.5")', [
        eq('result', { value: 'text/html', quality: 0.5 }),
      ]),
    ).not.toMatch(/field/);
  });

  test('strings the steps never state are rejected (002-03 "application/json")', () => {
    const p = problemsOf(TYPES, 'normalizeTypes', 'normalizeTypes(["html", "json"])', [
      eq('result.length', 2),
      eq('result[0]', 'text/html'),
      eq('result[1]', 'application/json'),
    ]);
    expect(p).toMatch(/"text\/html", which no step states/);
    expect(p).toMatch(/"application\/json", which no step states/);
    expect(
      problemsOf(TYPES, 'normalizeTypes', 'normalizeTypes(["html", "json"])', [
        eq('result.length', 2),
      ]),
    ).toBe('');
  });

  test('a Then step with <kind> needs "when" or "<kind>" (003-01: the "none" row)', () => {
    const run2 = [eq('typeof result', 'function')];
    expect(problemsOf(ETAG, 'compileETag', 'compileETag(<setting>)', run2)).toMatch(
      /Then step T1 depends on <kind>.*rule 11/,
    );
    const good = [
      eq('typeof result', 'function', { when: { column: 'kind', equals: 'weak' } }),
      eq('result', null, { when: { column: 'kind', equals: 'none' } }),
    ];
    expect(problemsOf(ETAG, 'compileETag', 'compileETag(<setting>)', good)).toBe('');
  });

  test('a <column> of a When step must reach the act (004-02: compileTrust(2) without <hop>)', () => {
    expect(
      problemsOf(HOPS, 'compileTrust', 'compileTrust(2)', [eq('result', '<trusted>')]),
    ).toMatch(/does not use the step value\(s\) <hop> \(S2\)/);
  });

  test('a list value passed split up counts as used (004-03 was stubbed in run 2)', () => {
    expect(unusedStepValues(LIST, 'compileTrust(["127.0.0.1", "10.0.0.1"])("10.0.0.1")')).toEqual(
      [],
    );
    expect(unusedStepValues(LIST, 'compileTrust(["10.0.0.1"])("10.0.0.1")')).toEqual([
      { value: '"127.0.0.1, 10.0.0.1"', step: 'S1' },
    ]);
  });

  test('an expected object renders as toMatchObject (the requirement names some fields, not all)', () => {
    const ctx = planContext(QUALITY, EXPORTS, ['normalizeType']);
    const c = checkAssertionAnswer(
      {
        act: 'normalizeType("text/html; q=0.5")',
        assertions: [eq('result', { value: 'text/html', quality: 0.5 })],
      },
      ctx,
    );
    const plan = {
      scenario_id: QUALITY.scenarioId,
      act: c.act,
      act_code: c.actCode,
      quoted_columns: c.quoted,
      params: {},
      assertions: c.assertions,
      cases: c.cases,
    };
    expect(renderCase(plan as never, c.cases[0]!).join('\n')).toContain(
      `expect(result).toMatchObject(${renderValue({ value: 'text/html', quality: 0.5 }, new Map())});`,
    );
  });
});

// ---------------------------------------------------------------- fix-5 (control run: golden outline stubbed)

describe('C3-14 fix-5: the control run (golden example, Qwen prompt 0.6.0)', () => {
  const GOLDEN = fileURLToPath(
    new URL('../../contracts/fixtures/golden/example-registration', import.meta.url),
  );
  const ctx = () => {
    const inputs = readC3Inputs(GOLDEN);
    const s = inputs.scenarios[0]!.subject;
    const scan = scanModule(path.join(GOLDEN, 'subject-src'), s.modulePath);
    const { file, targets } = buildMockDecisions(
      inputs,
      new Map([[`${s.subjectId}|${s.modulePath}`, scan]]),
      { generatedAt: '2026-10-19T10:00:00+05:30' },
    );
    const sc = inputs.scenarios[1]!;
    return planContext(sc, scan.exports, targets.get(sc.scenarioId)!.exports, file);
  };
  const row = (age: string, rest: object) => ({
    then: 'T1',
    when: { column: 'age', equals: age },
    ...rest,
  });
  const refused = { category: 'exception', error: 'ValidationError', message: null };
  const act = 'registerUser({ age: <age>, email: "test@example.com" })';

  test('Examples cells are stated values: "accepted" is no longer called invented', () => {
    const c = ctx();
    expect(ungroundedStrings('accepted', 'result', c.sc)).toEqual([]);
    expect(ungroundedStrings('approved', 'result', c.sc)).toEqual(['approved']);
  });

  test('attempt 1: result == "accepted" is named as an outcome label and rule 5 is given', () => {
    const attempt1 = {
      act,
      assertions: [
        row('17', refused),
        row('18', { category: 'equality', actual: 'result', expected: 'accepted' }),
        row('66', refused),
      ],
    };
    const p = checkAssertionAnswer(attempt1, ctx()).problems.join('\n');
    expect(p).toMatch(
      /"accepted" is an outcome label from the Examples column result, not what registerUser returns.*userRepository\.save was called \(state_change\).*rules 2, 5/,
    );
    expect(p).not.toMatch(/which no step states/);
  });

  test('attempt 2: "actual": "<result>" gets a clear message, not a parser error', () => {
    const attempt2 = {
      act,
      assertions: [row('18', { category: 'equality', actual: '<result>', expected: 'accepted' })],
    };
    const p = checkAssertionAnswer(attempt2, ctx()).problems.join('\n');
    expect(p).toMatch(/"actual" is what the call returns.*<column> values belong in "expected"/);
    expect(p).not.toMatch(/JSX/);
  });

  test('the answer rule 5 asks for passes: exception when rejected, save called when accepted', () => {
    const good = {
      act,
      assertions: [
        { then: 'T1', when: { column: 'result', equals: 'rejected' }, ...refused },
        {
          then: 'T1',
          when: { column: 'result', equals: 'accepted' },
          category: 'state_change',
          target: 'userRepository.save',
          change: 'called',
        },
      ],
    };
    expect(checkAssertionAnswer(good, ctx()).problems).toEqual([]);
  });

  test('without a mocked dependency a label may be a real return value (no outcome-label message)', () => {
    const c = { ...ctx(), mocks: [] };
    expect(outcomeLabel('accepted', 'result', c.sc, c)).toBeUndefined();
  });
});
