// C3 BugsJS batch, fix-6: the false alarms of the first real Qwen run on the 9 new bugs (21 Oct 2026).
// Every answer below is the one Qwen2.5-Coder-7B gave in that run (from its answer cache). Each test shows the
// answer is now handled by a general rule; the scenarios are the real fixtures in fixtures/bugsjs.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';
import {
  checkAssertionAnswer,
  copiedFromInput,
  jsonLiterals,
  planContext,
  unquoteValue,
} from '../src/assert/plan.js';
import { replacePlaceholders } from '../src/assert/expr.js';
import { renderCase } from '../src/assert/templates.js';
import { readC3Inputs } from '../src/input/reader.js';
import { checkAnswer, defaultStructured } from '../src/mock/behaviour.js';
import type { MockDecision } from '../src/mock/decisions.js';
import type { ScannedExport } from '../src/scan/types.js';

const FIX = fileURLToPath(new URL('../fixtures/bugsjs', import.meta.url));
const sc = (bug: string, id: string) => {
  const s = readC3Inputs(path.join(FIX, bug)).scenarios.find((x) => x.scenarioId === id);
  if (!s) throw new Error(`no ${id} in ${bug}`);
  return s;
};
const fn = (name: string, params: string[], doc?: string): ScannedExport => ({
  name,
  style: 'named',
  line: 1,
  dependencies: [],
  valueKind: 'function',
  params,
  ...(doc ? { doc } : {}),
});
const check = (bug: string, id: string, exp: ScannedExport, answer: object) => {
  const s = sc(bug, id);
  const ctx = planContext(s, [exp], [exp.name]);
  return { s, ctx, out: checkAssertionAnswer(JSON.parse(JSON.stringify(answer)), ctx) };
};

const MERGE = fn(
  'merge',
  ['target', 'src', 'combine', 'isRule'],
  'Merges two config objects. This will not only add missing keys, but will also modify values to match. | @param {Object} target config object | @param {Object} src config object. Overrides in this config object will take priority over base. | @returns {Object} merged config object.',
);

describe('fix-6: a list or object written as JSON text (eslint-267, eslint-281)', () => {
  test('run 1: expected "[\\"warn\\", \\"allow-null\\"]" is the list the Then step states, rendered with toEqual', () => {
    const { out, s } = check('eslint-267', 'SCN-ESL267-001-01', MERGE, {
      act: 'merge({ rules: { eqeqeq: ["error", "allow-null"] } }, { rules: { eqeqeq: "warn" } }, undefined, true)',
      assertions: [
        {
          then: 'T1',
          category: 'equality',
          actual: 'result.rules.eqeqeq',
          expected: '["warn", "allow-null"]',
        },
      ],
    });
    expect(out.problems).toEqual([]);
    expect(out.assertions[0]!.expected).toEqual(['warn', 'allow-null']);
    expect(unquoteValue('["warn", "allow-null"]', s)).toEqual(['warn', 'allow-null']);
  });

  test('run 1: expected "{\\"foo\\": true}" is an object; its key foo is named by the Then step', () => {
    const { out } = check('eslint-267', 'SCN-ESL267-001-02', MERGE, {
      act: 'merge({}, { "globals": { "foo": true } }, undefined, undefined)',
      assertions: [
        { then: 'T1', category: 'equality', actual: 'result.globals', expected: '{"foo": true}' },
      ],
    });
    expect(out.problems).toEqual([]);
    expect(out.assertions[0]!.expected).toEqual({ foo: true });
  });

  test('JSON text that no step states stays a string', () => {
    expect(unquoteValue('["a"]', sc('eslint-267', 'SCN-ESL267-001-01'))).toBe('["a"]');
  });

  test('jsonLiterals finds lists and objects in step text, not in quoted words', () => {
    expect(jsonLiterals('Then the configurations are [2, [2, "always"], [2, "never"]]')).toEqual([
      [2, [2, 'always'], [2, 'never']],
    ]);
    expect(jsonLiterals('Then the merged globals are {"foo": true}')).toEqual([{ foo: true }]);
    expect(jsonLiterals('Given the path "/home/user"')).toEqual([]);
  });
});

describe('fix-6 rule 12: a Then step that writes the value out is checked against the whole value (eslint-273)', () => {
  const GEN = fn(
    'generateConfigsFromSchema',
    ['schema'],
    "Generate valid rule configurations based on a schema object | @param {Object} schema A rule's schema object | @returns {array[]} Valid rule configurations",
  );
  test('run 1: result.length 2 for "the configurations are [2]" is rejected', () => {
    const { out } = check('eslint-273', 'SCN-ESL273-001-01', GEN, {
      act: 'generateConfigsFromSchema([])',
      assertions: [{ then: 'T1', category: 'equality', actual: 'result.length', expected: 2 }],
    });
    expect(out.problems.join('\n')).toMatch(/Then step T1 states the value \[2\].*rule 12/);
  });
  test('the answer rule 12 asks for passes and renders toEqual([2])', () => {
    const { out, ctx } = check('eslint-273', 'SCN-ESL273-001-01', GEN, {
      act: 'generateConfigsFromSchema([])',
      assertions: [{ then: 'T1', category: 'equality', actual: 'result', expected: [2] }],
    });
    expect(out.problems).toEqual([]);
    expect(renderCase({ ...planFrom(out, ctx) }, out.cases[0]!).join('\n')).toContain(
      'toEqual([2])',
    );
  });
});

