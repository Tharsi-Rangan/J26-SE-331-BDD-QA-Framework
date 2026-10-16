import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';
import { run } from '../src/index.js';
import { readC3Inputs } from '../src/input/reader.js';
import type { C3Inputs, C3ScenarioInput } from '../src/input/types.js';
import { buildMockDecisions, chooseTargetExports } from '../src/mock/decisions.js';
import { decide, RULES, type RuleContext } from '../src/mock/rules.js';
import { scanModule } from '../src/scan/scanner.js';
import type { ScannedDependency } from '../src/scan/types.js';

const GOLDEN = fileURLToPath(
  new URL('../../contracts/fixtures/golden/example-registration', import.meta.url),
);
const VALIDATE = fileURLToPath(new URL('../../contracts/scripts/validate.mjs', import.meta.url));
const SUBJECT = fileURLToPath(new URL('./fixtures/scan-subject', import.meta.url));
const FIXED_TIME = '2026-10-16T10:00:00+05:30';

function goldenIndex(inputs: C3Inputs) {
  const s = inputs.scenarios[0]!.subject;
  const scan = scanModule(path.join(GOLDEN, 'subject-src'), s.modulePath);
  return new Map([[`${s.subjectId}|${s.modulePath}`, scan]]);
}

/** A hand-made scenario on the scan-subject fixture. */
function scenario(name: string, when: string, exportsInScope: string[]): C3ScenarioInput {
  return {
    scenarioId: 'SCN-FX-001-01',
    requirementId: 'REQ-FX-001',
    scenarioName: name,
    scenarioType: 'positive',
    isOutline: false,
    featureFile: 'c2/features/REQ-FX-001.feature',
    line: 3,
    steps: [
      { keyword: 'Given', text: 'the user repository is available', line: 4 },
      { keyword: 'When', text: when, line: 5 },
      { keyword: 'Then', text: 'the result is returned', line: 6 },
    ],
    examples: [],
    metadata: {} as C3ScenarioInput['metadata'],
    subject: {
      subjectId: 'SUB-FX-1',
      projectCode: 'FX',
      modulePath: 'lib/main.js',
      exports: exportsInScope,
      source: {},
    },
  };
}

describe('C3-05 mock decisions on the golden example', () => {
  const inputs = readC3Inputs(GOLDEN);
  const { file } = buildMockDecisions(inputs, goldenIndex(inputs), { generatedAt: FIXED_TIME });

  test('same decisions as the hand-written golden mock_decisions.json', () => {
    const golden = JSON.parse(fs.readFileSync(path.join(GOLDEN, 'c3/mock_decisions.json'), 'utf8'));
    const pick = (d: any) => ({
      decision_id: d.decision_id,
      scenario_id: d.scenario_id,
      module_path: d.module_path,
      import_specifier: d.dependency.import_specifier,
      symbol: d.dependency.symbol,
      kind: d.dependency.kind,
      resolved_path: d.dependency.resolved_path,
      side_effect: d.dependency.side_effect,
      decision: d.decision,
      rule_id: d.rule_id,
    });
    expect(file.decisions.map(pick)).toEqual(golden.decisions.map(pick));
  });

  test('every decision has decision, rule_id and reason; every mock has a behaviour', () => {
    for (const d of file.decisions) {
      expect(d.decision).toMatch(/^(mock|no_mock)$/);
      expect(d.rule_id).toMatch(/^R-\d{2}$/);
      expect(d.reason.length).toBeGreaterThan(20);
      if (d.decision === 'mock') expect(d.behaviour?.summary).toBeTruthy();
    }
    expect(file.decisions[0]!.behaviour!.derived_from_steps).toContain(
      'Given the user repository is available',
    );
  });

  test('same input gives the same output 3 times (NFR4)', () => {
    const outputs = [1, 2, 3].map(() =>
      JSON.stringify(
        buildMockDecisions(readC3Inputs(GOLDEN), goldenIndex(inputs), { generatedAt: FIXED_TIME })
          .file,
      ),
    );
    expect(new Set(outputs).size).toBe(1);
  });

  test('c3 run writes c3/mock_decisions.json that passes validate.mjs', async () => {
    const out = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-md-'));
    try {
      fs.cpSync(GOLDEN, out, { recursive: true });
      fs.rmSync(path.join(out, 'c3', 'mock_decisions.json'));
      await run({ in: GOLDEN, out, generatedAt: FIXED_TIME });
      expect(fs.existsSync(path.join(out, 'c3', 'mock_decisions.json'))).toBe(true);
      const res = spawnSync(process.execPath, [VALIDATE, out], { encoding: 'utf8' });
      expect(res.stdout).toContain('c3/mock_decisions.json matches c3-mock-decisions.schema.json');
      expect(res.stdout).toContain('C3 mock decision links checked');
      expect(res.status).toBe(0);
    } finally {
      fs.rmSync(out, { recursive: true, force: true });
    }
  });
});

