// C3-14 pilot: run the SAME generated tests on the buggy and the fixed subject version.
//   bug detected = fails on buggy, passes on fixed
//   false alarm  = fails on fixed (the fixed code is taken as correct)
//   no signal    = passes on both (the test does not reach the bug)
// Tests are generated once, on the buggy version (as in real use: the fix is not known yet).
import fs from 'node:fs';
import path from 'node:path';
import { makeSandbox, removeSandbox, runJest, type JestRunResult } from './runner/jest.js';

export interface PilotOptions {
  run: string; // run folder with c3/ written by `c3 run`
  buggy: string; // subject root, buggy version
  fixed: string; // subject root, fixed version
  label?: string; // e.g. "Express-5"
}

export type Outcome = 'bug_detected' | 'false_alarm' | 'no_signal' | 'not_run';

export interface PilotTestRow {
  test_id: string;
  scenario_id: string;
  buggy: string; // Jest status, or "missing"
  fixed: string;
  outcome: Outcome;
  buggy_message?: string;
  fixed_message?: string;
}

export interface PilotSummary {
  label: string;
  run_id: string;
  scenarios: number;
  runnable_scenarios: number;
  stub_scenarios: number;
  runnable_percent: number;
  tests_generated: number;
  bugs_detected_tests: number;
  bugs_detected_scenarios: number;
  false_alarm_tests: number;
  false_alarm_rate: number; // false alarms / tests generated
  no_signal_tests: number;
}

export interface PilotResult {
  summary: PilotSummary;
  tests: PilotTestRow[];
  stubs: { scenario_id: string; reason: string }[];
}

interface ManifestTest {
  test_id: string;
  scenario_id: string;
  jest_full_name: string;
}

const readJson = <T>(f: string): T => JSON.parse(fs.readFileSync(f, 'utf8')) as T;

/** Where the generated tests expect the subject: source.repo_path (default subject-src). */
function repoPathOf(runDir: string): string {
  const f = path.join(runDir, 'subject-manifest.json');
  if (!fs.existsSync(f)) return 'subject-src';
  const m = readJson<{ subjects: { source: { repo_path?: string } }[] }>(f);
  return m.subjects[0]?.source.repo_path ?? 'subject-src';
}

function runOn(runDir: string, subjectRoot: string): JestRunResult {
  if (!fs.existsSync(subjectRoot)) throw new Error(`subject root ${subjectRoot} does not exist`);
  const dir = makeSandbox({ runDir, subjectRoot, repoPath: repoPathOf(runDir) });
  try {
    return runJest(dir, { timeoutMs: 300_000 });
  } finally {
    removeSandbox(dir);
  }
}

export function outcomeOf(buggy: string, fixed: string): Outcome {
  if (buggy === 'missing' || fixed === 'missing') return 'not_run';
  if (fixed !== 'passed') return 'false_alarm';
  return buggy === 'passed' ? 'no_signal' : 'bug_detected';
}

const pct = (a: number, b: number) => (b === 0 ? 0 : Math.round((1000 * a) / b) / 10);

/** Join the two Jest runs with the manifest and the confidence report. Pure, so it is unit-tested. */
export function comparePilot(
  runDir: string,
  buggy: JestRunResult,
  fixed: JestRunResult,
  label: string,
): PilotResult {
  const manifest = readJson<{ run_id: string; tests: ManifestTest[] }>(
    path.join(runDir, 'c3', 'test_manifest.json'),
  );
  const report = readJson<{
    scenarios: { scenario_id: string; route: string; reason: string }[];
  }>(path.join(runDir, 'c3', 'generation_confidence_report.json'));

  const byName = (r: JestRunResult) => new Map(r.tests.map((t) => [t.fullName, t]));
  const b = byName(buggy);
  const f = byName(fixed);
  const firstLine = (m?: string[]) =>
    m?.[0]
      ?.split('\n')
      .find((l) => l.trim())
      ?.trim();

  const tests: PilotTestRow[] = manifest.tests.map((t) => {
    const bt = b.get(t.jest_full_name);
    const ft = f.get(t.jest_full_name);
    const row: PilotTestRow = {
      test_id: t.test_id,
      scenario_id: t.scenario_id,
      buggy: bt?.status ?? 'missing',
      fixed: ft?.status ?? 'missing',
      outcome: outcomeOf(bt?.status ?? 'missing', ft?.status ?? 'missing'),
    };
    const bm = firstLine(bt?.failureMessages);
    const fm = firstLine(ft?.failureMessages);
    if (bm) row.buggy_message = bm;
    if (fm) row.fixed_message = fm;
    return row;
  });

  const stubs = report.scenarios
    .filter((s) => s.route !== 'runnable')
    .map((s) => ({ scenario_id: s.scenario_id, reason: s.reason }));
  const runnable = report.scenarios.length - stubs.length;
  const count = (o: Outcome) => tests.filter((t) => t.outcome === o).length;
  const bugScenarios = new Set(
    tests.filter((t) => t.outcome === 'bug_detected').map((t) => t.scenario_id),
  );

  return {
    summary: {
      label,
      run_id: manifest.run_id,
      scenarios: report.scenarios.length,
      runnable_scenarios: runnable,
      stub_scenarios: stubs.length,
      runnable_percent: pct(runnable, report.scenarios.length),
      tests_generated: tests.length,
      bugs_detected_tests: count('bug_detected'),
      bugs_detected_scenarios: bugScenarios.size,
      false_alarm_tests: count('false_alarm'),
      false_alarm_rate: pct(count('false_alarm'), tests.length),
      no_signal_tests: count('no_signal'),
    },
    tests,
    stubs,
  };
}

