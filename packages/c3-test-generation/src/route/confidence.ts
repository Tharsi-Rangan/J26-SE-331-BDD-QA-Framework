// C3-13 confidence formula + routing to runnable test or human stub (FR9, FR10, FR12, SO5).
// Confidence is a weighted formula over rule-based signals, NOT the model's own confidence (contract).
// Not calibrated yet (calibrated: false): the weights are a first guess; C3-14 / PP2 calibrate them against
// the expert labels (ECE).
//   confidence >= threshold -> runnable (its tests stay in c3/runnable_tests)
//   confidence <  threshold -> stub: test.todo in c3/test_stubs/<STB-ID>.stub.js, with the draft code and why
//   C2 did not fully verify the scenario -> skipped_not_verified (no test, no stub)
import type { C3Inputs, C3ScenarioInput } from '../input/types.js';
import type { ScenarioPlan } from '../assert/plan.js';
import type { BehaviourWorkFile } from '../mock/behaviour.js';
import type { MockDecisionsFile } from '../mock/decisions.js';
import type { VerificationWorkFile } from '../verify/verify.js';
import type { ManifestStub, WrittenFiles } from '../writer/jest-writer.js';

export const FORMULA_VERSION = '0.1.0';
// A clean test (all checks pass, ran without a broken-test error, no repair) scores 0.7 + 0.3 x semantic, so it
// needs semantic >= 0.34 to run; a repaired test needs semantic >= 0.67. Invented values or a category that
// contradicts the Then step therefore send a test to a stub even when it compiles and runs.
export const THRESHOLD = 0.8;
export const WEIGHTS = {
  all_deterministic_checks_pass: 0.3, // syntactic, referential, traceability pass for every test
  semantic_score: 0.3, // mean semantic score of its tests (C3-11)
  runs_clean: 0.1, // Jest ran every test without a broken-test error
  no_repair_needed: 0.1, // repair_rounds == 0
  c2_fully_verified: 0.1, // C2 verified the scenario
  mock_behaviour_from_model: 0.1, // every mock behaviour came from a checked model answer (or no mocks)
} as const;
export type SignalName = keyof typeof WEIGHTS;
export type Signals = Record<SignalName, number | boolean>;

export type Route = 'runnable' | 'stub' | 'skipped_not_verified';

export interface ReportScenario {
  scenario_id: string;
  requirement_id: string;
  signals: Signals;
  confidence: number;
  route: Route;
  reason: string;
  test_ids?: string[];
  stub_id?: string;
}

export interface ConfidenceReportFile {
  contract: 'c3.confidence-report';
  schema_version: '1.0.0';
  producer: { component: 'C3'; tool_version: string; model?: string };
  run_id: string;
  generated_at: string;
  upstream: { contract: string; path: string; schema_version: string }[];
  subject_id: string;
  formula: {
    version: string;
    weights: Record<string, number>;
    threshold: number;
    calibrated: boolean;
  };
  scenarios: ReportScenario[];
}

const round3 = (n: number) => Math.round(n * 1000) / 1000;

/** Weighted sum of the signals (booleans count as 0/1), rounded to 3 decimals. */
export function confidenceOf(s: Signals): number {
  let total = 0;
  for (const [k, w] of Object.entries(WEIGHTS)) {
    const v = s[k as SignalName];
    total += w * (typeof v === 'boolean' ? (v ? 1 : 0) : v);
  }
  return round3(total);
}

export const stubId = (scenarioId: string) => `STB-${scenarioId.slice(4)}`;

export interface RouteInputs {
  inputs: C3Inputs;
  plans: ScenarioPlan[];
  written: WrittenFiles;
  verification: VerificationWorkFile;
  repairRounds: ReadonlyMap<string, number>;
  mockFile: MockDecisionsFile;
  behaviour: BehaviourWorkFile;
}

/** Signals of one scenario from its tests (C3-10/11/12) and mock behaviour (C3-07). */
export function signalsFor(r: RouteInputs, sc: C3ScenarioInput): Signals {
  const tests = r.verification.tests.filter((t) => t.scenario_id === sc.scenarioId);
  const mocks = r.mockFile.decisions.filter(
    (d) => d.scenario_id === sc.scenarioId && d.decision === 'mock',
  );
  const fromModel = mocks.every(
    (d) => r.behaviour.records.find((b) => b.decision_id === d.decision_id)?.source === 'model',
  );
  if (!tests.length)
    return {
      all_deterministic_checks_pass: false,
      semantic_score: 0,
      runs_clean: false,
      no_repair_needed: (r.repairRounds.get(sc.scenarioId) ?? 0) === 0,
      c2_fully_verified: sc.metadata.verification.fully_verified,
      mock_behaviour_from_model: fromModel,
    };
  return {
    all_deterministic_checks_pass: tests.every(
      (t) => t.syntactic === 'pass' && t.referential === 'pass' && t.traceability === 'pass',
    ),
    semantic_score: round3(tests.reduce((n, t) => n + t.semantic.score, 0) / tests.length),
    runs_clean:
      r.verification.subject_run &&
      tests.every((t) => t.run !== 'test_error' && t.run !== 'suite_error' && t.run !== 'not_run'),
    no_repair_needed: (r.repairRounds.get(sc.scenarioId) ?? 0) === 0,
    c2_fully_verified: sc.metadata.verification.fully_verified,
    mock_behaviour_from_model: fromModel,
  };
}

const LABELS: Record<SignalName, string> = {
  all_deterministic_checks_pass: 'a deterministic check failed',
  semantic_score: 'low semantic score',
  runs_clean: 'tests did not run cleanly',
  no_repair_needed: 'needed repair',
  c2_fully_verified: 'not fully verified by C2',
  mock_behaviour_from_model: 'a mock behaviour is only the rule default',
};