describe('fix-6: invented input fields in the call (shields-4)', () => {
  test('run 1: makeBadge({ text: "build", status: "passed" }) is rejected: no step names "status"', () => {
    const { out } = check('shields-4', 'SCN-SHLD4-001-01', fn('makeBadge', ['data']), {
      act: 'makeBadge({ text: "build", status: "passed" }, "<template>")',
      assertions: [
        { then: 'T1', category: 'equality', actual: 'typeof result', expected: 'string' },
      ],
    });
    expect(out.problems.join('\n')).toMatch(/passes the field\(s\) status that no step/);
  });
  test('the documented format object passes', () => {
    const { out } = check('shields-4', 'SCN-SHLD4-001-01', fn('makeBadge', ['data']), {
      act: 'makeBadge({ text: ["build", "passed"], template: "<template>" })',
      assertions: [
        { then: 'T1', category: 'equality', actual: 'typeof result', expected: 'string' },
      ],
    });
    expect(out.problems).toEqual([]);
  });
});

describe('fix-6: HTML inside a string is text, not a <placeholder> (hexo-7)', () => {
  const TOC = fn('tocHelper', ['str', 'options']);
  test('run 1: tocHelper("<p>No headings here</p>") with expected "" is accepted', () => {
    const { out } = check('hexo-7', 'SCN-HEXO7-001-01', TOC, {
      act: 'tocHelper("<p>No headings here</p>")',
      assertions: [{ then: 'T1', category: 'equality', actual: 'result', expected: '' }],
    });
    expect(out.problems).toEqual([]);
    expect(out.actCode).toBe('tocHelper("<p>No headings here</p>")');
  });
  test('a real column inside quotes is still a placeholder; an unknown bare <name> is still reported', () => {
    const params = new Map([['template', 'template']]);
    expect(replacePlaceholders('f("<template>", "<b>x</b>")', params).code).toBe(
      'f(template, "<b>x</b>")',
    );
    expect(replacePlaceholders('f(<hop>)', params).unknown).toEqual(['hop']);
  });
  test('run 1: the input copied as the expected output is rejected (no Then step states it)', () => {
    const { out, s, ctx } = check('hexo-7', 'SCN-HEXO7-001-02', TOC, {
      act: 'tocHelper("<h1 id=\'intro\'>Intro</h1>")',
      assertions: [
        {
          then: 'T1',
          category: 'equality',
          actual: 'result',
          expected: "<h1 id='intro'>Intro</h1>",
        },
      ],
    });
    expect(out.problems.join('\n')).toMatch(
      /is the input of a Given\/When step; no Then step states it/,
    );
    expect(copiedFromInput('string', s, ctx)).toBeUndefined(); // typeof words are fine
  });
});

describe('fix-6: backslashes and mocks that must fit their type (eslint-23)', () => {
  const RES = fn('resolveFileGlobPatterns', ['patterns', 'options']);
  test('run 1 retry: "src\\app.js" written without doubling the backslash is rejected', () => {
    const { out } = check('eslint-23', 'SCN-ESL23-001-02', RES, {
      act: 'resolveFileGlobPatterns(["src\\app.js"], {})',
      assertions: [
        { then: 'T1', category: 'equality', actual: 'result', expected: ['src/app.js'] },
      ],
    });
    expect(out.problems.join('\n')).toMatch(/a backslash in a string must be doubled/);
  });
  test('run 1 first answer: "src\\\\app.js" (doubled) is accepted and counts as the step value', () => {
    const { out } = check('eslint-23', 'SCN-ESL23-001-02', RES, {
      act: 'resolveFileGlobPatterns(["src\\\\app.js"], {})',
      assertions: [
        { then: 'T1', category: 'equality', actual: 'result', expected: ['src/app.js'] },
      ],
    });
    expect(out.problems).toEqual([]);
  });

  const CWD = {
    decision_id: 'MD-004',
    scenario_id: 'SCN-ESL23-001-01',
    module_path: 'lib/util/glob-util.js',
    dependency: {
      import_specifier: 'process',
      symbol: 'cwd',
      kind: 'global_object',
      side_effect: 'io',
    },
    decision: 'mock',
    rule_id: 'R-05',
    reason: 'reads the environment',
  } as unknown as MockDecision;
  test('run 1: cwd() as returns_input with an object is rejected; it takes no input and returns a string', () => {
    const problems = checkAnswer(
      {
        steps: ['S1'],
        kind: 'returns_input',
        value: { cwd: '/path/to/project' },
        error_message: null,
        summary: "cwd() returns '/path/to/project'.",
        rationale: 'The function needs the current working directory to resolve file patterns.',
      },
      sc('eslint-23', 'SCN-ESL23-001-01'),
      CWD,
    );
    expect(problems.join('\n')).toMatch(
      /cwd\(\) takes no input, so returns_input cannot work; use returns with a string/,
    );
    const ok = checkAnswer(
      {
        steps: ['S1'],
        kind: 'returns',
        value: '/path/to/project',
        error_message: null,
        summary: "cwd() returns '/path/to/project'.",
        rationale: 'The function needs the current working directory to resolve file patterns.',
      },
      sc('eslint-23', 'SCN-ESL23-001-01'),
      CWD,
    );
    expect(ok).toEqual([]);
  });
  test('the rule default for cwd() is a path string, not null', () => {
    expect(defaultStructured(CWD)).toEqual({ kind: 'returns', value: '/project' });
  });
});

/** A minimal plan for renderCase from a checked answer. */
function planFrom(
  out: ReturnType<typeof checkAssertionAnswer>,
  ctx: ReturnType<typeof planContext>,
) {
  return {
    scenario_id: ctx.sc.scenarioId,
    requirement_id: ctx.sc.requirementId,
    source: 'model' as const,
    attempts: 1,
    problems: [],
    function_under_test: ctx.targets,
    act: out.act,
    act_code: out.actCode,
    params: Object.fromEntries(ctx.params),
    quoted_columns: out.quoted,
    assertions: out.assertions,
    cases: out.cases,
    rule_categories: [],
    category_agreement: 1,
  };
}
