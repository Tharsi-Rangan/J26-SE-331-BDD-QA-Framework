// C3-11 four-layer verification (FR7, SO4), PP1 version. Every runnable test gets 4 check results, recorded
// in test_manifest.json `verification`, plus how it ran on the given subject version (c3/work/verification.json).
//   syntactic    the test file parses, and Jest loads it (no suite error)
//   referential  the require() targets exist in the subject, the names taken from the module under test are
//                real exports, and internal mocked modules exist
//   traceability the test id embeds its scenario id, the Jest name is [REQ] ... [SCN][TST] ..., the scenario
//                was fully verified by C2, and (when Jest ran) Jest reported exactly the manifest name
//   semantic     PP1: a rule-based grounding score (see semanticScore); the cross-encoder is planned for PP2
// Jest results are sorted by cause, because C3 runs on the subject C4 will mutate (often the BUGGY version):
//   passed           the test passed
//   assertion_failed an expect() failed           -> kept: may have found a bug (check on the fixed version)
//   subject_error    the code under test threw    -> kept: may have found a bug
//   test_error       the test code itself failed  -> broken test: C3-12 repairs it
//   suite_error      Jest could not load the file -> broken test: C3-12 repairs it
//   not_run          no subject to run against
import fs from 'node:fs';
import path from 'node:path';
import { ts } from 'ts-morph';
import type { C3Inputs, C3ScenarioInput } from '../input/types.js';
import { objectKeys, type AssertionSlot, type ScenarioPlan } from '../assert/plan.js';
import type { JestRunResult } from '../runner/jest.js';
import type { CheckStatus, ManifestTest, WrittenFiles } from '../writer/jest-writer.js';
import type { ScannedExport } from '../scan/types.js';

export const VERIFY_VERSION = '0.1.0';
export const SEMANTIC_PASS = 0.5;

export type RunStatus =
  'passed' | 'assertion_failed' | 'subject_error' | 'test_error' | 'suite_error' | 'not_run';

export interface TestVerification {
  test_id: string;
  scenario_id: string;
  syntactic: CheckStatus;
  referential: CheckStatus;
  traceability: CheckStatus;
  semantic: { status: CheckStatus; score: number };
  run: RunStatus;
  /** First lines of the failure, for repair prompts and humans. */
  message?: string;
  problems: string[];
}

export interface VerificationWorkFile {
  version: string;
  subject_run: boolean;
  tests: TestVerification[];
}

// ---------------------------------------------------------------- syntactic

/** Parse a JS file; returns the first syntax error, or undefined. */
export function syntaxError(code: string): string | undefined {
  const sf = ts.createSourceFile('t.js', code, ts.ScriptTarget.ES2022, true, ts.ScriptKind.JS);
  const d = (sf as unknown as { parseDiagnostics?: { messageText: unknown; start?: number }[] })
    .parseDiagnostics?.[0];
  if (!d) return undefined;
  const line = d.start !== undefined ? sf.getLineAndCharacterOfPosition(d.start).line + 1 : '?';
  return `line ${line}: ${typeof d.messageText === 'string' ? d.messageText : 'syntax error'}`;
}

// ---------------------------------------------------------------- referential

function resolvesInSubject(subjectRoot: string, rel: string): boolean {
  const base = path.join(subjectRoot, rel);
  return [base, `${base}.js`, `${base}.cjs`, `${base}.json`, path.join(base, 'index.js')].some(
    (f) => fs.existsSync(f) && fs.statSync(f).isFile(),
  );
}

/** Problems with what a test file requires (empty = pass). */
export function referentialProblems(
  req: NonNullable<ReturnType<WrittenFiles['requires']['get']>>,
  exportsList: ScannedExport[],
  subjectRoot: string,
): string[] {
  const problems: string[] = [];
  if (!resolvesInSubject(subjectRoot, req.module))
    problems.push(`module ${req.module} not found in the subject`);
  const names = new Set(exportsList.map((e) => e.name));
  for (const n of req.names)
    if (!names.has(n)) problems.push(`${n} is not an export of ${req.module}`);
  for (const m of req.mocks)
    if (
      m.kind === 'internal_module' &&
      m.subjectPath &&
      !resolvesInSubject(subjectRoot, m.subjectPath)
    )
      problems.push(`mocked module ${m.subjectPath} not found in the subject`);
  return problems;
}

// ---------------------------------------------------------------- semantic (PP1: grounding score)