function weakSignals(s: Signals): string[] {
  return (Object.keys(WEIGHTS) as SignalName[])
    .filter((k) => (typeof s[k] === 'boolean' ? !s[k] : (s[k] as number) < 0.5))
    .map((k) => (k === 'semantic_score' ? `${LABELS[k]} (${s[k]})` : LABELS[k]));
}

/** Route every scenario C3 received, with a reason. */
export function routeScenarios(r: RouteInputs): ReportScenario[] {
  const out: ReportScenario[] = [];
  const planOf = new Map(r.plans.map((p) => [p.scenario_id, p]));
  for (const sc of r.inputs.scenarios) {
    const plan = planOf.get(sc.scenarioId);
    const signals = signalsFor(r, sc);
    const tests = r.written.manifest.tests.filter((t) => t.scenario_id === sc.scenarioId);
    const base = { scenario_id: sc.scenarioId, requirement_id: sc.requirementId, signals };
    if (!plan || plan.source !== 'model' || !tests.length) {
      const why = plan?.problems.at(-1) ?? 'no assertion plan';
      out.push({
        ...base,
        confidence: Math.min(confidenceOf(signals), round3(THRESHOLD - 0.001)),
        route: 'stub',
        reason: `No runnable test: ${why}`.slice(0, 400),
        stub_id: stubId(sc.scenarioId),
      });
      continue;
    }
    const confidence = confidenceOf(signals);
    const v = r.verification.tests.filter((t) => t.scenario_id === sc.scenarioId);
    const failing = v.filter((t) => t.run === 'assertion_failed' || t.run === 'subject_error');
    const note = failing.length
      ? ` ${failing.length} test(s) fail on this subject version (possible bug found; check on the fixed version): ${failing.map((t) => t.test_id).join(', ')}.`
      : '';
    if (confidence >= THRESHOLD) {
      const weak = weakSignals(signals);
      out.push({
        ...base,
        confidence,
        route: 'runnable',
        reason:
          (weak.length
            ? `Confidence ${confidence} >= ${THRESHOLD} despite: ${weak.join('; ')}.`
            : `All checks passed${signals.no_repair_needed ? ' first time' : ''}; semantic score ${signals.semantic_score}.`) +
          note,
        test_ids: tests.map((t) => t.test_id),
      });
    } else {
      out.push({
        ...base,
        confidence,
        route: 'stub',
        reason: `Confidence ${confidence} < ${THRESHOLD}: ${weakSignals(signals).join('; ') || 'low signals'}.${note}`,
        stub_id: stubId(sc.scenarioId),
      });
    }
  }
  for (const s of r.inputs.skipped)
    out.push({
      scenario_id: s.scenarioId,
      requirement_id: s.requirementId,
      signals: { c2_fully_verified: false } as Signals,
      confidence: 0,
      route: 'skipped_not_verified',
      reason: `Skipped: ${s.reason}.`,
    });
  return out;
}

/** c3/test_stubs/<STB-ID>.stub.js: a test.todo with the steps, the reason and the draft code for a human. */
export function stubFile(sc: C3ScenarioInput, reason: string, draft?: string): string {
  const title = `[${sc.scenarioId}][${stubId(sc.scenarioId)}] ${sc.scenarioName} :: ${reason.split('\n')[0]!.slice(0, 160)}`;
  const comment = (s: string) => s.split('\n').map((l) => `//   ${l}`.trimEnd());
  return [
    `// @requirement ${sc.requirementId}`,
    `// Stub written by C3: a human should write or fix this test. It never fails CI (test.todo).`,
    `// Why: ${reason.split('\n')[0]}`,
    `// Scenario: ${sc.scenarioName}`,
    ...comment(sc.steps.map((s) => `${s.keyword} ${s.text}`).join('\n')),
    ...(draft ? ['// Draft from C3 (not trusted enough to run):', ...comment(draft)] : []),
    `test.todo(${JSON.stringify(title)});`,
    '',
  ].join('\n');
}

export function stubEntry(sc: C3ScenarioInput, reason: string): ManifestStub {
  return {
    stub_id: stubId(sc.scenarioId),
    scenario_id: sc.scenarioId,
    requirement_id: sc.requirementId,
    file: `c3/test_stubs/${stubId(sc.scenarioId)}.stub.js`,
    reason: reason.slice(0, 400),
  };
}

export function confidenceReport(
  r: RouteInputs,
  scenarios: ReportScenario[],
  meta: { generatedAt?: string; toolVersion?: string; model?: string },
): ConfidenceReportFile {
  const subjects = [...new Set(r.inputs.scenarios.map((s) => s.subject.subjectId))];
  return {
    contract: 'c3.confidence-report',
    schema_version: '1.0.0',
    producer: {
      component: 'C3',
      tool_version: meta.toolVersion ?? '0.1.0',
      ...(meta.model ? { model: meta.model } : {}),
    },
    run_id: r.inputs.runId,
    generated_at: meta.generatedAt ?? new Date().toISOString(),
    upstream: [
      {
        contract: 'c2.scenario-metadata',
        path: 'c2/scenario_metadata.json',
        schema_version: '1.0.0',
      },
      { contract: 'c3.test-manifest', path: 'c3/test_manifest.json', schema_version: '1.0.0' },
    ],
    subject_id: subjects[0] ?? 'SUB-NONE',
    formula: {
      version: FORMULA_VERSION,
      weights: { ...WEIGHTS },
      threshold: THRESHOLD,
      calibrated: false,
    },
    scenarios,
  };
}
