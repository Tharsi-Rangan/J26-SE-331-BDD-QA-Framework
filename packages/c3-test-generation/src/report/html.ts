// C3-16 HTML report: one page per run that shows what every C3 step did, in simple words, for a demo or a
// review. Plus one batch page that lists many runs (e.g. the BugsJS bugs) with a link to each run page.
//   - read-only: it only reads the files `c3 run` / `c3 pilot` wrote (see load.ts)
//   - one self-contained file: inline CSS + a few lines of JS, no internet, works from file://
//   - every text from the run is HTML-escaped
//   - "open in VS Code" links: vscode://file/<absolute path>:<line> (feature file, subject source,
//     generated tests, output JSON, and the C3 source file where each rule / formula is written)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { AssertionSlot, ScenarioPlan } from '../assert/plan.js';
import type { C3ScenarioInput } from '../input/types.js';
import type { MockDecision } from '../mock/decisions.js';
import type { PilotTestRow } from '../pilot.js';
import type { ReportScenario } from '../route/confidence.js';
import type { ScannedExport } from '../scan/types.js';
import { semanticParts } from '../verify/verify.js';
import { isC3Run, loadRun, type RunData } from './load.js';

export const REPORT_FILE = 'c3/c3_report.html';
export const BATCH_REPORT_FILE = 'c3_batch_report.html';

// ---------------------------------------------------------------- small helpers