describe('C3-05 which export a scenario tests', () => {
  const scan = scanModule(SUBJECT, 'lib/main.js');

  test('one export in scope -> that export', () => {
    const t = chooseTargetExports(scenario('Save', 'a user is saved', ['saveUser']), scan);
    expect(t.exports).toEqual(['saveUser']);
  });

  test('export named in the steps, also as separate words (camelCase)', () => {
    const all = ['isAbsolute', 'saveUser', 'loadConfig', 'pickId'];
    expect(
      chooseTargetExports(scenario('x', 'isAbsolute is called with "c:/"', all), scan).exports,
    ).toEqual(['isAbsolute']);
    expect(
      chooseTargetExports(scenario('x', 'the config is loaded from disk', all), scan).exports,
    ).toEqual(['loadConfig']);
  });

  test('nothing named -> every export in scope (none are missed)', () => {
    const t = chooseTargetExports(
      scenario('x', 'something happens', ['isAbsolute', 'pickId']),
      scan,
    );
    expect(t.exports).toEqual(['isAbsolute', 'pickId']);
    expect(t.basis).toMatch(/no export named/);
  });
});

describe('C3-05 decisions on the scan-subject fixture', () => {
  const scan = scanModule(SUBJECT, 'lib/main.js');
  const build = (sc: C3ScenarioInput) =>
    buildMockDecisions(
      { runId: 'RUN-FIXTURE-FX-1', inDir: SUBJECT, scenarios: [sc], skipped: [] },
      new Map([['SUB-FX-1|lib/main.js', scan]]),
      { generatedAt: FIXED_TIME },
    ).file.decisions.map((d) => [
      `${d.dependency.import_specifier}#${d.dependency.symbol}`,
      d.decision,
      d.rule_id,
    ]);

  test('saveUser: database and clock are mocked; load-time logging and file reads stay real', () => {
    expect(build(scenario('Save a user', 'saveUser is called', ['saveUser']))).toEqual([
      ['./repo#save', 'mock', 'R-03'],
      ['Date#now', 'mock', 'R-04'],
      ['debug#default', 'no_mock', 'R-02'],
      ['fs#readdirSync', 'no_mock', 'R-06'],
      ['node:path#join', 'no_mock', 'R-07'],
      ['path#join', 'no_mock', 'R-07'],
      ['process#env', 'no_mock', 'R-06'],
    ]);
  });

  test('loadConfig: a file read inside the function under test is mocked (R-05)', () => {
    const rows = build(scenario('Load', 'loadConfig is called', ['loadConfig']));
    expect(rows).toContainEqual(['fs#readFileSync', 'mock', 'R-05']);
    expect(rows).toContainEqual(['./limits.json#maxName', 'no_mock', 'R-07']);
  });

  test('a run folder with two subjects is rejected (one subject_id per file)', () => {
    const a = scenario('a', 'saveUser is called', ['saveUser']);
    const b = {
      ...a,
      scenarioId: 'SCN-FX-001-02',
      subject: { ...a.subject, subjectId: 'SUB-FX-2' },
    };
    expect(() =>
      buildMockDecisions(
        { runId: 'RUN-FIXTURE-FX-1', inDir: SUBJECT, scenarios: [a, b], skipped: [] },
        new Map([
          ['SUB-FX-1|lib/main.js', scan],
          ['SUB-FX-2|lib/main.js', scan],
        ]),
      ),
    ).toThrow(/one subject/);
  });
});

describe('C3-05 rule table', () => {
  const dep = (over: Partial<ScannedDependency>): ScannedDependency => ({
    key: 'x#y',
    importSpecifier: 'x',
    symbol: 'y',
    kind: 'external_package',
    sideEffect: 'unknown',
    sideEffectBasis: 'test',
    lines: [1],
    ...over,
  });
  const ctx = (
    over: Partial<ScannedDependency>,
    usedByTarget = true,
    usedAtLoad = false,
  ): RuleContext => ({
    dep: dep(over),
    usedByTarget,
    usedAtLoad,
  });

  test('rule ids are R-01..R-08 in order, and each has a plain-words condition', () => {
    expect(RULES.map((r) => r.id)).toEqual([
      'R-01',
      'R-02',
      'R-03',
      'R-04',
      'R-05',
      'R-06',
      'R-07',
      'R-08',
    ]);
    for (const r of RULES) expect(r.when.length).toBeGreaterThan(10);
  });

  test.each([
    ['network', ctx({ sideEffect: 'network', importSpecifier: 'axios' }), 'R-01', 'mock'],
    ['logging', ctx({ sideEffect: 'io', importSpecifier: 'debug' }), 'R-02', 'no_mock'],
    [
      'console',
      ctx({ sideEffect: 'io', importSpecifier: 'console', kind: 'global_object' }),
      'R-02',
      'no_mock',
    ],
    ['database', ctx({ sideEffect: 'database', importSpecifier: './repo' }), 'R-03', 'mock'],
    ['time', ctx({ sideEffect: 'time', importSpecifier: 'Date' }), 'R-04', 'mock'],
    ['random', ctx({ sideEffect: 'random', importSpecifier: 'Math' }), 'R-04', 'mock'],
    ['io in function', ctx({ sideEffect: 'io', importSpecifier: 'fs' }), 'R-05', 'mock'],
    [
      'io on load only',
      ctx({ sideEffect: 'io', importSpecifier: 'fs' }, false, true),
      'R-06',
      'no_mock',
    ],
    ['pure', ctx({ sideEffect: 'none', importSpecifier: 'qs' }), 'R-07', 'no_mock'],
    ['unknown', ctx({ sideEffect: 'unknown', importSpecifier: 'pdfkit' }), 'R-08', 'no_mock'],
  ])('%s -> %s', (_label, c, ruleId, decision) => {
    const { rule, reason } = decide(c);
    expect(rule.id).toBe(ruleId);
    expect(rule.decision).toBe(decision);
    expect(reason).toContain(c.dep.importSpecifier);
  });
});
