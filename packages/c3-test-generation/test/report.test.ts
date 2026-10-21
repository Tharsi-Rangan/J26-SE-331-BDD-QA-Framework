// C3-16 HTML report: read-only, self-contained, escaped, VS Code links, run page + batch page.
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, test } from 'vitest';
import { parsePilotArgs, parseReportArgs, parseRunArgs } from '../src/args.js';
import { run } from '../src/index.js';
import { FakeModelClient } from '../src/model/index.js';
import { pilot } from '../src/pilot.js';
import {
  BATCH_REPORT_FILE,
  esc,
  renderRunReport,
  REPORT_FILE,
  scenarioCode,
  vscodeUrl,
  writeBatchReport,
  writeRunReport,
} from '../src/report/html.js';
import { loadRun } from '../src/report/load.js';
import { openCommand } from '../src/report/open.js';

const GOLDEN = fileURLToPath(
  new URL('../../contracts/fixtures/golden/example-registration', import.meta.url),
);
const BUGGY = fileURLToPath(new URL('../fixtures/pilot/example-off-by-one', import.meta.url));
const FIXED_TIME = '2026-10-19T10:00:00+05:30';

// Same model answers as test/pilot.test.ts: one mocked repository, typed assertions for both scenarios.
const BEHAVIOUR = {
  steps: ['S1'],
  kind: 'returns_input',
  value: { id: 'u1' },
  error_message: null,
  summary: "save() returns the given user with id 'u1'.",
  rationale: 'S1 says the repository is available, so save succeeds.',
};
const A1 = {
  act: 'registerUser({ age: 30, email: "amal@example.com" })',
  assertions: [{ then: 'T1', category: 'equality', actual: 'result.age', expected: 30 }],
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
    if (u.includes('Mocked dependency:')) return JSON.stringify(BEHAVIOUR);
    return JSON.stringify(u.includes('Age at and around') ? A2 : A1);
  });

/** sha256 of every file under dir except the report files (to prove the report is read-only). */
function snapshot(dir: string): Map<string, string> {
  const out = new Map<string, string>();
  const walk = (d: string) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const f = path.join(d, e.name);
      if (e.isDirectory()) walk(f);
      else if (!f.endsWith('.html'))
        out.set(
          path.relative(dir, f),
          crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex'),
        );
    }
  };
  walk(dir);
  return out;
}

describe('C3-16 helpers', () => {
  test('vscode links: Windows and POSIX paths, spaces, line numbers', () => {
    expect(vscodeUrl('C:\\c3-subjects\\bugs\\eslint-22-buggy\\lib\\a.js', 64)).toBe(
      'vscode://file/C:/c3-subjects/bugs/eslint-22-buggy/lib/a.js:64',
    );
    expect(vscodeUrl('/home/me/My Runs/x#1.json')).toBe(
      'vscode://file/home/me/My%20Runs/x%231.json',
    );
    expect(vscodeUrl('/a/b.ts', 0)).toBe('vscode://file/a/b.ts');
  });

  test('escaping', () => {
    expect(esc(`<script>alert("x")</script>&'`)).toBe(
      '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;&amp;&#39;',
    );
    expect(esc(undefined)).toBe('');
  });

  test('scenarioCode: only the blocks of one scenario, without the closing describe', () => {
    const file = [
      'const { f } = require("x");',
      '',
      'describe("[REQ-A-001] A", () => {',
      '  test.each([',
      '    ["TST-A-001-01-01", "a=1", 1],',
      '  ])("[SCN-A-001-01][%s] one :: %s", (_id, _case, a) => {',
      '    expect(f(a)).toBe(1);',
      '  });',
      '',
      '  test("[SCN-A-001-02][TST-A-001-02-01] two", () => {',
      '    expect(f(2)).toBe(2);',
      '  });',
      '});',
      '',
    ].join('\n');
    expect(scenarioCode(file, 'SCN-A-001-01')).toEqual({
      code: [
        'test.each([',
        '  ["TST-A-001-01-01", "a=1", 1],',
        '])("[SCN-A-001-01][%s] one :: %s", (_id, _case, a) => {',
        '  expect(f(a)).toBe(1);',
        '});',
      ].join('\n'),
      line: 4,
    });
    const two = scenarioCode(file, 'SCN-A-001-02')!;
    expect(two.line).toBe(10);
    expect(two.code).not.toContain('});\n});');
    expect(two.code.split('\n').at(-1)).toBe('});');
    expect(scenarioCode(file, 'SCN-A-001-09')).toBeUndefined();
  });

  test('CLI options: c3 report, --open on run and pilot', () => {
    const base = path.resolve('repo-root');
    expect(parseReportArgs(['report', '--run', 'runs/R', '--open'], base)).toEqual({
      run: path.join(base, 'runs', 'R'),
      open: true,
    });
    expect(
      parseReportArgs(
        ['report', '--index', 'runs', '--runs', 'bugsjs-eslint-22, bugsjs-hexo-7'],
        base,
      ),
    ).toEqual({ index: path.join(base, 'runs'), runs: ['bugsjs-eslint-22', 'bugsjs-hexo-7'] });
    expect(() => parseReportArgs(['report'], base)).toThrow(/Usage: c3 report/);
    expect(() => parseReportArgs(['report', '--run', 'a', '--index', 'b'], base)).toThrow(/Usage/);
    expect(parseRunArgs(['run', '--out', 'o', '--open'], base).open).toBe(true);
    expect(parseRunArgs(['run', '--out', 'o'], base)).not.toHaveProperty('open');
    expect(
      parsePilotArgs(['pilot', '--run', 'r', '--buggy', 'b', '--fixed', 'f', '--open'], base).open,
    ).toBe(true);
  });

  test('open command per platform (a path with spaces stays one argument)', () => {
    expect(openCommand('C:\\My Runs\\c3_batch_report.html', 'win32')).toEqual({
      cmd: 'cmd',
      args: ['/c', 'start', '""', '"C:\\My Runs\\c3_batch_report.html"'],
      verbatim: true,
    });
    expect(openCommand('/x/r.html', 'darwin').cmd).toBe('open');
    expect(openCommand('/x/r.html', 'linux')).toEqual({
      cmd: 'xdg-open',
      args: ['/x/r.html'],
      verbatim: false,
    });
  });
});