/** Markdown for the results table (PP1 evidence). */
export function pilotMarkdown(r: PilotResult): string {
  const s = r.summary;
  const lines = [
    `# C3-14 pilot: ${s.label} (${s.run_id})`,
    '',
    'Tests were generated once (on the buggy version) and the same files were run on both versions.',
    '',
    '| Metric | Value |',
    '|---|---|',
    `| Scenarios from C2 | ${s.scenarios} |`,
    `| Routed runnable / stub | ${s.runnable_scenarios} / ${s.stub_scenarios} |`,
    `| Runnable % (scenarios) | ${s.runnable_percent}% |`,
    `| Tests generated | ${s.tests_generated} |`,
    `| Bug detected (fail on buggy, pass on fixed) | ${s.bugs_detected_tests} test(s) in ${s.bugs_detected_scenarios} scenario(s) |`,
    `| False alarms (fail on fixed) | ${s.false_alarm_tests} (${s.false_alarm_rate}%) |`,
    `| Pass on both (no signal for this bug) | ${s.no_signal_tests} |`,
    '',
    '| Test | Buggy | Fixed | Outcome |',
    '|---|---|---|---|',
    ...r.tests.map((t) => `| ${t.test_id} | ${t.buggy} | ${t.fixed} | ${t.outcome} |`),
  ];
  if (r.stubs.length) {
    lines.push('', '| Stub scenario | Reason |', '|---|---|');
    for (const st of r.stubs)
      lines.push(`| ${st.scenario_id} | ${st.reason.replace(/\|/g, '/')} |`);
  }
  const notes = r.tests.filter((t) => t.outcome === 'false_alarm' || t.outcome === 'bug_detected');
  if (notes.length) {
    lines.push('', 'Failure messages:', '');
    for (const t of notes) {
      const m = t.outcome === 'false_alarm' ? t.fixed_message : t.buggy_message;
      lines.push(`- ${t.test_id} (${t.outcome}): ${m ?? '(no message)'}`);
    }
  }
  return lines.join('\n') + '\n';
}

/** `c3 pilot`: run both versions, write c3/work/pilot_results.json and .md, return the result. */
export function pilot(o: PilotOptions, log: (l: string) => void = console.log): PilotResult {
  const label = o.label ?? path.basename(o.run);
  log(`[c3] pilot (C3-14) ${label}: same tests on buggy and fixed`);
  const buggy = runOn(o.run, o.buggy);
  log(`  buggy: ${summaryLine(buggy)}`);
  const fixed = runOn(o.run, o.fixed);
  log(`  fixed: ${summaryLine(fixed)}`);
  const result = comparePilot(o.run, buggy, fixed, label);
  const work = path.join(o.run, 'c3', 'work');
  fs.mkdirSync(work, { recursive: true });
  fs.writeFileSync(path.join(work, 'pilot_results.json'), JSON.stringify(result, null, 2) + '\n');
  const md = pilotMarkdown(result);
  fs.writeFileSync(path.join(work, 'pilot_results.md'), md);
  log(md);
  log(`[c3] pilot results written to ${path.join(work, 'pilot_results.md')}`);
  return result;
}

function summaryLine(r: JestRunResult): string {
  if (!r.ok) return `Jest did not run: ${r.stderr.split('\n')[0] ?? ''}`;
  const passed = r.tests.filter((t) => t.status === 'passed').length;
  const extra = r.suiteErrors.length ? `, ${r.suiteErrors.length} file(s) could not run` : '';
  return `${passed} passed, ${r.tests.length - passed} failed${extra}`;
}