/** Primitive values an assertion compares against (strings, numbers). Placeholders and booleans are skipped. */
function assertionValues(a: AssertionSlot): (string | number)[] {
  const out: (string | number)[] = [];
  const walk = (v: unknown) => {
    if (typeof v === 'number') out.push(v);
    else if (typeof v === 'string' && !/^<[^<>]+>$/.test(v)) out.push(v);
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
  };
  if (a.category === 'equality') walk(a.expected);
  if (a.category === 'range') walk([a.min, a.max]);
  if (a.category === 'state_change') walk(a.args);
  if (a.category === 'exception' && a.message) out.push(a.message);
  return out;
}

/** A value appears in the step text (numbers as whole tokens, strings case-insensitively). */
function grounded(v: string | number, text: string): boolean {
  if (typeof v === 'number')
    return new RegExp(`(^|[^0-9.])${String(v).replace('.', '\\.')}([^0-9]|$)`).test(text);
  return text.toLowerCase().includes(v.toLowerCase());
}

/**
 * Semantic score of one test (0..1), PP1 rule-based version:
 *   0.5 x share of this case's Then steps where the model's category matches the rule-based guess (C3-08)
 * + 0.5 x share of the assertion's literal values that appear in the scenario's steps (with this row's values)
 * Values the model invented (not in any step) lower the score; a test with no literal values gets full marks
 * for that half. The cross-encoder (requirement text vs. test) replaces this in PP2.
 */
export function semanticScore(sc: C3ScenarioInput, plan: ScenarioPlan, row?: number): number {
  const c = plan.cases.find((x) => x.row === row) ?? plan.cases[0];
  if (!c) return 0;
  const rules = plan.rule_categories.filter((r) => r.row === row);
  const slots = c.assertions.map((i) => plan.assertions[i]!);
  const agree = rules.length
    ? rules.filter((r) => slots.some((a) => a.then === r.then && a.category === r.category))
        .length / rules.length
    : 1;
  const values = sc.examples.find((r) => r.rowIndex === row)?.values ?? {};
  const text = sc.steps
    .map((s) => s.text.replace(/<([^<>]+)>/g, (m, col: string) => values[col] ?? m))
    .join(' \n ');
  // Literal values must appear in the steps; field names must appear in the steps or the act.
  const vals = slots.flatMap(assertionValues);
  const keys = slots.flatMap((a) =>
    a.category === 'state_change'
      ? objectKeys(a.args)
      : a.category === 'equality'
        ? objectKeys(a.expected)
        : [],
  );
  const keyOk = (k: string) => {
    const w = new RegExp(`(^|[^A-Za-z0-9_$])${k.replace(/[$]/g, '\\$')}([^A-Za-z0-9_$]|$)`, 'i');
    return w.test(text) || w.test(plan.act ?? '');
  };
  const total = vals.length + keys.length;
  const ok = vals.filter((v) => grounded(v, text)).length + keys.filter(keyOk).length;
  const ground = total ? ok / total : 1;
  return Math.round((0.5 * agree + 0.5 * ground) * 1000) / 1000;
}

// ---------------------------------------------------------------- Jest result classification