describe('C3-16 report on the golden example (generated on the planted-bug version, then piloted)', () => {
  let runs: string;
  let out: string;
  beforeAll(async () => {
    runs = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-rep-'));
    out = path.join(runs, 'example-run');
    fs.cpSync(GOLDEN, out, { recursive: true });
    for (const d of ['c3', 'c4']) fs.rmSync(path.join(out, d), { recursive: true, force: true });
    await run({ in: out, out, subjectRoot: BUGGY, generatedAt: FIXED_TIME, model: model() });
  });
  afterAll(() => fs.rmSync(runs, { recursive: true, force: true }));

  test('c3 run writes c3/c3_report.html: every step, every scenario, links to files and rules', () => {
    const html = fs.readFileSync(path.join(out, REPORT_FILE), 'utf8');
    expect(html.startsWith('<!doctype html>')).toBe(true);
    // self-contained: no external scripts, styles or fonts
    expect(html).not.toMatch(/<script[^>]+src=|<link[^>]+href=|@import|https?:\/\/(?!claude)/);
    for (const step of [
      'C3-03',
      'C3-04',
      'C3-05',
      'C3-07',
      'C3-08',
      'C3-09',
      'C3-10',
      'C3-11',
      'C3-12',
      'C3-13',
      'C3-14',
    ])
      expect(html).toContain(`>${step}<`);
    expect(html).toContain('SCN-EX-001-01');
    expect(html).toContain('SCN-EX-001-02');
    // the mocked repository and the model's behaviour for it (escaped)
    expect(html).toContain('userRepository');
    expect(html).toContain('save() returns the given user with id &#39;u1&#39;.');
    // VS Code links: feature file at the scenario line, buggy source at the export line, C3 rule files
    const feature = loadRun(out).inputs!.scenarios[0]!;
    expect(html).toContain(esc(vscodeUrl(path.join(out, feature.featureFile), feature.line)));
    expect(html).toMatch(/vscode:\/\/file[^"]*example-off-by-one[^"]*:\d+/);
    expect(html).toMatch(/vscode:\/\/file[^"]*src\/mock\/rules\.ts:\d+/);
    expect(html).toMatch(/vscode:\/\/file[^"]*src\/route\/confidence\.ts:\d+/);
    // confidence maths: weights and the threshold
    expect(html).toContain('× 0.3');
    expect(html).toMatch(/≥ 0\.8/);
    // before the pilot the page says so
    expect(html).toContain('Pilot not run yet');
  });

  test('c3 pilot writes the roots and rewrites the page with the outcomes; nothing else changes', () => {
    pilot(
      { run: out, buggy: BUGGY, fixed: path.join(GOLDEN, 'subject-src'), label: 'example' },
      () => {},
    );
    const res = JSON.parse(
      fs.readFileSync(path.join(out, 'c3', 'work', 'pilot_results.json'), 'utf8'),
    );
    expect(res.roots).toEqual({
      buggy: path.resolve(BUGGY),
      fixed: path.resolve(GOLDEN, 'subject-src'),
    });

    const html = fs.readFileSync(path.join(out, REPORT_FILE), 'utf8');
    expect(html).toContain('<h1>example</h1>');
    expect(html).toContain('Bug detected');
    expect(html).toContain('TST-EX-001-02-05');
    // the bug-detected scenario comes first
    expect(html.indexOf('id="SCN-EX-001-02"')).toBeLessThan(html.indexOf('id="SCN-EX-001-01"'));
    // links to the fixed version too
    expect(html).toContain(esc(vscodeUrl(path.join(GOLDEN, 'subject-src'))).slice(0, 30));

    // read-only: writing the report again changes no other file
    const before = snapshot(out);
    writeRunReport(out);
    expect(snapshot(out)).toEqual(before);
  });

  test('text from the inputs is escaped (no HTML injection from a feature file or the model)', () => {
    const d = loadRun(out);
    d.inputs!.scenarios[0]!.scenarioName = '<img src=x onerror=alert(1)>';
    d.label = '<script>alert(1)</script>';
    const html = renderRunReport(d);
    expect(html).not.toContain('<img src=x');
    expect(html).not.toContain('<script>alert(1)');
    expect(html).toContain('&lt;img src=x onerror=alert(1)&gt;');
  });

  test('batch page: runs in the given order, totals, links to each run page; missing runs are listed', () => {
    const r = writeBatchReport(runs, {
      runs: ['example-run', 'not-a-run'],
      generatedAt: FIXED_TIME,
    });
    expect(r.file).toBe(path.join(runs, BATCH_REPORT_FILE));
    expect(r.runs).toEqual(['example-run']);
    expect(r.missing).toEqual(['not-a-run']);
    const html = fs.readFileSync(r.file, 'utf8');
    expect(html).toContain('href="example-run/c3/c3_report.html"');
    expect(html).toContain('C3 batch report (1 runs)');
    expect(html).toMatch(/<div class="n">7<\/div><div class="l">Jest tests/);
    expect(html).toMatch(/<div class="n">1<\/div><div class="l">Bug detected/);
    // default: every finished run in the folder
    expect(writeBatchReport(runs).runs).toEqual(['example-run']);
  });
});
