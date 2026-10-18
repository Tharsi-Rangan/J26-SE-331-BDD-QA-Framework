import type { Survivor } from './trace.js';
import type { ManifestTest, MockDecisions, MutationReport } from './types.js';

export type GapType =
  'missing_test' | 'weak_assertion' | 'untested_branch' | 'incomplete_mock' | 'missing_boundary';

/** The `gap` object of a survivor in the C4 contract. */
export interface Gap {
  type: GapType;
  evidence: string;
  explanation: string;
}

/** What the classifier reads besides the survivors. */
export interface GapContext {
  report: MutationReport;
  tests: ManifestTest[];
  /** Source of a C3 test file, by its manifest `file` path. Returns undefined when the file is missing. */
  testSource: (file: string) => string | undefined;
  mockDecisions?: MockDecisions;
}

const BRANCH_MUTATORS = new Set([
  'ConditionalExpression',
  'LogicalOperator',
  'BlockStatement',
  'OptionalChaining',
]);

/** The source lines that the mutant changes, trimmed and joined with a space. */
export function mutatedCode(s: Survivor, source = ''): string {
  return source
    .split('\n')
    .slice(s.location.start.line - 1, s.location.end.line)
    .map((l) => l.trim())
    .join(' ');
}

/**
 * The `expect(...)` lines in the body of one test, found by its TST id.
 * For `test.each`, the body is the one after the table row with the id.
 */
export function assertionLines(testSource: string, test: ManifestTest): string[] {
  const lines = testSource.split('\n');
  const idx = lines.findIndex((l) => l.includes(test.test_id));
  if (idx < 0) return [];
  let start = lines.findIndex(
    (l, i) => i >= idx && l.includes(test.scenario_id) && l.includes('=>'),
  );
  if (start < 0) start = idx;

  const out: string[] = [];
  let depth = 0;
  let opened = false;
  for (let i = start; i < lines.length; i++) {
    if (i > start && lines[i].includes('expect(')) out.push(lines[i].trim());
    for (const ch of lines[i]) {
      if (ch === '{') {
        depth++;
        opened = true;
      } else if (ch === '}') depth--;
    }
    if (opened && depth <= 0) break;
  }
  return out;
}

const THROW_CHECK = /\)\.toThrow\(/;
const VALUE_CHECK = /\.(toBe|toEqual|toStrictEqual|toMatchObject)\(/;

/** The assertion that should catch the mutant: a `toThrow` for a throw, a value check for a return. */
function pickAssertion(code: string, candidates: string[]): string | undefined {
  const prefer = /\bthrow\b/.test(code)
    ? THROW_CHECK
    : /\breturn\b/.test(code)
      ? VALUE_CHECK
      : undefined;
  return (prefer && candidates.find((l) => prefer.test(l))) ?? candidates[0];
}

const escapeRegExp = (t: string) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** A mocked dependency that the mutated code calls, for the scenarios of the trace. */
function mockedCall(s: Survivor, code: string, mocks?: MockDecisions) {
  return mocks?.decisions.find(
    (d) =>
      d.decision === 'mock' &&
      s.trace.scenario_ids.includes(d.scenario_id) &&
      new RegExp(`(^|[^\\w$])${escapeRegExp(d.dependency.symbol)}\\s*\\(`).test(code),
  );
}

const change = (s: Survivor) =>
  s.replacement !== undefined ? `${s.mutator} changes it to \`${s.replacement}\`` : s.mutator;

/**
 * Give one survivor a gap type, evidence and explanation. The first rule that matches wins.
 * Equivalent mutants get null, because they are not a test gap.
 */
export function classifyGap(s: Survivor, ctx: GapContext): Gap | null {
  if (s.equivalent) return null;
  const code = mutatedCode(s, ctx.report.files[s.file]?.source);
  const where = `${s.file}:${s.location.start.line}`;

  if (s.trace.test_ids.length === 0)
    return {
      type: 'missing_test',
      evidence: code,
      explanation: `No test in the manifest runs ${where}, so a change to this code is not detected.`,
    };

  const mock = mockedCall(s, code, ctx.mockDecisions);
  if (mock)
    return {
      type: 'incomplete_mock',
      evidence: code,
      explanation: `The tests mock \`${mock.dependency.symbol}\` from ${mock.dependency.import_specifier} (${mock.decision_id}). No assertion on the mock fails when ${change(s)}.`,
    };

  if (s.mutator === 'EqualityOperator')
    return {
      type: 'missing_boundary',
      evidence: code,
      explanation: `No test uses the exact boundary value of this comparison, so the tests do not see when ${change(s)}.`,
    };

  if (BRANCH_MUTATORS.has(s.mutator))
    return {
      type: 'untested_branch',
      evidence: code,
      explanation: `No test checks the result of this branch at ${where}, so the tests do not see when ${change(s)}.`,
    };

  const byId = new Map(ctx.tests.map((t) => [t.test_id, t]));
  const candidates = s.trace.test_ids.flatMap((id) => {
    const t = byId.get(id);
    const src = t && ctx.testSource(t.file);
    return t && src ? assertionLines(src, t) : [];
  });
  const assertion = pickAssertion(code, candidates);
  const typeOnly =
    assertion !== undefined &&
    s.mutator === 'StringLiteral' &&
    /\bthrow\b/.test(code) &&
    /\)\.toThrow\(\s*[A-Za-z_$][\w$]*\s*\)/.test(assertion);
  return {
    type: 'weak_assertion',
    evidence: assertion ?? code,
    explanation: typeOnly
      ? `The tests ${s.trace.test_ids.join(', ')} check the error type but not the error message. So the tests do not see when ${change(s)}.`
      : `The tests ${s.trace.test_ids.join(', ')} run this code, but no assertion fails when ${change(s)}.`,
  };
}

/** Add a `gap` to every survivor. */
export function classifyGaps(survivors: Survivor[], ctx: GapContext): Survivor[] {
  return survivors.map((s) => ({ ...s, gap: classifyGap(s, ctx) }));
}
