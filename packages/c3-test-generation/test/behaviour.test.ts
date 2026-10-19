import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test, vi } from 'vitest';
import { run } from '../src/index.js';
import { readC3Inputs } from '../src/input/reader.js';
import {
  behaviourPrompt,
  behaviourToJest,
  checkAnswer,
  deriveMockBehaviours,
  usesResult,
  type StructuredBehaviour,
} from '../src/mock/behaviour.js';
import { buildMockDecisions, type MockDecision } from '../src/mock/decisions.js';
import { FakeModelClient } from '../src/model/index.js';
import { scanModule } from '../src/scan/scanner.js';

const GOLDEN = fileURLToPath(
  new URL('../../contracts/fixtures/golden/example-registration', import.meta.url),
);
const VALIDATE = fileURLToPath(new URL('../../contracts/scripts/validate.mjs', import.meta.url));
const FIXED_TIME = '2026-10-19T10:00:00+05:30';

function golden() {
  const inputs = readC3Inputs(GOLDEN);
  const s = inputs.scenarios[0]!.subject;
  const scan = scanModule(path.join(GOLDEN, 'subject-src'), s.modulePath);
  const built = buildMockDecisions(inputs, new Map([[`${s.subjectId}|${s.modulePath}`, scan]]), {
    generatedAt: FIXED_TIME,
  });
  return { inputs, ...built };
}

/** The answer a good model gives for the golden repository mock. */
const GOOD = JSON.stringify({
  steps: ['S1'],
  kind: 'returns_input',
  value: { id: 'u1' },
  error_message: null,
  summary: "save() returns the given user with id 'u1'.",
  rationale: 'S1 says the repository is available, so save succeeds and echoes the stored user.',
});

