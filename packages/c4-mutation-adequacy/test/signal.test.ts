import { describe, expect, test } from 'vitest';
import type { Embedder } from '../src/embedding.js';
import { applyTraceSignal, mutantText, traceTexts, type TraceSignalMode } from '../src/signal.js';
import type { Survivor } from '../src/trace.js';
import type { MutationReport, ScenarioMetadata } from '../src/types.js';

// Fake embedder: one vector entry per keyword, set to the keyword count in the text.
const VOCAB = ['age', 'email', 'password', 'register', 'login'];
const fakeEmbed: Embedder = async (texts) =>
  texts.map((t) => VOCAB.map((w) => t.toLowerCase().split(w).length - 1));

const meta: ScenarioMetadata = {
  features: [
    {
      requirement_id: 'REQ-A-001',
      feature_name: 'Age',
      requirement_text_used: 'Register: age from 18 to 65.',
    },
    { requirement_id: 'REQ-B-001', feature_name: 'Email login' },
  ],
  scenarios: [
    {
      scenario_id: 'SCN-A-001-01',
      requirement_id: 'REQ-A-001',
      scenario_name: 'Register with a valid age',
    },
    {
      scenario_id: 'SCN-A-001-02',
      requirement_id: 'REQ-A-001',
      scenario_name: 'Reject a short password',
    },
    { scenario_id: 'SCN-B-001-01', requirement_id: 'REQ-B-001', scenario_name: 'Login with email' },
  ],
};
const texts = traceTexts(meta);

const source = [
  'function register(user) {',
  '  if (user.age < 18) throw new Error("too young");',
  '  if (user.age > 65) throw new Error("too old");',
  '  return save(user);',
  '}',
  '',
  'function login(email) {',
  '  return find(email);',
  '}',
].join('\n');
const report: MutationReport = { files: { 'src/app.js': { source, mutants: [] } } };

const survivor = (id: string, line: number, trace: Survivor['trace']): Survivor => ({
  mutant_id: id,
  file: 'src/app.js',
  location: { start: { line, column: 2 }, end: { line, column: 20 } },
  mutator: 'EqualityOperator',
  replacement: 'user.age <= 18',
  status: trace.signal === 'none' ? 'NoCoverage' : 'Survived',
  equivalent: false,
  trace,
});

// Mutant 1 links to both requirements; its code is about age. Mutant 2 links to one.
// Mutant 3 has no coverage; its code is about email login.
const survivors: Survivor[] = [
  survivor('1', 2, {
    test_ids: ['TST-A-001-01-01', 'TST-B-001-01-01'],
    scenario_ids: ['SCN-A-001-01', 'SCN-B-001-01'],
    requirement_ids: ['REQ-A-001', 'REQ-B-001'],
    signal: 'coverage',
    confidence: 0.5,
  }),
  survivor('2', 3, {
    test_ids: ['TST-A-001-01-01'],
    scenario_ids: ['SCN-A-001-01'],
    requirement_ids: ['REQ-A-001'],
    signal: 'coverage',
    confidence: 1,
  }),
  {
    ...survivor('3', 8, { test_ids: [], scenario_ids: [], requirement_ids: [], signal: 'none' }),
    replacement: '',
  },
];

const run = (mode: TraceSignalMode) => applyTraceSignal(survivors, mode, report, texts, fakeEmbed);

describe('c4 trace texts', () => {
  test('requirement text is the C2 text or the feature name, plus its scenario names', () => {
    expect(texts.requirements.get('REQ-A-001')).toBe(
      'Register: age from 18 to 65.\nRegister with a valid age\nReject a short password',
    );
    expect(texts.requirements.get('REQ-B-001')).toBe('Email login\nLogin with email');
  });

  test('mutant text has 2 lines of context and the replacement', () => {
    expect(mutantText(survivors[1], source)).toBe(
      [...source.split('\n').slice(0, 5), 'EqualityOperator -> user.age <= 18'].join('\n'),
    );
  });
});

describe('c4 applyTraceSignal', () => {
  test('coverage_only does not call the embedder', async () => {
    const never: Embedder = () => Promise.reject(new Error('called'));
    expect(await applyTraceSignal(survivors, 'coverage_only', report, texts, never)).toBe(
      survivors,
    );
  });

  test('embedding_assisted ranks a tie and keeps every requirement', async () => {
    const [tie, single, none] = await run('embedding_assisted');
    expect(tie.trace).toMatchObject({
      requirement_ids: ['REQ-A-001', 'REQ-B-001'],
      test_ids: survivors[0].trace.test_ids,
      signal: 'coverage+embedding',
    });
    expect(tie.trace.confidence).toBeGreaterThan(0.5);
    expect(single).toBe(survivors[1]);
    expect(none).toBe(survivors[2]);
  });

  test('the most similar requirement goes first, even when its ID sorts last', async () => {
    const swapped = {
      ...survivors[0],
      location: { start: { line: 8, column: 2 }, end: { line: 8, column: 20 } },
      replacement: '',
    };
    const [tie] = await applyTraceSignal([swapped], 'embedding_assisted', report, texts, fakeEmbed);
    expect(tie.trace.requirement_ids).toEqual(['REQ-B-001', 'REQ-A-001']);
  });

  test('full also traces a NoCoverage mutant to the closest requirement and scenario', async () => {
    const [tie, , none] = await run('full');
    expect(tie.trace.signal).toBe('coverage+embedding');
    expect(none.trace).toMatchObject({
      test_ids: [],
      scenario_ids: ['SCN-B-001-01'],
      requirement_ids: ['REQ-B-001'],
      signal: 'embedding',
    });
    expect(none.trace.confidence).toBeGreaterThan(0.5);
  });

  test('all 3 modes keep the same mutants, and coverage links are never dropped', async () => {
    const results = await Promise.all(
      (['coverage_only', 'embedding_assisted', 'full'] as const).map(run),
    );
    for (const r of results) {
      expect(r.map((s) => s.mutant_id)).toEqual(['1', '2', '3']);
      expect([...r[0].trace.requirement_ids].sort()).toEqual(survivors[0].trace.requirement_ids);
    }
    expect(results.map((r) => r.map((s) => s.trace.signal))).toEqual([
      ['coverage', 'coverage', 'none'],
      ['coverage+embedding', 'coverage', 'none'],
      ['coverage+embedding', 'coverage', 'embedding'],
    ]);
  });

  test('equal similarities give the coverage-only confidence 1/n', async () => {
    const flat: Embedder = async (t) => t.map(() => [1, 1]);
    const [tie] = await applyTraceSignal(survivors, 'embedding_assisted', report, texts, flat);
    expect(tie.trace.confidence).toBe(0.5);
    expect(tie.trace.requirement_ids).toEqual(['REQ-A-001', 'REQ-B-001']);
  });
});
