import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, test } from 'vitest';
import { parsePilotArgs } from '../src/args.js';
import { run } from '../src/index.js';
import { FakeModelClient } from '../src/model/index.js';
import { comparePilot, outcomeOf, pilot, pilotMarkdown } from '../src/pilot.js';
import type { JestRunResult } from '../src/runner/jest.js';

const GOLDEN = fileURLToPath(
  new URL('../../contracts/fixtures/golden/example-registration', import.meta.url),
);
const BUGGY = fileURLToPath(new URL('../fixtures/pilot/example-off-by-one', import.meta.url));
const FIXED_TIME = '2026-10-19T10:00:00+05:30';

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

describe('C3-14 pilot outcome', () => {
  test('fail on buggy + pass on fixed = bug; fail on fixed = false alarm; pass on both = no signal', () => {
    expect(outcomeOf('failed', 'passed')).toBe('bug_detected');
    expect(outcomeOf('passed', 'failed')).toBe('false_alarm');
    expect(outcomeOf('failed', 'failed')).toBe('false_alarm');
    expect(outcomeOf('passed', 'passed')).toBe('no_signal');
    expect(outcomeOf('missing', 'passed')).toBe('not_run');
  });

  test('CLI options', () => {
    const base = path.resolve('repo-root');
    const o = parsePilotArgs(
      ['pilot', '--run', 'runs/R', '--buggy', 'b', '--fixed', 'f', '--label', 'Express-5'],
      base,
    );
    expect(o).toEqual({
      run: path.join(base, 'runs', 'R'),
      buggy: path.join(base, 'b'),
      fixed: path.join(base, 'f'),
      label: 'Express-5',
    });
    expect(() => parsePilotArgs(['pilot', '--run', 'x'])).toThrow(/Usage: c3 pilot/);
  });
});

describe('C3-14 pilot on the example with a planted off-by-one bug (real Jest)', () => {
  let out: string;
  beforeAll(async () => {
    out = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-p-'));
    fs.cpSync(GOLDEN, out, { recursive: true });
    for (const d of ['c3', 'c4']) fs.rmSync(path.join(out, d), { recursive: true, force: true });
    // generated on the BUGGY version, as in real use
    await run({ in: out, out, subjectRoot: BUGGY, generatedAt: FIXED_TIME, model: model() });
  });
  afterAll(() => fs.rmSync(out, { recursive: true, force: true }));

  test('the same tests on buggy and fixed: the age-65 row detects the bug, no false alarms', () => {
    const r = pilot(
      { run: out, buggy: BUGGY, fixed: path.join(GOLDEN, 'subject-src'), label: 'example' },
      () => {},
    );
    expect(r.summary).toMatchObject({
      scenarios: 2,
      runnable_scenarios: 2,
      stub_scenarios: 0,
      runnable_percent: 100,
      tests_generated: 7,
      bugs_detected_tests: 1,
      bugs_detected_scenarios: 1,
      false_alarm_tests: 0,
      no_signal_tests: 6,
    });
    const bug = r.tests.find((t) => t.outcome === 'bug_detected')!;
    expect(bug.test_id).toBe('TST-EX-001-02-05');
    expect(bug.buggy_message).toMatch(/age out of range/);
    const md = fs.readFileSync(path.join(out, 'c3', 'work', 'pilot_results.md'), 'utf8');
    expect(md).toContain('| TST-EX-001-02-05 | failed | passed | bug_detected |');
    expect(fs.existsSync(path.join(out, 'c3', 'work', 'pilot_results.json'))).toBe(true);
  });

  test('a test that fails on the fixed version counts as a false alarm; stubs are listed', () => {
    const fake = (failId?: string): JestRunResult => {
      const m = JSON.parse(fs.readFileSync(path.join(out, 'c3', 'test_manifest.json'), 'utf8'));
      return {
        ok: true,
        exitCode: 0,
        suiteErrors: [],
        stderr: '',
        tests: m.tests.map((t: { test_id: string; jest_full_name: string }) => ({
          fullName: t.jest_full_name,
          status: t.test_id === failId ? 'failed' : 'passed',
          failureMessages: t.test_id === failId ? ['Error: expected 1'] : [],
          file: 'x',
        })),
      };
    };
    const r = comparePilot(out, fake(), fake('TST-EX-001-01-01'), 'x');
    expect(r.summary.false_alarm_tests).toBe(1);
    expect(r.summary.false_alarm_rate).toBe(14.3);
    expect(pilotMarkdown(r)).toContain('TST-EX-001-01-01 (false_alarm): Error: expected 1');
  });
});
