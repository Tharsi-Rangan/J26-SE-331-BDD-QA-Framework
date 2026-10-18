import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, test } from 'vitest';
import {
  assertionLines,
  classifyGap,
  classifyGaps,
  mutatedCode,
  type GapContext,
} from '../src/gap.js';
import { loadMockDecisions } from '../src/loader.js';
import { buildSurvivors, testsByStrykerId, type Survivor } from '../src/trace.js';
import type { ManifestTest, MutationReport, TestManifest } from '../src/types.js';

const golden = path.resolve(
  import.meta.dirname,
  '../../contracts/fixtures/golden/example-registration',
);
const readJson = <T>(rel: string) =>
  JSON.parse(fs.readFileSync(path.join(golden, rel), 'utf8')) as T;
const report = readJson<MutationReport>('c4/raw/mutation.json');
const manifest = readJson<TestManifest>('c3/test_manifest.json');
const goldenTestSource = fs.readFileSync(
  path.join(golden, 'c3/runnable_tests/REQ-EX-001.test.js'),
  'utf8',
);

const goldenCtx: GapContext = {
  report,
  tests: manifest.tests,
  testSource: (file) => fs.readFileSync(path.join(golden, file), 'utf8'),
  mockDecisions: loadMockDecisions(golden),
};

const FILE = 'src/m.js';
const SOURCE = [
  "const repo = require('./repo');",
  'function f(x) {',
  '  if (x > 10) {',
  "    throw new Error('too big');",
  '  }',
  '  repo.save(x);',
  '  return x * 2;',
  '}',
].join('\n');

const TEST_SOURCE = [
  "describe('[REQ-A-001] F', () => {",
  "  test('[SCN-A-001-01][TST-A-001-01-01] f works :: 3', () => {",
  '    expect(() => f(11)).toThrow(Error);',
  '    expect(f(3)).toBeDefined();',
  '  });',
  '});',
].join('\n');

const tst: ManifestTest = {
  test_id: 'TST-A-001-01-01',
  scenario_id: 'SCN-A-001-01',
  requirement_id: 'REQ-A-001',
  file: 'c3/runnable_tests/a.test.js',
  jest_full_name: '[REQ-A-001] F [SCN-A-001-01][TST-A-001-01-01] f works :: 3',
};

const ctx: GapContext = {
  report: { files: { [FILE]: { source: SOURCE, mutants: [] } } },
  tests: [tst],
  testSource: (file) => (file === tst.file ? TEST_SOURCE : undefined),
  mockDecisions: {
    decisions: [
      {
        decision_id: 'MD-001',
        scenario_id: 'SCN-A-001-01',
        dependency: { import_specifier: './repo', symbol: 'save' },
        decision: 'mock',
      },
    ],
  },
};

const survivor = (
  line: number,
  mutator: string,
  replacement: string,
  covered = true,
): Survivor => ({
  mutant_id: '1',
  file: FILE,
  location: { start: { line, column: 3 }, end: { line, column: 20 } },
  mutator,
  replacement,
  status: covered ? 'Survived' : 'NoCoverage',
  equivalent: false,
  trace: covered
    ? {
        test_ids: [tst.test_id],
        scenario_ids: [tst.scenario_id],
        requirement_ids: [tst.requirement_id],
        signal: 'coverage',
        confidence: 1,
      }
    : { test_ids: [], scenario_ids: [], requirement_ids: [], signal: 'none' },
});