describe('C3-07 prompt', () => {
  const { inputs, file, targets } = golden();
  const sc = inputs.scenarios[0]!;
  const d = file.decisions[0]!;

  test('lists the Given/When steps as S1.. and the dependency facts', () => {
    const { user } = behaviourPrompt(sc, d, targets.get(sc.scenarioId)!.exports);
    expect(user).toContain('S1: Given the user repository is available');
    expect(user).toContain('S2: When a user registers with age 30 and email "amal@example.com"');
    expect(user).not.toMatch(/S\d: Then/); // Then steps are context, never citable
    expect(user).toContain("save() from './userRepository'");
    expect(user).toContain('Side effect: database');
    expect(user).toContain('Function under test: registerUser');
    expect(user).toContain('(the real code only throws in tests');
  });

  test('shows the call site and the Then steps as context only', () => {
    const { user } = behaviourPrompt(
      sc,
      d,
      ['registerUser'],
      ['  return userRepository.save({ age, email });'],
    );
    expect(user).toContain('Where the function under test calls it:\n  return userRepository.save');
    expect(user).toMatch(/Expected outcome \(context only.*\n?Then the user is saved with age 30/);
    expect(user).not.toMatch(/S\d: Then/);
  });

  test('same input -> same prompt (so the answer cache key is stable)', () => {
    const a = behaviourPrompt(sc, d, ['registerUser']);
    const b = behaviourPrompt(sc, d, ['registerUser']);
    expect(a).toEqual(b);
  });

  test('a Scenario Outline prompt says placeholders change per row', () => {
    const outline = inputs.scenarios[1]!;
    const { user } = behaviourPrompt(outline, file.decisions[1]!, ['registerUser']);
    expect(user).toContain('Scenario Outline');
    expect(user).toContain('S2: When a user registers with age <age>');
  });
});

describe('C3-07 answer check', () => {
  const { inputs, file } = golden();
  const sc = inputs.scenarios[0]!;
  const d = file.decisions[0]!;
  const ok = JSON.parse(GOOD);

  test('a good answer has no problems', () => {
    expect(checkAnswer(ok, sc, d)).toEqual([]);
  });

  test('unknown step ids, missing error_message and empty text are problems', () => {
    expect(checkAnswer({ ...ok, steps: ['S9'] }, sc, d).join()).toMatch(/unknown ids/);
    expect(checkAnswer({ ...ok, steps: [] }, sc, d).join()).toMatch(/non-empty/);
    expect(checkAnswer({ ...ok, kind: 'throws', error_message: '' }, sc, d).join()).toMatch(
      /error_message/,
    );
    expect(checkAnswer({ ...ok, kind: 'explodes' }, sc, d).join()).toMatch(/"kind" must be/);
    expect(checkAnswer({ ...ok, summary: '' }, sc, d).join()).toMatch(/summary/);
    expect(checkAnswer({ ...ok, value: [1] }, sc, d).join()).toMatch(/object or null/);
  });

  test('resolves/rejects on a function that does not return a Promise is a problem', () => {
    expect(checkAnswer({ ...ok, kind: 'resolves', value: 1 }, sc, d).join()).toMatch(
      /needs a Promise/,
    );
  });

  test('a failing mock with no failure step is a problem (rule 1)', () => {
    const p = checkAnswer({ ...ok, kind: 'throws', error_message: 'Database error' }, sc, d);
    expect(p.join()).toMatch(/no Given\/When step says it fails; the mock must succeed/);
  });

  test('a failing mock is fine when a step says the dependency fails', () => {
    const down = {
      ...sc,
      steps: [{ ...sc.steps[0]!, text: 'the user repository is down' }, ...sc.steps.slice(1)],
    };
    expect(
      checkAnswer({ ...ok, kind: 'throws', error_message: 'repository is down' }, down, d),
    ).toEqual([]);
  });

  test('null is a problem when the function uses the result (rule 4), fine when it does not', () => {
    const site = ['  return userRepository.save({ age, email });'];
    const nul = { ...ok, kind: 'returns', value: null };
    expect(checkAnswer(nul, sc, d, site).join()).toMatch(/must not be null/);
    expect(checkAnswer(nul, sc, d, ['  userRepository.save({ age, email });'])).toEqual([]);
  });

  test('usesResult reads return, assignment, await and chained calls', () => {
    expect(usesResult(['return repo.save(u);'], d)).toBe(true);
    expect(usesResult(['const saved = repo.save(u);'], d)).toBe(true);
    expect(usesResult(['x = await repo.save(u)'], d)).toBe(true);
    expect(usesResult(['repo.save(u).id'], d)).toBe(true);
    expect(usesResult(['repo.save(u);'], d)).toBe(false);
    expect(usesResult(['if (repo.save(u) === 1) {'], d)).toBe(false);
  });

  test('returns needs a value', () => {
    const { value: _v, ...noValue } = ok;
    expect(checkAnswer({ ...noValue, kind: 'returns' }, sc, d).join()).toMatch(
      /"value" is required/,
    );
  });
});

describe('C3-07 deriveMockBehaviours', () => {
  test('a good answer becomes the behaviour; steps are the exact step texts; model tag recorded', async () => {
    const { inputs, file, targets } = golden();
    const model = new FakeModelClient([GOOD], 'Qwen/Qwen2.5-Coder-7B-Instruct:nscale@huggingface');
    const { file: out, work } = await deriveMockBehaviours(file, inputs, model, { targets });
    const b = out.decisions[0]!.behaviour!;
    expect(b.derived_from_steps).toEqual(['Given the user repository is available']);
    expect(b.summary).toBe("save() returns the given user with id 'u1'.");
    expect(b.model).toBe('Qwen/Qwen2.5-Coder-7B-Instruct:nscale@huggingface');
    expect(work.records[0]).toMatchObject({
      decision_id: 'MD-001',
      source: 'model',
      kind: 'returns_input',
      value: { id: 'u1' },
      attempts: 1,
      problems: [],
    });
    expect(model.calls).toHaveLength(2); // one per mock decision
    expect(model.calls[0]!.temperature).toBe(0);
    expect(file.decisions[0]!.behaviour!.rationale).toMatch(/Default for rule/); // input not changed
  });

  test('a bad answer gets one retry that lists the problems', async () => {
    const { inputs, file } = golden();
    const bad = JSON.stringify({ ...JSON.parse(GOOD), steps: ['S7'] });
    const model = new FakeModelClient([bad, GOOD]);
    const { work } = await deriveMockBehaviours(
      { ...file, decisions: [file.decisions[0]!] },
      inputs,
      model,
    );
    expect(work.records[0]).toMatchObject({ source: 'model', attempts: 2 });
    expect(work.records[0]!.problems.join()).toMatch(/attempt 1: "steps" has unknown ids/);
    const retry = model.calls[1]!.messages;
    expect(retry.at(-2)).toEqual({ role: 'assistant', content: bad });
    expect(retry.at(-1)!.content).toMatch(/unknown ids \["S7"\]/);
  });

  test('two bad answers -> rule default kept and marked rule_default', async () => {
    const { inputs, file } = golden();
    const model = new FakeModelClient(['I think save returns a user.']);
    const { file: out, work } = await deriveMockBehaviours(file, inputs, model);
    expect(work.records.every((r) => r.source === 'rule_default')).toBe(true);
    expect(work.records[0]).toMatchObject({ kind: 'returns_input', attempts: 2 });
    expect(out.decisions[0]!.behaviour!.rationale).toMatch(/not usable.*rule R-03 default kept/);
    expect(out.decisions[0]!.behaviour!.model).toBeUndefined();
  });

  test('no_mock decisions are never sent to the model', async () => {
    const { inputs, file } = golden();
    const noMock: MockDecision = { ...file.decisions[0]!, decision: 'no_mock', behaviour: null };
    const model = new FakeModelClient([GOOD]);
    const { file: out, work } = await deriveMockBehaviours(
      { ...file, decisions: [noMock] },
      inputs,
      model,
    );
    expect(model.calls).toHaveLength(0);
    expect(work.records).toEqual([]);
    expect(out.decisions[0]).toEqual(noMock);
  });

  test('a Promise signature turns returns/throws into resolves/rejects, with a note', async () => {
    const { inputs, file } = golden();
    const d: MockDecision = {
      ...file.decisions[0]!,
      dependency: { ...file.decisions[0]!.dependency, type_signature: '(u: any) => Promise<any>' },
    };
    const answer = JSON.stringify({ ...JSON.parse(GOOD), kind: 'returns', value: { ok: true } });
    const { work } = await deriveMockBehaviours(
      { ...file, decisions: [d] },
      inputs,
      new FakeModelClient([answer]),
    );
    expect(work.records[0]).toMatchObject({ kind: 'resolves', value: { ok: true } });
    expect(work.records[0]!.warnings).toContain(
      'returns -> resolves (signature returns a Promise)',
    );
  });

  test('a cited failure step with a succeeding mock is flagged for review', async () => {
    const { inputs, file } = golden();
    const sc = inputs.scenarios[0]!;
    const failing = {
      ...inputs,
      scenarios: [
        {
          ...sc,
          steps: [
            { ...sc.steps[0]!, text: 'the user repository is unavailable' },
            ...sc.steps.slice(1),
          ],
        },
      ],
    };
    const { work } = await deriveMockBehaviours(
      { ...file, decisions: [file.decisions[0]!] },
      failing,
      new FakeModelClient([GOOD]),
    );
    expect(work.records[0]!.warnings).toEqual([
      'a cited step sounds like a failure, but the mock succeeds',
    ]);
  });

  test('same answers -> same output 3 times (NFR4)', async () => {
    const outs = [];
    for (let i = 0; i < 3; i++) {
      const { inputs, file } = golden();
      const r = await deriveMockBehaviours(file, inputs, new FakeModelClient([GOOD]));
      outs.push(JSON.stringify(r));
    }
    expect(new Set(outs).size).toBe(1);
  });
});

describe('C3-07 behaviourToJest (used by the Jest writer)', () => {
  /** Run the generated line on a vi.fn() (same mock API as jest.fn()) and return the mock. */
  function apply(b: StructuredBehaviour) {
    const target = vi.fn();
    new Function('target', behaviourToJest('target', b))(target);
    return target;
  }

  test('returns / returns_input / throws', () => {
    expect(apply({ kind: 'returns', value: 42 })()).toBe(42);
    expect(apply({ kind: 'returns_input', value: { id: 'u1' } })({ age: 30 })).toEqual({
      id: 'u1',
      age: 30,
    });
    expect(apply({ kind: 'returns_input' })('x')).toBe('x');
    expect(() => apply({ kind: 'throws', error_message: 'db down' })()).toThrow('db down');
  });

  test('resolves / rejects / async returns_input', async () => {
    await expect(apply({ kind: 'resolves', value: [1] })()).resolves.toEqual([1]);
    await expect(apply({ kind: 'rejects', error_message: 'timeout' })()).rejects.toThrow('timeout');
    await expect(apply({ kind: 'returns_input', async: true })(7)).resolves.toBe(7);
  });

  test('the golden mock line', () => {
    expect(
      behaviourToJest('userRepository.save', { kind: 'returns_input', value: { id: 'u1' } }),
    ).toBe('userRepository.save.mockImplementation((input) => ({ ...{"id":"u1"}, ...input }));');
  });
});

describe('C3-07 inside c3 run', () => {
  async function runGolden(model?: FakeModelClient) {
    const out = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-mb-'));
    fs.cpSync(GOLDEN, out, { recursive: true });
    fs.rmSync(path.join(out, 'c3', 'mock_decisions.json'));
    await run({ in: GOLDEN, out, generatedAt: FIXED_TIME, model });
    return out;
  }

  test('with a model: behaviour from the model, work file written, validate.mjs passes', async () => {
    const out = await runGolden(new FakeModelClient([GOOD], 'qwen2.5-coder:3b@ollama'));
    try {
      const md = JSON.parse(fs.readFileSync(path.join(out, 'c3/mock_decisions.json'), 'utf8'));
      expect(md.decisions.map((d: any) => d.behaviour.model)).toEqual([
        'qwen2.5-coder:3b@ollama',
        'qwen2.5-coder:3b@ollama',
      ]);
      const work = JSON.parse(
        fs.readFileSync(path.join(out, 'c3/work/mock_behaviour.json'), 'utf8'),
      );
      expect(work.model).toBe('qwen2.5-coder:3b@ollama');
      expect(work.records).toHaveLength(2);
      const res = spawnSync(process.execPath, [VALIDATE, out], { encoding: 'utf8' });
      expect(res.stdout).toContain('c3/mock_decisions.json matches c3-mock-decisions.schema.json');
      expect(res.status).toBe(0);
    } finally {
      fs.rmSync(out, { recursive: true, force: true });
    }
  });

  test('without a model: rule defaults, still valid', async () => {
    const out = await runGolden();
    try {
      const work = JSON.parse(
        fs.readFileSync(path.join(out, 'c3/work/mock_behaviour.json'), 'utf8'),
      );
      expect(work.model).toBeNull();
      expect(work.records.every((r: any) => r.source === 'rule_default')).toBe(true);
      const res = spawnSync(process.execPath, [VALIDATE, out], { encoding: 'utf8' });
      expect(res.status).toBe(0);
    } finally {
      fs.rmSync(out, { recursive: true, force: true });
    }
  });
});