export function esc(v: unknown): string {
  return String(v ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * vscode://file/<absolute path>[:line]. Works for Windows paths (C:\a\b -> vscode://file/C:/a/b) and
 * POSIX paths (/home/a -> vscode://file/home/a). Spaces and '#' are percent-encoded.
 */
export function vscodeUrl(absPath: string, line?: number): string {
  let p = absPath.replace(/\\/g, '/');
  if (!p.startsWith('/')) p = '/' + p;
  const enc = encodeURI(p).replace(/#/g, '%23').replace(/\?/g, '%3F');
  return `vscode://file${enc}${line && line > 0 ? `:${line}` : ''}`;
}

/** A link that opens the file in VS Code, or plain text when the path is unknown. */
function vs(absPath: string | undefined, text: string, line?: number, cls = 'vs'): string {
  if (!absPath) return `<span class="mono">${esc(text)}</span>`;
  const where = absPath + (line ? `:${line}` : '');
  return `<a class="${cls}" href="${esc(vscodeUrl(absPath, line))}" title="Open in VS Code: ${esc(where)}">${esc(text)}</a>`;
}

const joinAbs = (root: string, rel: string) =>
  /^[A-Za-z]:[\\/]|^\\\\/.test(root)
    ? `${root.replace(/[\\/]+$/, '')}\\${rel.replace(/\//g, '\\')}`
    : path.join(root, rel);

const pct = (n: number) => `${Math.round(n * 100)}%`;
const num = (n: number | undefined) => (n === undefined ? '-' : Number(n.toFixed(3)).toString());
const short = (ref?: string) => (ref ? ref.slice(0, 7) : '?');

// ---------------------------------------------------------------- where C3's own rules are written

const PKG_ROOT = fileURLToPath(new URL('../../', import.meta.url));
const srcCache = new Map<string, string | null>();

/** Line (1-based) of the first match of `re` in a C3 source file, or undefined. */
function lineIn(rel: string, re: RegExp): number | undefined {
  const file = path.join(PKG_ROOT, rel);
  if (!srcCache.has(file))
    srcCache.set(file, fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null);
  const text = srcCache.get(file);
  if (!text) return undefined;
  const m = re.exec(text);
  return m ? text.slice(0, m.index).split('\n').length : undefined;
}

/** Link to a C3 source file at the line where `re` matches (e.g. a rule or the weights). */
function c3src(rel: string, re: RegExp, text?: string): string {
  const file = path.join(PKG_ROOT, rel);
  if (!fs.existsSync(file)) return `<span class="mono">${esc(text ?? rel)}</span>`;
  const line = lineIn(rel, re);
  return vs(file, text ?? `${rel}${line ? `:${line}` : ''}`, line, 'vs code');
}

const SRC = {
  reader: () => c3src('src/input/reader.ts', /export function readC3Inputs/),
  scanner: () => c3src('src/scan/scanner.ts', /export function scanModule/),
  sideEffects: () => c3src('src/scan/side-effects.ts', /export/),
  rules: () => c3src('src/mock/rules.ts', /export const RULES\b/),
  rule: (id: string) => c3src('src/mock/rules.ts', new RegExp(`id: '${id}'`), id),
  behaviourPrompt: () => c3src('src/mock/behaviour.ts', /export function behaviourPrompt/),
  behaviourCheck: () => c3src('src/mock/behaviour.ts', /export function checkAnswer/),
  assertPrompt: () => c3src('src/assert/plan.ts', /export function assertionPrompt/),
  assertCheck: () => c3src('src/assert/plan.ts', /export function checkAssertionAnswer/),
  categoryRules: () => c3src('src/assert/plan.ts', /^const RULES\b/m),
  templates: () => c3src('src/assert/templates.ts', /export function renderCase/),
  strategy: () => c3src('src/strategy.ts', /export function chooseStrategy/),
  strategyRule: (id: string) => c3src('src/strategy.ts', new RegExp(`rule_id: '${id}'`), id),
  writer: () => c3src('src/writer/jest-writer.ts', /export function writeJestTests/),
  verify: () => c3src('src/verify/verify.ts', /export function verifyTests/),
  semantic: () => c3src('src/verify/verify.ts', /export function semanticParts/),
  repair: () => c3src('src/verify/repair.ts', /export const MAX_REPAIR_ROUNDS/),
  weights: () => c3src('src/route/confidence.ts', /export const WEIGHTS/),
  threshold: () => c3src('src/route/confidence.ts', /export const THRESHOLD/),
  route: () => c3src('src/route/confidence.ts', /export function routeScenarios/),
  pilot: () => c3src('src/pilot.ts', /export function outcomeOf/),
};

// ---------------------------------------------------------------- outcome / route badges

type Outcome = PilotTestRow['outcome'];
const OUTCOME_TEXT: Record<Outcome, string> = {
  bug_detected: 'Bug detected',
  false_alarm: 'False alarm',
  no_signal: 'No signal',
  not_run: 'Not run',
};
const badge = (cls: string, text: string, title?: string) =>
  `<span class="badge ${cls}"${title ? ` title="${esc(title)}"` : ''}>${esc(text)}</span>`;
const outcomeBadge = (o: Outcome) => badge(`o-${o}`, OUTCOME_TEXT[o]);
const routeBadge = (r: string) =>
  r === 'runnable'
    ? badge('r-run', 'Runnable test')
    : r === 'stub'
      ? badge('r-stub', 'Stub for a human')
      : badge('r-skip', 'Skipped');
const checkBadge = (s: string | undefined) =>
  !s
    ? badge('c-na', '-')
    : s === 'pass' || s === 'passed'
      ? badge('c-pass', s)
      : s === 'skipped' || s === 'not_run'
        ? badge('c-na', s)
        : badge('c-fail', s);

// ---------------------------------------------------------------- the run page

interface Ctx {
  d: RunData;
  subjectRoot?: string; // buggy (the version the tests were generated on)
  fixedRoot?: string;
  testsOf: (sid: string) => NonNullable<RunData['manifest']>['tests'];
  pilotOf: Map<string, PilotTestRow>;
}

export function renderRunReport(d: RunData, opts: { generatedAt?: string } = {}): string {
  const scan = d.scans[0]?.scan;
  const ctx: Ctx = {
    d,
    subjectRoot: d.pilot?.roots?.buggy ?? scan?.subjectRoot,
    fixedRoot: d.pilot?.roots?.fixed,
    testsOf: (sid) => (d.manifest?.tests ?? []).filter((t) => t.scenario_id === sid),
    pilotOf: new Map((d.pilot?.tests ?? []).map((t) => [t.test_id, t])),
  };
  const subject = d.subjects[0];
  const title = `C3 report: ${d.label}`;
  const scenarios = orderScenarios(d, ctx);
  const body = [
    header(d, ctx),
    cards(d),
    pipelineStrip(),
    `<section id="steps"><h2>What each C3 step did in this run</h2>${stepTable(d, ctx)}</section>`,
    `<section id="scenarios"><div class="sechead"><h2>Scenarios (${scenarios.length})</h2>
      <span class="tools"><button type="button" data-all="open">Expand all</button><button type="button" data-all="close">Collapse all</button></span></div>
      <p class="hint">Order: bug detected first, then false alarms, then stubs, then the rest. Click a scenario to open it.</p>
      ${scenarios.map((sc, i) => scenarioSection(sc, ctx, i === 0)).join('\n')}
    </section>`,
    footer(d, opts.generatedAt),
  ].join('\n');
  return page(title, body, subject ? `${subject.module_path}` : '');
}

function header(d: RunData, ctx: Ctx): string {
  const s = d.subjects[0];
  const src = s?.source;
  const bug =
    src?.kind === 'bugsjs'
      ? `BugsJS <b>${esc(src.bug_id)}</b> &middot; buggy <span class="mono">${esc(short(src.buggy_ref))}</span> &middot; fixed <span class="mono">${esc(short(src.fixed_ref))}</span>`
      : esc(src?.kind ?? 'subject');
  const mod = s?.module_path ?? d.scans[0]?.modulePath;
  const modLinks = mod
    ? [
        ctx.subjectRoot
          ? vs(joinAbs(ctx.subjectRoot, mod), `${mod} (buggy)`)
          : `<span class="mono">${esc(mod)}</span>`,
        ctx.fixedRoot ? vs(joinAbs(ctx.fixedRoot, mod), 'fixed') : '',
      ]
        .filter(Boolean)
        .join(' &middot; ')
    : '-';
  const model = d.plans?.model ?? d.manifest?.producer.model ?? 'no model (rule defaults only)';
  const reqs = d.features
    .map(
      (
        f,
      ) => `<div class="req"><div class="reqhead"><span class="pill">${esc(f.requirement_id)}</span> <b>${esc(f.feature_name ?? '')}</b>
        &nbsp;${vs(path.join(d.runDir, f.feature_file), f.feature_file)}</div>
        ${f.requirement_text_used ? `<p class="reqtext">${esc(f.requirement_text_used)}</p>` : ''}</div>`,
    )
    .join('');
  return `<header class="top">
    <div class="eyebrow">C3 &middot; Runnable test generation with explainable assertions and mocking</div>
    <h1>${esc(d.label)}</h1>
    <div class="meta">
      <div><span class="k">Code under test</span><span class="v">${bug}</span></div>
      <div><span class="k">Module</span><span class="v">${modLinks}</span></div>
      <div><span class="k">Model</span><span class="v mono">${esc(model)}</span></div>
      <div><span class="k">Versions</span><span class="v">assertion prompt ${esc(d.plans?.prompt_version ?? '-')} &middot; behaviour prompt ${esc(d.behaviour?.prompt_version ?? '-')} &middot; mock rules ${esc(d.mock?.rules_version ?? '-')} &middot; strategy rules ${esc(d.strategy?.rules_version ?? '-')} &middot; formula ${esc(d.confidence?.formula.version ?? '-')}</span></div>
      <div><span class="k">Run</span><span class="v"><span class="mono">${esc(d.manifest?.run_id ?? d.inputs?.runId ?? '')}</span> &middot; ${vs(d.runDir, 'run folder')}</span></div>
    </div>
    ${reqs ? `<div class="reqs"><div class="k">Requirement${d.features.length > 1 ? 's' : ''} (input from C2)</div>${reqs}</div>` : ''}
    ${s?.notes ? `<p class="note">${esc(s.notes)}</p>` : ''}
  </header>`;
}

function cards(d: RunData): string {
  const sc = d.confidence?.scenarios ?? [];
  const runnable = sc.filter((s) => s.route === 'runnable').length;
  const stubs = sc.filter((s) => s.route === 'stub').length;
  const p = d.pilot?.summary;
  const card = (n: string | number, label: string, cls = '', sub = '') =>
    `<div class="card ${cls}"><div class="n">${esc(n)}</div><div class="l">${esc(label)}</div>${sub ? `<div class="s">${esc(sub)}</div>` : ''}</div>`;
  return `<section class="cards">
    ${card(sc.length, 'Scenarios', '', 'from C2')}
    ${card(runnable, 'Runnable', 'good', 'confidence ≥ threshold')}
    ${card(stubs, 'Stubs', stubs ? 'warn' : '', 'left for a human')}
    ${card(d.manifest?.tests.length ?? 0, 'Jest tests', '', 'one per Examples row')}
    ${p ? card(p.bugs_detected_tests, 'Bug detected', p.bugs_detected_tests ? 'good strong' : '', 'fail buggy, pass fixed') : card('-', 'Bug detected', 'muted', 'run c3 pilot')}
    ${p ? card(p.false_alarm_tests, 'False alarms', p.false_alarm_tests ? 'bad strong' : 'good', 'fail on fixed') : card('-', 'False alarms', 'muted', 'run c3 pilot')}
    ${p ? card(p.no_signal_tests, 'No signal', 'muted', 'pass on both') : ''}
  </section>`;
}

const STEPS: [string, string, string][] = [
  ['C3-03', 'Read', 'read'],
  ['C3-04', 'Scan', 'scan'],
  ['C3-05', 'Mock rules', 'mock'],
  ['C3-07', 'Mock behaviour', 'behaviour'],
  ['C3-08', 'Assertions', 'assert'],
  ['C3-09', 'Strategy', 'strategy'],
  ['C3-10', 'Jest writer', 'writer'],
  ['C3-11', 'Verify', 'verify'],
  ['C3-12', 'Repair', 'repair'],
  ['C3-13', 'Confidence', 'confidence'],
  ['C3-14', 'Pilot', 'pilot'],
];

function pipelineStrip(): string {
  return `<nav class="pipe" aria-label="C3 pipeline">${STEPS.map(
    ([id, name, a], i) =>
      `<a href="#step-${a}"><span class="sid">${id}</span><span class="sn">${esc(name)}</span></a>${i < STEPS.length - 1 ? '<span class="arrow">→</span>' : ''}`,
  ).join('')}</nav>`;
}

function stepTable(d: RunData, ctx: Ctx): string {
  const out = (rel: string) => vs(path.join(d.runDir, rel), rel);
  const decisions = d.mock?.decisions ?? [];
  const byRule = new Map<string, number>();
  for (const x of decisions) byRule.set(x.rule_id, (byRule.get(x.rule_id) ?? 0) + 1);
  const mocks = decisions.filter((x) => x.decision === 'mock').length;
  const records = d.behaviour?.records ?? [];
  const plans = d.plans?.plans ?? [];
  const modelPlans = plans.filter((p) => p.source === 'model').length;
  const meanAgree = plans.length
    ? plans.reduce((a, p) => a + (p.category_agreement ?? 0), 0) / plans.length
    : 0;
  const strat = d.strategy?.choices ?? [];
  const tests = d.manifest?.tests ?? [];
  const testFiles = [...new Set(tests.map((t) => t.file))];
  const v = d.verification?.tests ?? [];
  const allPass = v.filter(
    (t) =>
      t.syntactic === 'pass' &&
      t.referential === 'pass' &&
      t.traceability === 'pass' &&
      t.semantic.status === 'pass',
  ).length;
  const runs = new Map<string, number>();
  for (const t of v) runs.set(t.run, (runs.get(t.run) ?? 0) + 1);
  const rep = d.repair?.entries ?? [];
  const repaired = new Set(rep.filter((e) => e.fixed).map((e) => e.scenario_id));
  const conf = d.confidence;
  const routed = conf?.scenarios ?? [];
  const scan = d.scans[0]?.scan;
  const p = d.pilot;

  const row = (
    a: string,
    id: string,
    name: string,
    what: string,
    result: string,
    files: string,
    code: string,
  ) =>
    `<tr id="step-${a}"><td class="sid">${id}</td><td><b>${esc(name)}</b><div class="what">${what}</div></td><td>${result}</td><td class="files">${files}</td><td class="files">${code}</td></tr>`;

  const rows = [
    row(
      'read',
      'C3-03',
      'Read inputs',
      'Read the C2 scenarios (.feature + metadata) and the subject manifest. Only scenarios C2 fully verified get tests.',
      d.inputs
        ? `<b>${d.inputs.scenarios.length}</b> scenario(s) to build, ${d.inputs.skipped.length} skipped`
        : `<span class="bad">${esc(d.inputsError ?? 'not read')}</span>`,
      `${out('c2/scenario_metadata.json')}<br>${out('subject-manifest.json')}`,
      SRC.reader(),
    ),
    row(
      'scan',
      'C3-04',
      'Dependency scan',
      'ts-morph reads the module: its exports, every import and every call to a dependency, with line numbers.',
      scan
        ? `<b>${scan.exports.length}</b> export(s), <b>${scan.imports.length}</b> import(s), <b>${scan.dependencies.length}</b> dependency use(s)<div class="sub">${scan.exports.map((e) => exportLink(e, ctx, d)).join(' ')}</div>`
        : 'not written',
      out('c3/work/dependency_scan.json'),
      `${SRC.scanner()}<br>${SRC.sideEffects()}`,
    ),
    row(
      'mock',
      'C3-05',
      'Mock decisions (rules)',
      'Rules R-01..R-08 decide mock / no_mock for each dependency, with a reason. No model here.',
      d.mock
        ? `<b>${mocks}</b> mock, <b>${decisions.length - mocks}</b> no_mock<div class="sub">${[
            ...byRule,
          ]
            .sort()
            .map(([r, n]) => `${SRC.rule(r)}&nbsp;×${n}`)
            .join(' &nbsp; ')}</div>`
        : 'not written',
      out('c3/mock_decisions.json'),
      SRC.rules(),
    ),
    row(
      'behaviour',
      'C3-07',
      'Mock behaviour (model)',
      'For each mocked dependency the model says what it returns or throws, citing a Given/When step. Code checks the answer.',
      mocks
        ? `<b>${records.filter((r) => r.source === 'model').length}</b> from a checked model answer, ${records.filter((r) => r.source !== 'model').length} rule default`
        : 'No dependency was mocked, so no behaviour was needed.',
      out('c3/work/mock_behaviour.json'),
      `${SRC.behaviourPrompt()}<br>${SRC.behaviourCheck()}`,
    ),
    row(
      'assert',
      'C3-08',
      'Typed assertions (model)',
      'The model fills typed slots (category, actual, expected); code checks 12 rules and refuses invented values. Fixed templates write the expect() lines.',
      plans.length
        ? `<b>${modelPlans}</b> of ${plans.length} plan(s) accepted, ${plans.length - modelPlans} refused<div class="sub">mean category agreement ${pct(meanAgree)}</div>`
        : 'not written',
      out('c3/work/assertion_plan.json'),
      `${SRC.assertPrompt()}<br>${SRC.assertCheck()}<br>${SRC.templates()}`,
    ),
    row(
      'strategy',
      'C3-09',
      'Test strategy (rules)',
      'S-01: a Scenario Outline becomes test.each (one row per Examples row). S-02: any other scenario becomes one test.',
      strat.length
        ? `${strat.filter((c) => c.rule_id === 'S-01').length} × S-01 parametrised, ${strat.filter((c) => c.rule_id === 'S-02').length} × S-02 factory`
        : 'not written',
      out('c3/work/strategy.json'),
      SRC.strategy(),
    ),
    row(
      'writer',
      'C3-10',
      'Jest writer',
      'Writes the Jest files and test_manifest.json. Every test name carries the requirement, scenario and test id.',
      `<b>${tests.length}</b> test(s) in ${testFiles.length} file(s), ${d.manifest?.stubs.length ?? 0} stub(s)<div class="sub">${testFiles.map((f) => out(f)).join('<br>')}</div>`,
      out('c3/test_manifest.json'),
      SRC.writer(),
    ),
    row(
      'verify',
      'C3-11',
      '4-layer verification',
      'Syntactic, referential, traceability and semantic checks, then a real Jest run on the subject. Semantic = 0.5 × category agreement + 0.5 × grounding (pass ≥ 0.5).',
      v.length
        ? `<b>${allPass}</b> of ${v.length} test(s) pass all 4 checks<div class="sub">Jest run: ${[...runs].map(([k, n]) => `${esc(k)} ×${n}`).join(', ')}</div>`
        : 'not written',
      out('c3/work/verification.json'),
      `${SRC.verify()}<br>${SRC.semantic()}`,
    ),
    row(
      'repair',
      'C3-12',
      'Repair loop',
      `A broken test goes back to the model with the error, at most ${d.repair?.max_rounds ?? 3} rounds.`,
      rep.length
        ? `${rep.length} round(s): ${repaired.size} scenario(s) fixed`
        : 'No repair needed.',
      out('c3/work/repair_log.json'),
      SRC.repair(),
    ),
    row(
      'confidence',
      'C3-13',
      'Confidence and routing',
      `Confidence = Σ signal × weight (not the model's own confidence). ≥ ${conf?.formula.threshold ?? 0.8} → runnable test, else a stub for a human. Calibrated: ${conf?.formula.calibrated ? 'yes' : 'not yet'}.`,
      conf
        ? `<b>${routed.filter((s) => s.route === 'runnable').length}</b> runnable, <b>${routed.filter((s) => s.route === 'stub').length}</b> stub`
        : 'not written',
      out('c3/generation_confidence_report.json'),
      `${SRC.weights()}<br>${SRC.threshold()}`,
    ),
    row(
      'pilot',
      'C3-14',
      'Pilot: buggy vs fixed',
      'The same generated tests run on the buggy and on the fixed version. Fail buggy + pass fixed = bug detected. Fail fixed = false alarm.',
      p
        ? `<b>${p.summary.bugs_detected_tests}</b> bug detected, <b>${p.summary.false_alarm_tests}</b> false alarm(s), ${p.summary.no_signal_tests} no signal${p.roots ? `<div class="sub">${vs(p.roots.buggy, 'buggy folder')} &middot; ${vs(p.roots.fixed, 'fixed folder')}</div>` : ''}`
        : 'Not run yet: <span class="mono">c3 pilot --run … --buggy … --fixed …</span>',
      p ? out('c3/work/pilot_results.json') : '-',
      SRC.pilot(),
    ),
  ];
  return `<div class="tablewrap"><table class="steps"><thead><tr><th>Step</th><th>What it does</th><th>Result in this run</th><th>Output file</th><th>Rules / code</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
}

function exportLink(e: ScannedExport, ctx: Ctx, d: RunData): string {
  const mod = d.scans[0]?.modulePath;
  const text = `${e.name}(${(e.params ?? []).join(', ')})`;
  return ctx.subjectRoot && mod
    ? vs(joinAbs(ctx.subjectRoot, mod), text, e.line, 'vs chip')
    : `<span class="mono chip">${esc(text)}</span>`;
}

// ---------------------------------------------------------------- one scenario

function orderScenarios(d: RunData, ctx: Ctx): C3ScenarioInput[] {
  const list = d.inputs?.scenarios ?? [];
  const rank = (sc: C3ScenarioInput) => {
    const outs = ctx.testsOf(sc.scenarioId).map((t) => ctx.pilotOf.get(t.test_id)?.outcome);
    if (outs.includes('bug_detected')) return 0;
    if (outs.includes('false_alarm')) return 1;
    const r = d.confidence?.scenarios.find((s) => s.scenario_id === sc.scenarioId);
    if (r?.route === 'stub') return 2;
    return 3;
  };
  return list
    .map((sc, i) => ({ sc, i, r: rank(sc) }))
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .map((x) => x.sc);
}

function scenarioSection(sc: C3ScenarioInput, ctx: Ctx, open: boolean): string {
  const d = ctx.d;
  const conf = d.confidence?.scenarios.find((s) => s.scenario_id === sc.scenarioId);
  const plan = d.plans?.plans.find((p) => p.scenario_id === sc.scenarioId);
  const tests = ctx.testsOf(sc.scenarioId);
  const outs = tests
    .map((t) => ctx.pilotOf.get(t.test_id)?.outcome)
    .filter((o): o is Outcome => !!o);
  const count = (o: Outcome) => outs.filter((x) => x === o).length;
  const outcomeBadges = (['bug_detected', 'false_alarm', 'no_signal'] as Outcome[])
    .filter((o) => count(o))
    .map((o) =>
      badge(
        `o-${o}`,
        `${OUTCOME_TEXT[o]}${count(o) > 1 || tests.length > 1 ? ` ×${count(o)}` : ''}`,
      ),
    )
    .join(' ');
  const summary = `<summary>
      <span class="scid mono">${esc(sc.scenarioId)}</span>
      <span class="scname">${esc(sc.scenarioName)}</span>
      <span class="badges">${badge('t-type', sc.scenarioType)} ${conf ? routeBadge(conf.route) : ''} ${outcomeBadges}
      ${conf ? `<span class="confnum" title="confidence (C3-13)">conf ${esc(conf.confidence.toFixed(2))}</span>` : ''}</span>
    </summary>`;
  const parts = [
    block(
      'C3-03',
      'Scenario from C2',
      `${vs(path.join(d.runDir, sc.featureFile), `${sc.featureFile}:${sc.line}`, sc.line)}`,
      gherkin(sc, ctx),
    ),
    block('C3-04', 'Code under test', '', codeUnderTest(sc, plan, ctx)),
    block(
      'C3-05 + C3-07',
      'Dependencies and mock decisions',
      `${SRC.rules()} ${SRC.behaviourCheck()}`,
      mockTable(sc, ctx),
    ),
    block('C3-08', 'Typed assertions', `${SRC.assertCheck()}`, assertionBlock(sc, plan)),
    block('C3-09', 'Test strategy', SRC.strategy(), strategyBlock(sc, d)),
    block(
      'C3-10',
      conf?.route === 'stub' ? 'Stub file (for a human)' : 'Generated Jest code',
      '',
      codeBlock(sc, ctx, conf),
    ),
    block('C3-11', 'Verification', SRC.semantic(), verifyBlock(sc, plan, ctx)),
    block('C3-12', 'Repair', SRC.repair(), repairBlock(sc, d)),
    block('C3-13', 'Confidence and route', `${SRC.weights()}`, confidenceBlock(conf, d)),
    block('C3-14', 'Pilot: buggy vs fixed', SRC.pilot(), pilotBlock(sc, ctx)),
  ];
  return `<details class="scenario" id="${esc(sc.scenarioId)}"${open ? ' open' : ''}>${summary}<div class="scbody">${parts.join('')}</div></details>`;
}

const block = (id: string, title: string, links: string, inner: string) =>
  `<div class="blk"><div class="blkhead"><span class="sid">${esc(id)}</span><h3>${esc(title)}</h3><span class="links">${links}</span></div>${inner}</div>`;

function gherkin(sc: C3ScenarioInput, ctx: Ctx): string {
  const feature = path.join(ctx.d.runDir, sc.featureFile);
  // highlight <column> only for real Examples columns (a step may hold HTML such as <p>)
  const cols = new Set(sc.examples.flatMap((r) => Object.keys(r.values)));
  const steps = sc.steps
    .map((s) => {
      const text = esc(s.text).replace(/&lt;([^&<>]+)&gt;/g, (m, c: string) =>
        cols.has(c) ? `<span class="ph">${m}</span>` : m,
      );
      return `<div class="step k-${s.keyword}"><a class="ln" href="${esc(vscodeUrl(feature, s.line))}" title="Open line ${s.line}">${s.line}</a><span class="kw">${s.keyword}</span> ${text}</div>`;
    })
    .join('');
  let examples = '';
  if (sc.isOutline && sc.examples.length) {
    const cols = Object.keys(sc.examples[0]!.values);
    const tests = ctx.testsOf(sc.scenarioId);
    const head = `<tr><th>#</th>${cols.map((c) => `<th>${esc(c)}</th>`).join('')}<th>Test</th>${ctx.d.pilot ? '<th>Pilot</th>' : ''}</tr>`;
    const rows = sc.examples
      .map((r) => {
        const t = tests.find((x) => x.examples_row === r.rowIndex);
        const p = t ? ctx.pilotOf.get(t.test_id) : undefined;
        return `<tr><td>${r.rowIndex}</td>${cols.map((c) => `<td class="mono">${esc(r.values[c])}</td>`).join('')}<td class="mono small">${esc(t?.test_id ?? '-')}</td>${ctx.d.pilot ? `<td>${p ? outcomeBadge(p.outcome) : '-'}</td>` : ''}</tr>`;
      })
      .join('');
    examples = `<div class="exlabel">Examples (C3 uses C2's values unchanged)</div><div class="tablewrap"><table class="ex">${head}${rows}</table></div>`;
  }
  return `<div class="gherkin"><div class="scline"><span class="kw">${sc.isOutline ? 'Scenario Outline' : 'Scenario'}:</span> ${esc(sc.scenarioName)} <span class="muted">(${esc(sc.scenarioType)}, ${esc(sc.requirementId)})</span></div>${steps}</div>${examples}`;
}

function codeUnderTest(sc: C3ScenarioInput, plan: ScenarioPlan | undefined, ctx: Ctx): string {
  const s = ctx.d.scans.find((x) => x.modulePath === sc.subject.modulePath)?.scan;
  const names = plan?.function_under_test?.length ? plan.function_under_test : sc.subject.exports;
  const rows = names.map((n) => {
    const e = s?.exports.find((x) => x.name === n);
    const buggy = ctx.subjectRoot ? joinAbs(ctx.subjectRoot, sc.subject.modulePath) : undefined;
    const fixed = ctx.fixedRoot ? joinAbs(ctx.fixedRoot, sc.subject.modulePath) : undefined;
    const fixedLine = fixed ? findLine(fixed, n) : undefined;
    const deps = e?.dependencies.length
      ? e.dependencies.map((k) => `<span class="mono chip">${esc(k)}</span>`).join(' ')
      : '<span class="muted">none</span>';
    return `<div class="fut">
      <div><span class="mono big">${esc(n)}(${esc((e?.params ?? []).join(', '))})</span> ${e?.isAsync ? badge('t-type', 'async') : ''}
        &nbsp; ${vs(buggy, `buggy: ${sc.subject.modulePath}${e ? `:${e.line}` : ''}`, e?.line)} ${fixed ? `&middot; ${vs(fixed, `fixed${fixedLine ? `:${fixedLine}` : ''}`, fixedLine)}` : ''}</div>
      ${e?.doc ? `<div class="doc">${esc(e.doc).replace(/ \| /g, '<br>')}</div>` : ''}
      <div class="small">Dependencies it reaches: ${deps}</div>
    </div>`;
  });
  return rows.join('') || '<p class="muted">Not found in the scan.</p>';
}

/** First line that defines or exports `name` in a file (for the fixed version, which C3 did not scan). */
function findLine(file: string, name: string): number | undefined {
  try {
    const lines = fs.readFileSync(file, 'utf8').split('\n');
    const n = name.replace(/[$]/g, '\\$');
    const res = [
      new RegExp(`function\\s+${n}\\b`),
      new RegExp(`\\b${n}\\s*[:=]\\s*(async\\s+)?(function|\\(|[A-Za-z_$][\\w$]*\\s*=>)`),
      new RegExp(`\\b${n}\\b`),
    ];
    for (const re of res) {
      const i = lines.findIndex((l) => re.test(l));
      if (i >= 0) return i + 1;
    }
  } catch {
    /* fixed file not there */
  }
  return undefined;
}

function mockTable(sc: C3ScenarioInput, ctx: Ctx): string {
  const ds = (ctx.d.mock?.decisions ?? []).filter((x) => x.scenario_id === sc.scenarioId);
  if (!ds.length)
    return '<p class="muted">The function under test reaches no dependency, so there is nothing to mock.</p>';
  const recs = ctx.d.behaviour?.records ?? [];
  const scan = ctx.d.scans.find((x) => x.modulePath === sc.subject.modulePath)?.scan;
  const rows = ds.map((x: MockDecision) => {
    const dep = `${x.dependency.import_specifier}#${x.dependency.symbol}`;
    const used = scan?.dependencies.find((u) => u.key === dep);
    const where =
      used?.lines.length && ctx.subjectRoot
        ? used.lines
            .slice(0, 4)
            .map((l) => vs(joinAbs(ctx.subjectRoot!, sc.subject.modulePath), `L${l}`, l))
            .join(' ')
        : '';
    const rec = recs.find((r) => r.decision_id === x.decision_id);
    const beh = x.behaviour
      ? `<div class="beh"><b>Behaviour:</b> ${esc(x.behaviour.summary)}<div class="small">Why: ${esc(x.behaviour.rationale)}</div>
         <div class="small">From steps: ${x.behaviour.derived_from_steps.map((s) => `<span class="mono chip">${esc(s)}</span>`).join(' ') || '-'}
         &middot; ${rec ? (rec.source === 'model' ? `checked model answer (${rec.attempts} attempt${rec.attempts === 1 ? '' : 's'})` : 'rule default (no model)') : ''}</div>
         ${rec?.problems.length ? `<div class="small bad">Rejected answers: ${rec.problems.map(esc).join(' | ')}</div>` : ''}
         ${rec?.warnings.length ? `<div class="small warnc">Review: ${rec.warnings.map(esc).join(' | ')}</div>` : ''}</div>`
      : '';
    return `<tr><td class="mono small nw">${esc(x.decision_id)}</td>
      <td><span class="mono">${esc(dep)}</span><div class="small muted">${esc(x.dependency.kind)} &middot; side effect: ${esc(x.dependency.side_effect)}${x.dependency.type_signature ? ` &middot; <span class="mono">${esc(x.dependency.type_signature)}</span>` : ''}</div>${where ? `<div class="small">used at ${where}</div>` : ''}</td>
      <td>${x.decision === 'mock' ? badge('d-mock', 'mock') : badge('d-real', 'no_mock')}<div class="small">${SRC.rule(x.rule_id)}</div></td>
      <td>${esc(x.reason)}${beh}</td></tr>`;
  });
  return `<div class="tablewrap"><table class="mk"><thead><tr><th>ID</th><th>Dependency</th><th>Decision</th><th>Reason</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
}

function slotText(a: AssertionSlot): string {
  const j = (v: unknown) => JSON.stringify(v);
  switch (a.category) {
    case 'equality':
      return `${a.actual ?? 'result'} equals ${j(a.expected)}`;
    case 'range':
      return `${a.actual ?? 'result'} in ${a.min_inclusive === false ? '(' : '['}${j(a.min)}, ${j(a.max)}${a.max_inclusive === false ? ')' : ']'}`;
    case 'exception':
      return `throws ${a.error ?? 'an error'}${a.message ? ` with message containing ${j(a.message)}` : ''}`;
    case 'state_change':
      return `${a.target ?? '?'} ${a.change ?? ''}${a.args ? ` ${j(a.args)}` : ''}${a.times !== undefined ? ` ×${a.times}` : ''}`;
    default:
      return j(a);
  }
}

function assertionBlock(sc: C3ScenarioInput, plan: ScenarioPlan | undefined): string {
  if (!plan) return '<p class="muted">No plan written.</p>';
  const thens = sc.steps.filter((s) => s.keyword === 'Then');
  const thenText = (id: string) => thens[Number(id.slice(1)) - 1]?.text ?? '';
  const status =
    plan.source === 'model'
      ? `<p>${badge('c-pass', 'accepted')} Model answer accepted after <b>${plan.attempts}</b> attempt${plan.attempts === 1 ? '' : 's'}.</p>`
      : `<p>${badge('c-fail', 'refused')} No usable answer after <b>${plan.attempts}</b> attempt${plan.attempts === 1 ? '' : 's'}, so this scenario gets no runnable test (it becomes a stub).</p>`;
  const problems = plan.problems.length
    ? `<div class="problems"><b>${plan.source === 'model' ? 'Earlier answers were rejected because:' : 'Why the answers were refused:'}</b><ul>${plan.problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul></div>`
    : '';
  if (plan.source !== 'model') return status + problems;
  const act = plan.act_code
    ? `<div class="kv"><span class="k">Act (call)</span><pre class="code one">${esc((plan.await ? 'await ' : '') + plan.act_code)}</pre></div>`
    : '';
  const slots = plan.assertions
    .map(
      (
        a,
      ) => `<tr><td class="mono">${esc(a.then)}</td><td class="small">${esc(thenText(a.then))}</td><td>${badge('cat', a.category)}</td>
      <td class="mono small">${esc(slotText(a))}${a.when ? `<div class="muted">only rows where ${esc(a.when.column)} = ${esc(a.when.equals)}</div>` : ''}</td></tr>`,
    )
    .join('');
  const ruleCats = [...new Set(plan.rule_categories.map((r) => `${r.then}:${r.category}`))]
    .map((k) => `<span class="mono chip">${esc(k)}</span>`)
    .join(' ');
  return `${status}${problems}${act}
    <div class="tablewrap"><table class="as"><thead><tr><th>Then</th><th>Then step</th><th>Category</th><th>Assertion (typed slots)</th></tr></thead><tbody>${slots}</tbody></table></div>
    <p class="small">Rule-based category guess from the Then words: ${ruleCats || '-'} &middot; agreement with the model: <b>${pct(plan.category_agreement)}</b> ${SRC.categoryRules()}</p>`;
}

function strategyBlock(sc: C3ScenarioInput, d: RunData): string {
  const c = d.strategy?.choices.find((x) => x.scenario_id === sc.scenarioId);
  if (!c) return '<p class="muted">Not written.</p>';
  return `<p>${badge('t-type', c.strategy)} rule ${SRC.strategyRule(c.rule_id)}: ${esc(c.reason)}</p>`;
}

/** The part of a generated Jest file that belongs to one scenario (blank-line separated blocks). */
export function scenarioCode(
  text: string,
  scenarioId: string,
): { code: string; line: number } | undefined {
  const lines = text.split('\n');
  const blocks: { start: number; end: number }[] = [];
  let start = -1;
  lines.forEach((l, i) => {
    if (l.trim() === '') {
      if (start >= 0) blocks.push({ start, end: i - 1 });
      start = -1;
    } else if (start < 0) start = i;
  });
  if (start >= 0) blocks.push({ start, end: lines.length - 1 });
  const hit = blocks.filter((b) =>
    lines.slice(b.start, b.end + 1).some((l) => l.includes(`[${scenarioId}]`)),
  );
  if (!hit.length) return undefined;
  const indent = (l: string) => l.length - l.trimStart().length;
  let first = 0;
  const parts = hit.map((b, i) => {
    let part = lines.slice(b.start, b.end + 1);
    // a block can also hold the "describe(...) {" line above the test or the closing "});" of describe:
    // keep only the lines at the test's own indent or deeper
    const base = indent(part.find((l) => l.includes(`[${scenarioId}]`))!);
    let drop = 0;
    while (drop < part.length - 1 && indent(part[drop]!) < base) drop++;
    part = part.slice(drop);
    while (part.length > 1 && indent(part.at(-1)!) < base) part.pop();
    if (i === 0) first = b.start + drop;
    return part.map((l) => l.slice(Math.min(base, indent(l)))).join('\n');
  });
  return { code: parts.join('\n\n'), line: first + 1 };
}

function codeBlock(sc: C3ScenarioInput, ctx: Ctx, conf: ReportScenario | undefined): string {
  const d = ctx.d;
  if (conf?.route === 'stub') {
    const stub = d.manifest?.stubs.find((s) => s.scenario_id === sc.scenarioId);
    const text = stub ? d.files.get(stub.file) : undefined;
    return stub
      ? `<p>${vs(path.join(d.runDir, stub.file), stub.file)} &middot; <span class="muted">test.todo: it never fails CI; a human writes or fixes this test.</span></p><pre class="code">${esc(text ?? '')}</pre>`
      : '<p class="muted">No stub file.</p>';
  }
  const files = [...new Set(ctx.testsOf(sc.scenarioId).map((t) => t.file))];
  if (!files.length) return '<p class="muted">No runnable test for this scenario.</p>';
  return files
    .map((f) => {
      const text = d.files.get(f) ?? '';
      const part = scenarioCode(text, sc.scenarioId);
      const head = text
        .split('\n')
        .filter((l) => /^(const|import|jest\.mock|let|var)\b|require\(/.test(l))
        .slice(0, 8)
        .join('\n');
      return `<p>${vs(path.join(d.runDir, f), `${f}${part ? `:${part.line}` : ''}`, part?.line)}</p>
        ${head ? `<pre class="code dim">${esc(head)}</pre>` : ''}<pre class="code">${esc(part?.code ?? text)}</pre>`;
    })
    .join('');
}

function verifyBlock(sc: C3ScenarioInput, plan: ScenarioPlan | undefined, ctx: Ctx): string {
  const v = (ctx.d.verification?.tests ?? []).filter((t) => t.scenario_id === sc.scenarioId);
  if (!v.length)
    return '<p class="muted">No test was verified for this scenario (no runnable test).</p>';
  const tests = ctx.testsOf(sc.scenarioId);
  const rows = v
    .map((t) => {
      const row = tests.find((x) => x.test_id === t.test_id)?.examples_row;
      let parts = '';
      if (plan && plan.source === 'model') {
        try {
          const sp = semanticParts(sc, plan, row);
          parts = `<div class="small muted">0.5 × ${num(sp.agree)} + 0.5 × ${num(sp.ground)}</div>`;
        } catch {
          parts = '';
        }
      }
      return `<tr><td class="mono small nw">${esc(t.test_id)}</td><td>${row ?? '-'}</td><td>${checkBadge(t.syntactic)}</td><td>${checkBadge(t.referential)}</td><td>${checkBadge(t.traceability)}</td>
        <td class="nw">${checkBadge(t.semantic.status)} <b>${esc(num(t.semantic.score))}</b>${parts}</td><td>${checkBadge(t.run)}</td>
        <td class="small">${t.problems.length ? t.problems.map(esc).join('<br>') : '<span class="muted">none</span>'}${t.message ? `<div class="mono small muted">Jest: ${esc(t.message)}</div>` : ''}</td></tr>`;
    })
    .join('');
  return `<p class="small">Semantic = 0.5 × category agreement + 0.5 × grounding (share of the assertion's values that appear in the steps). Pass ≥ 0.5.</p>
    <div class="tablewrap"><table class="vf"><thead><tr><th>Test</th><th>Row</th><th>Syntactic</th><th>Referential</th><th>Traceability</th><th>Semantic</th><th>Jest run (generation version)</th><th>Problems / Jest message</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function repairBlock(sc: C3ScenarioInput, d: RunData): string {
  const e = (d.repair?.entries ?? []).filter((x) => x.scenario_id === sc.scenarioId);
  if (!e.length) {
    const plan = d.plans?.plans.find((p) => p.scenario_id === sc.scenarioId);
    return plan && plan.source !== 'model'
      ? '<p class="muted">No repair round: the assertion plan was refused, so there was no test to repair.</p>'
      : '<p class="muted">No repair needed: every test of this scenario was fine the first time.</p>';
  }
  return `<div class="tablewrap"><table><thead><tr><th>Round</th><th>Errors sent back to the model</th><th>Answer</th><th>Fixed</th></tr></thead><tbody>${e
    .map(
      (x) =>
        `<tr><td>${x.round}</td><td class="small">${x.errors.map(esc).join('<br>')}</td><td>${esc(x.answer)}</td><td>${x.fixed ? badge('c-pass', 'yes') : badge('c-fail', 'no')}</td></tr>`,
    )
    .join('')}</tbody></table></div>`;
}

const SIGNAL_TEXT: Record<string, string> = {
  all_deterministic_checks_pass: 'Syntactic, referential and traceability checks pass',
  semantic_score: 'Semantic score (mean of its tests)',
  runs_clean: 'Jest ran every test without a broken-test error',
  no_repair_needed: 'No repair needed',
  c2_fully_verified: 'C2 fully verified the scenario',
  mock_behaviour_from_model: 'Every mock behaviour is a checked model answer (or no mocks)',
};

function confidenceBlock(conf: ReportScenario | undefined, d: RunData): string {
  if (!conf || !d.confidence) return '<p class="muted">Not written.</p>';
  const w = d.confidence.formula.weights;
  const th = d.confidence.formula.threshold;
  let sum = 0;
  const rows = Object.entries(w)
    .map(([k, weight]) => {
      const raw = (conf.signals as Record<string, number | boolean>)[k];
      const value = typeof raw === 'boolean' ? (raw ? 1 : 0) : Number(raw ?? 0);
      const pts = value * weight;
      sum += pts;
      const shown = typeof raw === 'boolean' ? (raw ? 'yes (1)' : 'no (0)') : num(value);
      return `<tr class="${value < (typeof raw === 'boolean' ? 1 : 0.5) ? 'weak' : ''}"><td>${esc(SIGNAL_TEXT[k] ?? k)}<div class="mono small muted">${esc(k)}</div></td><td>${esc(shown)}</td><td>× ${weight}</td><td><b>${num(pts)}</b></td></tr>`;
    })
    .join('');
  sum = Math.round(sum * 1000) / 1000;
  const capped =
    Math.abs(sum - conf.confidence) > 0.0005
      ? `<p class="small warnc">The sum is ${num(sum)}, but there is no runnable test for this scenario, so the confidence is held just below the threshold (${num(conf.confidence)}).</p>`
      : '';
  const ok = conf.confidence >= th;
  return `<div class="tablewrap"><table class="cf"><thead><tr><th>Signal</th><th>Value</th><th>Weight</th><th>Points</th></tr></thead><tbody>${rows}
    <tr class="total"><td>Confidence</td><td></td><td></td><td><b>${num(conf.confidence)}</b></td></tr></tbody></table></div>${capped}
    <div class="verdict ${ok ? 'good' : 'warnbox'}"><b>${num(conf.confidence)} ${ok ? '≥' : '<'} ${th}</b> → ${routeBadge(conf.route)} <span>${esc(conf.reason)}</span></div>`;
}

function pilotBlock(sc: C3ScenarioInput, ctx: Ctx): string {
  if (!ctx.d.pilot) return '<p class="muted">Pilot not run yet for this run.</p>';
  const tests = ctx.testsOf(sc.scenarioId);
  if (!tests.length)
    return '<p class="muted">No runnable test, so nothing ran in the pilot (the stub is for a human).</p>';
  const rows = tests
    .map((t) => {
      const p = ctx.pilotOf.get(t.test_id);
      const msg =
        p?.outcome === 'false_alarm'
          ? p.fixed_message
          : p?.outcome === 'bug_detected'
            ? p.buggy_message
            : undefined;
      return `<tr class="row-${p?.outcome ?? 'not_run'}"><td class="mono small nw">${esc(t.test_id)}</td><td>${t.examples_row ?? '-'}</td><td>${checkBadge(p?.buggy)}</td><td>${checkBadge(p?.fixed)}</td><td>${p ? outcomeBadge(p.outcome) : '-'}</td><td class="mono small">${esc(msg ?? '')}</td></tr>`;
    })
    .join('');
  return `<div class="tablewrap"><table class="pl"><thead><tr><th>Test</th><th>Row</th><th>Buggy version</th><th>Fixed version</th><th>Outcome</th><th>Failure message</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function footer(d: RunData, generatedAt?: string): string {
  return `<footer>
    <p><b>How to read the pilot:</b> ${outcomeBadge('bug_detected')} fails on the buggy version and passes on the fixed one &middot;
      ${outcomeBadge('false_alarm')} fails on the fixed version (the fixed code is taken as correct) &middot;
      ${outcomeBadge('no_signal')} passes on both (the test does not reach this bug).</p>
    <p class="muted">This page only reads the files that <span class="mono">c3 run</span> and <span class="mono">c3 pilot</span> wrote in ${vs(d.runDir, d.folder)}.
      Blue links open the file in VS Code at the right line. Made by C3 (C3-16)${generatedAt ? ` on ${esc(generatedAt)}` : ''}.</p>
  </footer>`;
}

// ---------------------------------------------------------------- the batch page

export interface BatchRow {
  data: RunData;
  reportHref: string; // relative link from the batch page to the run page
}

export function renderBatchReport(
  rows: BatchRow[],
  opts: { generatedAt?: string; title?: string } = {},
): string {
  const sum = (f: (r: RunData) => number | undefined) =>
    rows.reduce((a, r) => a + (f(r.data) ?? 0), 0);
  const routes = (r: RunData, k: string) =>
    (r.confidence?.scenarios ?? []).filter((s) => s.route === k).length;
  const t = {
    scenarios: sum((r) => r.confidence?.scenarios.length),
    runnable: sum((r) => routes(r, 'runnable')),
    stubs: sum((r) => routes(r, 'stub')),
    tests: sum((r) => r.manifest?.tests.length),
    bug: sum((r) => r.pilot?.summary.bugs_detected_tests),
    fa: sum((r) => r.pilot?.summary.false_alarm_tests),
    ns: sum((r) => r.pilot?.summary.no_signal_tests),
  };
  const bugsjs = rows.filter((r) => r.data.subjects[0]?.source?.kind === 'bugsjs').length;
  const title =
    opts.title ??
    (bugsjs === rows.length && rows.length
      ? `C3 on ${rows.length} BugsJS bugs`
      : `C3 batch report (${rows.length} runs)`);
  const card = (n: number, label: string, cls = '', sub = '') =>
    `<div class="card ${cls}"><div class="n">${n}</div><div class="l">${esc(label)}</div>${sub ? `<div class="s">${esc(sub)}</div>` : ''}</div>`;
  const body = rows
    .map((r) => {
      const d = r.data;
      const s = d.subjects[0];
      const scan = d.scans[0]?.scan;
      const root = d.pilot?.roots?.buggy ?? scan?.subjectRoot;
      const mod = s?.module_path ?? scan?.modulePath ?? '';
      const p = d.pilot?.summary;
      const cell = (n: number | undefined, cls: string) =>
        `<td class="num ${n ? cls : 'zero'}">${n ?? '-'}</td>`;
      const fut = [...new Set((d.plans?.plans ?? []).flatMap((x) => x.function_under_test))];
      return `<tr>
        <td><a class="runlink" href="${esc(r.reportHref)}">${esc(d.label)}</a><div class="small muted">${esc(s?.source?.bug_id ?? d.folder)}</div></td>
        <td>${root && mod ? vs(joinAbs(root, mod), mod) : `<span class="mono">${esc(mod)}</span>`}<div class="small mono muted">${esc((fut.length ? fut : (s?.exports ?? [])).join(', '))}</div></td>
        <td class="num">${d.confidence?.scenarios.length ?? '-'}</td>
        <td class="num">${routes(d, 'runnable')} / ${routes(d, 'stub')}</td>
        <td class="num">${d.manifest?.tests.length ?? '-'}</td>
        ${cell(p?.bugs_detected_tests, 'good')}${cell(p?.false_alarm_tests, 'bad')}${cell(p?.no_signal_tests, '')}
        <td><a class="open" href="${esc(r.reportHref)}">Open report →</a></td></tr>`;
    })
    .join('');
  const html = `<header class="top"><div class="eyebrow">C3 &middot; Runnable test generation with explainable assertions and mocking</div>
    <h1>${esc(title)}</h1>
    <p class="lead">For each bug, C3 read hand-written Gherkin requirements, generated Jest tests on the <b>buggy</b> version, and then ran the <b>same</b> tests on the buggy and the fixed version.</p></header>
    <section class="cards">
      ${card(rows.length, 'Bugs / runs')}
      ${card(t.scenarios, 'Scenarios')}
      ${card(t.runnable, 'Runnable', 'good', `${t.scenarios ? Math.round((100 * t.runnable) / t.scenarios) : 0}% of scenarios`)}
      ${card(t.stubs, 'Stubs', t.stubs ? 'warn' : '', 'left for a human')}
      ${card(t.tests, 'Jest tests')}
      ${card(t.bug, 'Bug detected', t.bug ? 'good strong' : '', 'fail buggy, pass fixed')}
      ${card(t.fa, 'False alarms', t.fa ? 'bad strong' : 'good', 'fail on fixed')}
      ${card(t.ns, 'No signal', 'muted', 'pass on both')}
    </section>
    <section><div class="tablewrap"><table class="batch"><thead><tr><th>Bug</th><th>Module (opens buggy file)</th><th class="num">Scenarios</th><th class="num">Runnable / stub</th><th class="num">Tests</th><th class="num">Bug detected</th><th class="num">False alarms</th><th class="num">No signal</th><th></th></tr></thead>
    <tbody>${body}</tbody>
    <tfoot><tr><td><b>Total</b></td><td></td><td class="num">${t.scenarios}</td><td class="num">${t.runnable} / ${t.stubs}</td><td class="num">${t.tests}</td><td class="num">${t.bug}</td><td class="num">${t.fa}</td><td class="num">${t.ns}</td><td></td></tr></tfoot></table></div></section>
    <footer><p><b>How to read:</b> ${outcomeBadge('bug_detected')} the test fails on the buggy version and passes on the fixed one &middot;
      ${outcomeBadge('false_alarm')} the test fails on the fixed version &middot; ${outcomeBadge('no_signal')} the test passes on both.
      A <b>stub</b> is a scenario whose confidence was below the threshold: C3 writes a test.todo for a human instead of a test it does not trust.</p>
      <p class="muted">Each run page shows every C3 step for that bug. Made by C3 (C3-16)${opts.generatedAt ? ` on ${esc(opts.generatedAt)}` : ''}.</p></footer>`;
  return page(title, html, 'batch');
}

// ---------------------------------------------------------------- write files

export function writeRunReport(runDir: string, opts: { generatedAt?: string } = {}): string {
  const data = loadRun(runDir);
  const file = path.join(data.runDir, REPORT_FILE);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(
    file,
    renderRunReport(data, { generatedAt: opts.generatedAt ?? new Date().toISOString() }),
  );
  return file;
}

/**
 * Batch page in <dir>/c3_batch_report.html. `runs` = folder names inside <dir> (in this order);
 * default: every folder in <dir> with a finished c3 run. Every run page is written again first.
 */
export function writeBatchReport(
  dir: string,
  opts: { runs?: string[]; generatedAt?: string; title?: string } = {},
): { file: string; runs: string[]; missing: string[] } {
  const root = path.resolve(dir);
  const names =
    opts.runs ??
    fs
      .readdirSync(root, { withFileTypes: true })
      .filter((e) => e.isDirectory() && isC3Run(path.join(root, e.name)))
      .map((e) => e.name)
      .sort();
  const generatedAt = opts.generatedAt ?? new Date().toISOString();
  const missing: string[] = [];
  const rows: BatchRow[] = [];
  for (const n of names) {
    const runDir = path.join(root, n);
    if (!isC3Run(runDir)) {
      missing.push(n);
      continue;
    }
    writeRunReport(runDir, { generatedAt });
    rows.push({ data: loadRun(runDir), reportHref: `${encodeURI(n)}/${REPORT_FILE}` });
  }
  const file = path.join(root, BATCH_REPORT_FILE);
  fs.writeFileSync(file, renderBatchReport(rows, { generatedAt, title: opts.title }));
  return { file, runs: rows.map((r) => r.data.folder), missing };
}

// ---------------------------------------------------------------- page shell (CSS + JS)

function page(title: string, body: string, sub: string): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<meta name="description" content="${esc(sub)}">
<style>${CSS}</style>
</head>
<body>
<main>
${body}
</main>
<script>${JS}</script>
</body>
</html>
`;
}

const CSS = `
:root{--bg:#f6f7f9;--panel:#fff;--ink:#14181f;--muted:#5b6472;--line:#dfe3e8;--accent:#1f5fbf;--accent-soft:#e8f0fc;
--good:#137a3a;--good-soft:#e3f4e9;--bad:#b42318;--bad-soft:#fdecea;--warn:#a15c00;--warn-soft:#fff3dc;--grey-soft:#eef0f3;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
*{box-sizing:border-box}
html{font-size:17px}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.45}
main{max-width:1280px;margin:0 auto;padding:24px 20px 60px}
h1{font-size:2rem;margin:4px 0 14px;letter-spacing:-.01em}
h2{font-size:1.35rem;margin:0 0 12px}
h3{font-size:1.02rem;margin:0}
a{color:var(--accent)}
.mono{font-family:var(--mono);font-size:.92em}
.small{font-size:.85rem}
.muted{color:var(--muted)}
.bad{color:var(--bad)} .warnc{color:var(--warn)}
section{margin:22px 0}
.top{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px 22px}
.eyebrow{color:var(--muted);font-size:.85rem;text-transform:uppercase;letter-spacing:.06em}
.lead{font-size:1.05rem;max-width:70ch;margin:0}
.meta{display:grid;gap:6px}
.meta>div{display:grid;grid-template-columns:150px 1fr;gap:10px}
.k{color:var(--muted);font-size:.85rem;text-transform:uppercase;letter-spacing:.04em;padding-top:2px}
.reqs{margin-top:14px;border-top:1px solid var(--line);padding-top:12px}
.req{margin-top:6px}
.reqtext{margin:6px 0 0;padding:10px 14px;background:var(--accent-soft);border-left:4px solid var(--accent);border-radius:6px;font-size:1.02rem}
.note{color:var(--muted);font-size:.85rem;margin:12px 0 0}
.pill{display:inline-block;background:var(--grey-soft);border-radius:999px;padding:1px 10px;font-family:var(--mono);font-size:.85rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .n{font-size:2.1rem;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums}
.card .l{font-weight:600;margin-top:2px}
.card .s{color:var(--muted);font-size:.8rem}
.card.good .n{color:var(--good)} .card.bad .n{color:var(--bad)} .card.warn .n{color:var(--warn)} .card.muted .n{color:var(--muted)}
.card.good.strong{background:var(--good-soft);border-color:#b6dfc4} .card.bad.strong{background:var(--bad-soft);border-color:#f3c0ba}
.pipe{display:flex;flex-wrap:wrap;align-items:center;gap:4px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.pipe a{display:flex;flex-direction:column;text-decoration:none;color:var(--ink);padding:6px 10px;border-radius:8px;border:1px solid var(--line);background:#fbfcfd}
.pipe a:hover{background:var(--accent-soft);border-color:var(--accent)}
.pipe .sid{font-family:var(--mono);font-size:.75rem;color:var(--accent)} .pipe .sn{font-weight:600;font-size:.9rem}
.arrow{color:var(--muted)}
.tablewrap{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-size:.8rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);background:#fafbfc}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.num.good{color:var(--good);font-weight:700} td.num.bad{color:var(--bad);font-weight:700} td.num.zero{color:var(--muted)}
tfoot td{font-weight:700;background:#fafbfc;border-top:2px solid var(--line)}
table.steps td.sid{font-family:var(--mono);color:var(--accent);white-space:nowrap}
table.steps .what{color:var(--muted);font-size:.86rem;max-width:42ch}
table.steps .sub{margin-top:4px;font-size:.85rem}
table.steps td.files{font-size:.85rem;white-space:nowrap}
table.steps tr:target{background:var(--accent-soft)}
a.vs{font-family:var(--mono);font-size:.88em;text-decoration:none;border-bottom:1px dashed var(--accent)}
a.vs:hover{background:var(--accent-soft)}
a.vs.code{color:#6b3fb5;border-color:#6b3fb5}
.nw{white-space:nowrap}
table.batch a.vs{white-space:nowrap}
.chip{display:inline-block;background:var(--grey-soft);border-radius:6px;padding:0 6px;margin:1px 0;border-bottom:none!important}
.badge{display:inline-block;border-radius:999px;padding:1px 10px;font-size:.8rem;font-weight:600;white-space:nowrap;border:1px solid transparent}
.o-bug_detected{background:var(--good-soft);color:var(--good);border-color:#b6dfc4}
.o-false_alarm{background:var(--bad-soft);color:var(--bad);border-color:#f3c0ba}
.o-no_signal,.o-not_run,.c-na,.r-skip{background:var(--grey-soft);color:var(--muted)}
.r-run,.c-pass{background:var(--good-soft);color:var(--good)}
.r-stub{background:var(--warn-soft);color:var(--warn)}
.c-fail{background:var(--bad-soft);color:var(--bad)}
.t-type,.cat{background:var(--accent-soft);color:var(--accent)}
.d-mock{background:#efe7fb;color:#6b3fb5} .d-real{background:var(--grey-soft);color:var(--ink)}
.sechead{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.tools button{font:inherit;font-size:.85rem;margin-left:6px;padding:5px 12px;border-radius:8px;border:1px solid var(--line);background:var(--panel);cursor:pointer}
.tools button:hover{border-color:var(--accent)}
.hint{color:var(--muted);font-size:.88rem;margin:4px 0 10px}
details.scenario{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin:10px 0;overflow:hidden}
details.scenario>summary{cursor:pointer;list-style:none;display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;padding:12px 16px}
details.scenario>summary::-webkit-details-marker{display:none}
details.scenario>summary::before{content:"▸";color:var(--muted);font-size:1rem}
details.scenario[open]>summary::before{content:"▾"}
details.scenario[open]>summary{border-bottom:1px solid var(--line);background:#fafbfc}
.scid{color:var(--accent)} .scname{font-weight:650;font-size:1.05rem}
.badges{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-left:auto}
.confnum{font-family:var(--mono);font-weight:700;padding:1px 8px;border:1px solid var(--line);border-radius:6px}
.scbody{padding:6px 16px 16px}
.blk{padding:12px 0;border-bottom:1px dashed var(--line)}
.blk:last-child{border-bottom:none}
.blkhead{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:8px}
.blkhead .sid{font-family:var(--mono);font-size:.78rem;color:#fff;background:var(--accent);border-radius:6px;padding:1px 7px}
.blkhead .links{margin-left:auto;font-size:.82rem;display:flex;gap:10px;flex-wrap:wrap}
.gherkin{font-family:var(--mono);font-size:.95rem;background:#fbfcfd;border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.gherkin .scline{margin-bottom:4px}
.step{padding:2px 0}
.step .ln{display:inline-block;width:2.6em;color:var(--muted);text-decoration:none;font-size:.8rem}
.step .ln:hover{color:var(--accent)}
.kw{font-weight:700}
.k-Given .kw{color:#1f5fbf} .k-When .kw{color:#a15c00} .k-Then .kw{color:#137a3a}
.ph{background:#fff3dc;border-radius:4px;padding:0 3px}
.exlabel{margin:10px 0 4px;font-size:.85rem;color:var(--muted)}
.fut{padding:6px 0}
.fut .big{font-size:1.02rem;font-weight:600}
.doc{margin:6px 0;padding:8px 12px;background:#fbfcfd;border-left:3px solid var(--line);font-size:.88rem;color:var(--muted)}
.beh{margin-top:8px;padding:8px 10px;background:#f7f2fd;border-radius:8px}
pre.code{font-family:var(--mono);font-size:.86rem;background:#0f1520;color:#e6edf3;border-radius:8px;padding:12px 14px;overflow-x:auto;margin:6px 0;line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere}
pre.code.dim{background:#1b2230;color:#9fb0c3}
pre.code.one{display:inline-block;margin:0;padding:6px 10px}
.kv{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0}
.problems{background:var(--bad-soft);border-radius:8px;padding:8px 12px;margin:8px 0}
.problems ul{margin:4px 0 0;padding-left:20px}
table.cf tr.weak td{background:var(--warn-soft)}
table.cf tr.total td{border-top:2px solid var(--line);background:#fafbfc}
.verdict{margin-top:10px;padding:10px 14px;border-radius:8px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.verdict.good{background:var(--good-soft)} .verdict.warnbox{background:var(--warn-soft)}
tr.row-bug_detected td{background:var(--good-soft)} tr.row-false_alarm td{background:var(--bad-soft)}
a.runlink{font-weight:700;font-size:1.05rem;text-decoration:none}
a.open{white-space:nowrap;text-decoration:none;font-weight:600}
footer{margin-top:28px;font-size:.92rem}
footer p{margin:6px 0}
@media (max-width:700px){html{font-size:15px}.meta>div{grid-template-columns:1fr}.badges{margin-left:0}}
@media print{body{background:#fff}details.scenario{break-inside:avoid}.tools,.pipe{display:none}}
`;

const JS = `
document.querySelectorAll('[data-all]').forEach(function (b) {
  b.addEventListener('click', function () {
    var open = b.getAttribute('data-all') === 'open';
    document.querySelectorAll('details.scenario').forEach(function (d) { d.open = open; });
  });
});
if (location.hash) { var t = document.getElementById(decodeURIComponent(location.hash.slice(1))); if (t && t.tagName === 'DETAILS') t.open = true; }
`;