describe('c4 gap classifier rules', () => {
  test('an equivalent mutant has no gap', () => {
    expect(
      classifyGap({ ...survivor(4, 'StringLiteral', '""'), equivalent: true }, ctx),
    ).toBeNull();
  });

  test('missing_test: no manifest test covers the mutant', () => {
    expect(classifyGap(survivor(7, 'ArithmeticOperator', 'x / 2', false), ctx)).toEqual({
      type: 'missing_test',
      evidence: 'return x * 2;',
      explanation:
        'No test in the manifest runs src/m.js:7, so a change to this code is not detected.',
    });
  });

  test('missing_test also when only the embedding signal traces the mutant', () => {
    const s = survivor(7, 'ArithmeticOperator', 'x / 2', false);
    s.trace = { ...s.trace, requirement_ids: ['REQ-A-001'], signal: 'embedding', confidence: 0.6 };
    expect(classifyGap(s, ctx)?.type).toBe('missing_test');
  });

  test('incomplete_mock: the mutated code calls a mocked dependency', () => {
    const gap = classifyGap(survivor(6, 'ArithmeticOperator', 'repo.save(x - 1)'), ctx);
    expect(gap).toMatchObject({ type: 'incomplete_mock', evidence: 'repo.save(x);' });
    expect(gap?.explanation).toContain('`save` from ./repo (MD-001)');
  });

  test('a no_mock decision or a decision for another scenario does not count', () => {
    const decision = ctx.mockDecisions!.decisions[0];
    for (const d of [
      { ...decision, decision: 'no_mock' },
      { ...decision, scenario_id: 'SCN-A-001-02' },
    ]) {
      const gap = classifyGap(survivor(6, 'ArithmeticOperator', 'x'), {
        ...ctx,
        mockDecisions: { decisions: [d] },
      });
      expect(gap?.type).toBe('weak_assertion');
    }
  });

  test('missing_boundary: an EqualityOperator mutant survives', () => {
    expect(classifyGap(survivor(3, 'EqualityOperator', 'x >= 10'), ctx)).toMatchObject({
      type: 'missing_boundary',
      evidence: 'if (x > 10) {',
    });
  });

  test('untested_branch: a branch mutator survives', () => {
    for (const m of ['ConditionalExpression', 'LogicalOperator', 'BlockStatement'])
      expect(classifyGap(survivor(3, m, 'false'), ctx)?.type).toBe('untested_branch');
  });

  test('weak_assertion: a type-only toThrow does not see a message change', () => {
    const gap = classifyGap(survivor(4, 'StringLiteral', '""'), ctx);
    expect(gap).toEqual({
      type: 'weak_assertion',
      evidence: 'expect(() => f(11)).toThrow(Error);',
      explanation:
        'The tests TST-A-001-01-01 check the error type but not the error message. So the tests do not see when StringLiteral changes it to `""`.',
    });
  });

  test('weak_assertion: a return mutant gets a value check as evidence', () => {
    const src = TEST_SOURCE.replace('toBeDefined()', 'toBe(6)');
    const gap = classifyGap(survivor(7, 'ArithmeticOperator', 'x / 2'), {
      ...ctx,
      testSource: () => src,
    });
    expect(gap?.evidence).toBe('expect(f(3)).toBe(6);');
    expect(gap?.explanation).toContain('run this code, but no assertion fails');
  });

  test('weak_assertion falls back to the mutated code when the test file is missing', () => {
    const gap = classifyGap(survivor(7, 'ArithmeticOperator', 'x / 2'), {
      ...ctx,
      testSource: () => undefined,
    });
    expect(gap).toMatchObject({ type: 'weak_assertion', evidence: 'return x * 2;' });
  });
});

describe('c4 gap helpers', () => {
  test('mutatedCode joins the changed lines', () => {
    const s = survivor(3, 'BlockStatement', '{}');
    s.location.end.line = 5;
    expect(mutatedCode(s, SOURCE)).toBe("if (x > 10) { throw new Error('too big'); }");
  });

  test('assertionLines finds a test.each body from its table row', () => {
    const t = manifest.tests.find((x) => x.test_id === 'TST-EX-001-02-01')!;
    expect(assertionLines(goldenTestSource, t)).toEqual([
      "expect(() => registerUser({ age, email: 'test@example.com' })).toThrow(ValidationError);",
      'expect(userRepository.save).not.toHaveBeenCalled();',
      "expect(() => registerUser({ age, email: 'test@example.com' })).not.toThrow();",
      'expect(userRepository.save).toHaveBeenCalledTimes(1);',
    ]);
  });

  test('assertionLines stops at the end of a plain test', () => {
    const t = manifest.tests.find((x) => x.test_id === 'TST-EX-001-01-01')!;
    expect(assertionLines(goldenTestSource, t)).toEqual([
      "expect(userRepository.save).toHaveBeenCalledWith({ age: 30, email: 'amal@example.com' });",
      'expect(saved.age).toBe(30);',
    ]);
  });

  test('assertionLines returns nothing when the TST id is not in the file', () => {
    expect(assertionLines(goldenTestSource, { ...tst, test_id: 'TST-Z-001-01-01' })).toEqual([]);
  });
});

describe('c4 gap classifier on the golden example', () => {
  test('mutant 12 is a weak_assertion, the same as the golden report', () => {
    const survivors = classifyGaps(
      buildSurvivors(report, testsByStrykerId(report, manifest.tests)),
      goldenCtx,
    );
    const golden12 = readJson<{ survivors: { gap: { type: string } }[] }>('c4/adequacy_report.json')
      .survivors[0];
    expect(survivors).toHaveLength(1);
    expect(survivors[0].gap?.type).toBe(golden12.gap.type);
    expect(survivors[0].gap?.evidence).toBe(
      "expect(() => registerUser({ age, email: 'test@example.com' })).toThrow(ValidationError);",
    );
    expect(survivors[0].gap?.explanation).toContain(
      'check the error type but not the error message',
    );
  });

  test('loadMockDecisions reads the golden file and returns undefined when there is none', () => {
    expect(goldenCtx.mockDecisions?.decisions.map((d) => d.decision_id)).toEqual([
      'MD-001',
      'MD-002',
    ]);
    expect(loadMockDecisions(path.join(golden, 'c4'))).toBeUndefined();
  });
});
