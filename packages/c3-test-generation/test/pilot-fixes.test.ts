// C3-14 fix-3: the three kinds of false alarm found in Qwen run 1 on Express-5 (lib/utils.js).
// The "run 1" answers below are the ones Qwen gave (see the generated tests in the pilot run).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, test } from 'vitest';
import {
  assertionPrompt,
  checkAssertionAnswer,
  inventedResultFields,
  planContext,
  unquoteValue,
  unusedStepValues,
} from '../src/assert/plan.js';
import { renderCase } from '../src/assert/templates.js';
import type { C3ScenarioInput, ExampleRow, ScenarioStep } from '../src/input/types.js';
import { scanModule } from '../src/scan/scanner.js';
import type { ScannedExport } from '../src/scan/types.js';

const EXPORTS: ScannedExport[] = [
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
