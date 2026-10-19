import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';
import { run } from '../src/index.js';
import { FakeModelClient, type ModelRequest } from '../src/model/index.js';
import { brokenScenarios, repairMessages } from '../src/verify/repair.js';
import type { VerificationWorkFile } from '../src/verify/verify.js';

const GOLDEN = fileURLToPath(
  new URL('../../contracts/fixtures/golden/example-registration', import.meta.url),
);
const FIXED_TIME = '2026-10-19T10:00:00+05:30';
const B = {
  steps: ['S1'],
  kind: 'returns_input',
  value: { id: 'u1' },
  error_message: null,
  summary: "save() returns the given user with id 'u1'.",
  rationale: 'S1 says the repository is available.',
};
const GOOD1 = {
  act: 'registerUser({ age: 30, email: "amal@example.com" })',
  assertions: [
    {
      then: 'T1',
      category: 'state_change',
      target: 'userRepository.save',
      change: 'called_with',
      args: [{ age: 30, email: 'amal@example.com' }],
    },
    { then: 'T1', category: 'equality', actual: 'result.age', expected: 30 },
  ],
};
/** Passes every slot check, but result.profile is undefined, so the TypeError is raised in the test code. */
const BROKEN1 = {
  ...GOOD1,
  assertions: [{ then: 'T1', category: 'equality', actual: 'result.profile.age', expected: 30 }],
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
      change: 'called',
    },
  ],
};

/** Fake model: C3-07 behaviour, C3-08 answers, and `repair(n)` for the n-th repair call of scenario 1. */
function model(repair: (n: number) => object) {
  let repairs = 0;
  return new FakeModelClient((req: ModelRequest) => {
    const u = req.messages[1]!.content;
    if (u.includes('Mocked dependency:')) return JSON.stringify(B);
    if (u.includes('Age at and around')) return JSON.stringify(A2);
    if (req.purpose?.startsWith('C3-12 repair')) return JSON.stringify(repair(++repairs));
    return JSON.stringify(BROKEN1);
  });
}

async function goldenRun(m: FakeModelClient, patch?: (s: string) => string) {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-r-'));
  fs.cpSync(GOLDEN, out, { recursive: true });
  for (const d of ['c3', 'c4']) fs.rmSync(path.join(out, d), { recursive: true, force: true });
  if (patch) {
    const f = path.join(out, 'subject-src/src/registration.js');
    fs.writeFileSync(f, patch(fs.readFileSync(f, 'utf8')));
  }
  await run({ in: out, out, generatedAt: FIXED_TIME, model: m });
  const read = (f: string) => JSON.parse(fs.readFileSync(path.join(out, f), 'utf8'));
  const res = {
    manifest: read('c3/test_manifest.json'),
    log: read('c3/work/repair_log.json'),
    verification: read('c3/work/verification.json') as VerificationWorkFile,
  };
  fs.rmSync(out, { recursive: true, force: true });
  return res;
}

describe('C3-12 repair loop', () => {
  test('a broken test (TypeError in the test code) is repaired in round 1; repair_rounds recorded', async () => {
    const m = model(() => GOOD1);
    const r = await goldenRun(m);
    expect(r.log.entries).toHaveLength(1);
    expect(r.log.entries[0]).toMatchObject({
      scenario_id: 'SCN-EX-001-01',
      round: 1,
      answer: 'usable',
      fixed: true,
    });
    expect(r.log.entries[0].errors.join()).toMatch(
      /Cannot read properties of undefined \(reading 'age'\)/,
    );
    expect(r.verification.tests.every((t) => t.run === 'passed')).toBe(true);
    const rounds = Object.fromEntries(
      r.manifest.tests.map((t: any) => [t.test_id, t.repair_rounds]),
    );
    expect(rounds['TST-EX-001-01-01']).toBe(1);
    expect(rounds['TST-EX-001-02-01']).toBe(0);
    // the repair call carried the previous answer and the error
    const call = m.calls.find((c) => c.purpose?.startsWith('C3-12 repair 1'))!;
    expect(call.messages.at(-2)!.content).toContain('result.profile.age');
    expect(call.messages.at(-1)!.content).toMatch(/The error comes from the test itself/);
  });

  test('never fixed -> gives up after 3 rounds; the broken scenario gets no runnable test', async () => {
    const m = model(() => BROKEN1);
    const r = await goldenRun(m);
    expect(r.log.entries.map((e: any) => e.round)).toEqual([1, 2, 3]);
    expect(r.log.entries.every((e: any) => !e.fixed)).toBe(true);
    expect(r.manifest.tests.map((t: any) => t.scenario_id)).not.toContain('SCN-EX-001-01');
    expect(r.manifest.tests).toHaveLength(6); // the outline is still released
    expect(m.calls.filter((c) => c.purpose?.startsWith('C3-12 repair'))).toHaveLength(3);
  });

  test('a test that fails because of the code under test (a possible bug) is never repaired', async () => {
    const r = await goldenRun(
      new FakeModelClient((req) => {
        const u = req.messages[1]!.content;
        if (u.includes('Mocked dependency:')) return JSON.stringify(B);
        return JSON.stringify(u.includes('Age at and around') ? A2 : GOOD1);
      }),
      (s) => s.replace('age > 65', 'age > 64'),
    );
    expect(r.log.entries).toEqual([]);
    expect(r.verification.tests.find((t) => t.test_id === 'TST-EX-001-02-05')!.run).toBe(
      'subject_error',
    );
    expect(r.manifest.tests.every((t: any) => t.repair_rounds === 0)).toBe(true);
  });

  test('brokenScenarios groups errors per scenario; repairMessages carries the answer and errors', () => {
    const v: VerificationWorkFile = {
      version: '0',
      subject_run: true,
      tests: [
        {
          test_id: 'TST-X-001-01-01',
          scenario_id: 'SCN-X-001-01',
          syntactic: 'pass',
          referential: 'pass',
          traceability: 'pass',
          semantic: { status: 'pass', score: 1 },
          run: 'test_error',
          message: 'TypeError: x',
          problems: [],
        },
        {
          test_id: 'TST-X-001-02-01',
          scenario_id: 'SCN-X-001-02',
          syntactic: 'pass',
          referential: 'pass',
          traceability: 'pass',
          semantic: { status: 'pass', score: 1 },
          run: 'assertion_failed',
          message: 'expect',
          problems: [],
        },
      ],
    };
    expect([...brokenScenarios(v)]).toEqual([['SCN-X-001-01', ['TST-X-001-01-01: TypeError: x']]]);
    const msgs = repairMessages({ act: 'f(1)', assertions: [] } as never, ['TypeError: x']);
    expect(msgs[0]).toEqual({ role: 'assistant', content: '{"act":"f(1)","assertions":[]}' });
    expect(msgs[1]!.content).toContain('- TypeError: x');
  });
});