const ASSERTION = /^\s*(Error: )?expect\(|JestAssertionError|\bexpect\((received|value|function)\)/;

/** Why a Jest test failed: an expect() failure, an error from the code under test, or from the test itself. */
export function classifyFailure(messages: string[], testFile: string, repoPath: string): RunStatus {
  const msg = messages.join('\n');
  if (ASSERTION.test(msg)) return 'assertion_failed';
  const frames = msg
    .split('\n')
    .filter((l) => /^\s+at /.test(l))
    .map((l) => l.replace(/\\/g, '/'))
    .filter((l) => !/node_modules|node:internal|<anonymous>/.test(l));
  const first = frames[0] ?? '';
  if (first.includes(`/${repoPath}/`)) return 'subject_error';
  if (
    first.includes(testFile.replace(/\\/g, '/')) ||
    /ReferenceError|Cannot find module|is not a function|is not a constructor/.test(msg)
  )
    return 'test_error';
  return 'subject_error';
}

const short = (s: string) =>
  s
    .split('\n')
    .filter((l) => l.trim() && !/^\s+at /.test(l))
    .slice(0, 6)
    .join('\n')
    .slice(0, 600);

export interface VerifyInputs {
  inputs: C3Inputs;
  plans: ScenarioPlan[];
  written: WrittenFiles;
  exports: ReadonlyMap<string, ScannedExport[]>;
  /** Folder of the subject, or undefined when there is none (no referential check, no Jest run). */
  subjectRoot?: string;
  /** Result of running the written tests with Jest, if it ran. */
  jest?: JestRunResult;
}

/** The 4 checks + run status for every runnable test. */
export function verifyTests(v: VerifyInputs): VerificationWorkFile {
  const scOf = new Map(v.inputs.scenarios.map((s) => [s.scenarioId, s]));
  const planOf = new Map(v.plans.map((p) => [p.scenario_id, p]));
  const byName = new Map((v.jest?.tests ?? []).map((t) => [t.fullName, t]));
  const suiteErr = new Map((v.jest?.suiteErrors ?? []).map((e) => [e.file, e.message]));
  const out: TestVerification[] = [];

  for (const t of v.written.manifest.tests) {
    const problems: string[] = [];
    const sc = scOf.get(t.scenario_id);
    const plan = planOf.get(t.scenario_id);
    const code = v.written.files.get(t.file) ?? '';
    const req = v.written.requires.get(t.file);

    // syntactic
    const syn = syntaxError(code);
    if (syn) problems.push(`syntax: ${syn}`);
    const suite = suiteErr.get(t.file);
    if (suite) problems.push(`Jest could not load ${t.file}: ${short(suite)}`);
    const syntactic: CheckStatus = syn || suite ? 'fail' : 'pass';

    // referential
    let referential: CheckStatus = 'skipped';
    if (v.subjectRoot && req && sc) {
      const p = referentialProblems(req, v.exports.get(sc.subject.modulePath) ?? [], v.subjectRoot);
      problems.push(...p.map((x) => `referential: ${x}`));
      referential = p.length ? 'fail' : 'pass';
    }

    // traceability
    const trace = traceProblems(t, sc, v.jest ? byName.has(t.jest_full_name) : undefined);
    problems.push(...trace.map((x) => `traceability: ${x}`));
    const traceability: CheckStatus = trace.length ? 'fail' : 'pass';

    // semantic
    const score = sc && plan ? semanticScore(sc, plan, t.examples_row) : 0;
    const semantic = { status: (score >= SEMANTIC_PASS ? 'pass' : 'fail') as CheckStatus, score };

    // run
    let run: RunStatus = 'not_run';
    let message: string | undefined;
    if (v.jest) {
      const r = byName.get(t.jest_full_name);
      if (suite) {
        run = 'suite_error';
        message = short(suite);
      } else if (r?.status === 'passed') run = 'passed';
      else if (r?.status === 'failed') {
        run = classifyFailure(r.failureMessages, t.file, req?.repoPath ?? 'subject-src');
        message = short(r.failureMessages.join('\n'));
      } else {
        run = 'test_error';
        message = r ? `Jest status ${r.status}` : 'Jest did not report this test';
      }
    }
    out.push({
      test_id: t.test_id,
      scenario_id: t.scenario_id,
      syntactic,
      referential,
      traceability,
      semantic,
      run,
      ...(message ? { message } : {}),
      problems,
    });
  }
  return { version: VERIFY_VERSION, subject_run: !!v.jest, tests: out };
}

function traceProblems(
  t: ManifestTest,
  sc: C3ScenarioInput | undefined,
  jestHasName?: boolean,
): string[] {
  const p: string[] = [];
  if (!sc) p.push(`${t.scenario_id} is not a scenario C3 received`);
  if (!t.test_id.startsWith(`TST-${t.scenario_id.slice(4)}-`))
    p.push(`${t.test_id} does not embed ${t.scenario_id}`);
  if (!t.jest_full_name.startsWith(`[${t.requirement_id}] `))
    p.push('Jest name does not start with [REQ]');
  if (!t.jest_full_name.includes(`[${t.scenario_id}][${t.test_id}] `))
    p.push('Jest name has no [SCN][TST]');
  if (sc && sc.requirementId !== t.requirement_id) p.push('requirement differs from the scenario');
  if (sc && !sc.metadata.verification.fully_verified) p.push('scenario not fully verified by C2');
  if (jestHasName === false) p.push('Jest did not report this exact name');
  return p;
}

/** Copy the 4 results into the manifest tests (contract field `verification`). */
export function applyVerification(tests: ManifestTest[], v: VerificationWorkFile): ManifestTest[] {
  const byId = new Map(v.tests.map((x) => [x.test_id, x]));
  return tests.map((t) => {
    const x = byId.get(t.test_id);
    if (!x) return t;
    return {
      ...t,
      verification: {
        syntactic: x.syntactic,
        referential: x.referential,
        traceability: x.traceability,
        semantic: { status: x.semantic.status, score: x.semantic.score },
      },
    };
  });
}

/** A test is broken (C3-12 repairs it) when it fails for a reason inside the test, not the subject. */
export function isBroken(t: TestVerification): boolean {
  return (
    t.syntactic === 'fail' ||
    t.referential === 'fail' ||
    t.traceability === 'fail' ||
    t.run === 'test_error' ||
    t.run === 'suite_error'
  );
}
