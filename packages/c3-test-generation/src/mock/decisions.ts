// C3-05 mock decisions -> c3/mock_decisions.json (FR3, SO1, NFR4 determinism).
// One decision per (scenario, dependency) pair. The decision + rule_id + reason come from rules.ts.
// For 'mock' decisions a DEFAULT behaviour is written here, because the contract requires one;
// C3-07 replaces it with behaviour derived from the scenario's Given/When steps.
import { pathWords, type SideEffect } from '../scan/side-effects.js';
import type { ModuleScan, ScannedDependency } from '../scan/types.js';
import type { C3Inputs, C3ScenarioInput } from '../input/types.js';
import { decide, RULES_VERSION } from './rules.js';

/** One entry of mock_decisions.json (field names exactly as in c3-mock-decisions.schema.json). */
export interface MockDecision {
  decision_id: string;
  scenario_id: string;
  module_path: string;
  dependency: {
    import_specifier: string;
    symbol: string;
    kind: ScannedDependency['kind'];
    resolved_path?: string;
    type_signature?: string;
    side_effect: SideEffect;
  };
  decision: 'mock' | 'no_mock';
  rule_id: string;
  reason: string;
  behaviour?: {
    derived_from_steps: string[];
    summary: string;
    rationale: string;
    model?: string;
  } | null;
}

export interface MockDecisionsFile {
  contract: 'c3.mock-decisions';
  schema_version: '1.0.0';
  producer: { component: 'C3'; tool_version: string };
  run_id: string;
  generated_at: string;
  upstream: { contract: string; path: string; schema_version: string }[];
  subject_id: string;
  rules_version: string;
  decisions: MockDecision[];
}

/** Which exported function(s) a scenario tests, and why. */
export interface TargetChoice {
  exports: string[];
  basis: string;
}

/**
 * Pick the export(s) a scenario is about.
 * Manifest exports that the scan found are the candidates. One candidate -> that one. Otherwise the
 * candidates whose name (or all of its camelCase words) appears in the scenario name or steps.
 * No match -> all candidates (safe: more dependencies are decided, none are missed).
 */
export function chooseTargetExports(scenario: C3ScenarioInput, scan: ModuleScan): TargetChoice {
  const found = new Set(scan.exports.map((e) => e.name));
  const listed = scenario.subject.exports.filter((e) => found.has(e));
  const candidates = listed.length ? listed : scan.exports.map((e) => e.name);
  if (candidates.length === 1) {
    return { exports: candidates, basis: `the only export in scope: ${candidates[0]}` };
  }
  const text = [scenario.scenarioName, ...scenario.steps.map((s) => s.text)]
    .join(' ')
    .toLowerCase();
  const squashed = text.replace(/[^a-z0-9]/g, '');
  const textWords = new Set(text.split(/[^a-z0-9]+/).filter(Boolean));
  const named = candidates.filter((name) => {
    const words = pathWords(name);
    return squashed.includes(name.toLowerCase()) || words.every((w) => hasWord(textWords, w));
  });
  if (named.length) {
    return { exports: named, basis: `named in the scenario text: ${named.join(', ')}` };
  }
  return {
    exports: candidates,
    basis: `no export named in the scenario; using all ${candidates.length} in scope`,
  };
}

/** 'load' matches 'load', 'loads', 'loaded', 'loading' (simple endings only, no dictionary). */
function hasWord(textWords: ReadonlySet<string>, w: string): boolean {
  if (textWords.has(w)) return true;
  for (const t of textWords) {
    if (t.startsWith(w) && /^(s|es|d|ed|ing)$/.test(t.slice(w.length))) return true;
  }
  return false;
}

export interface BuildOptions {
  generatedAt?: string; // ISO time; fixed in tests so the output can be compared byte for byte
  toolVersion?: string;
}

/** Scans of the subject modules, keyed by `${subjectId}|${modulePath}`. */
export type ScanIndex = ReadonlyMap<string, ModuleScan>;

/** Build mock_decisions.json for every scenario C3 builds. Same input -> same output. */
export function buildMockDecisions(
  inputs: C3Inputs,
  scans: ScanIndex,
  options: BuildOptions = {},
): { file: MockDecisionsFile; targets: Map<string, TargetChoice> } {
  const subjects = [...new Set(inputs.scenarios.map((s) => s.subject.subjectId))];
  if (subjects.length > 1) {
    throw new Error(
      `C3-05: one run folder must have one subject, found ${subjects.join(', ')} (mock_decisions.json has one subject_id)`,
    );
  }
  const decisions: MockDecision[] = [];
  const targets = new Map<string, TargetChoice>();

  for (const sc of inputs.scenarios) {
    const scan = scans.get(`${sc.subject.subjectId}|${sc.subject.modulePath}`);
    if (!scan) {
      throw new Error(
        `C3-05: no dependency scan for ${sc.subject.subjectId}:${sc.subject.modulePath} (pass --subject-root)`,
      );
    }
    const target = chooseTargetExports(sc, scan);
    targets.set(sc.scenarioId, target);
    const used = new Set(
      scan.exports.filter((e) => target.exports.includes(e.name)).flatMap((e) => e.dependencies),
    );
    const atLoad = new Set(scan.moduleLoadDependencies);

    for (const dep of scan.dependencies) {
      if (!used.has(dep.key) && !atLoad.has(dep.key)) continue; // the test never touches it
      const { rule, reason } = decide({
        dep,
        usedByTarget: used.has(dep.key),
        usedAtLoad: atLoad.has(dep.key),
      });
      decisions.push({
        decision_id: `MD-${String(decisions.length + 1).padStart(3, '0')}`,
        scenario_id: sc.scenarioId,
        module_path: scan.modulePath,
        dependency: {
          import_specifier: dep.importSpecifier,
          symbol: dep.symbol,
          kind: dep.kind,
          ...(dep.resolvedPath ? { resolved_path: dep.resolvedPath } : {}),
          ...(dep.typeSignature ? { type_signature: dep.typeSignature } : {}),
          side_effect: dep.sideEffect,
        },
        decision: rule.decision,
        rule_id: rule.id,
        reason,
        behaviour: rule.decision === 'mock' ? defaultBehaviour(sc, dep, rule.id) : null,
      });
    }
  }
  if (decisions.length > 999)
    throw new Error('C3-05: more than 999 decisions (MD-nnn is 3 digits)');

  return {
    file: {
      contract: 'c3.mock-decisions',
      schema_version: '1.0.0',
      producer: { component: 'C3', tool_version: options.toolVersion ?? '0.1.0' },
      run_id: inputs.runId,
      generated_at: options.generatedAt ?? new Date().toISOString(),
      upstream: [
        {
          contract: 'c2.scenario-metadata',
          path: 'c2/scenario_metadata.json',
          schema_version: '1.0.0',
        },
      ],
      subject_id: subjects[0] ?? inputs.scenarios[0]?.subject.subjectId ?? 'SUB-NONE',
      rules_version: RULES_VERSION,
      decisions,
    },
    targets,
  };
}

const DEFAULT_SUMMARY: Record<SideEffect, (fn: string) => string> = {
  database: (fn) => `${fn} is a jest mock that succeeds and returns the value it was given.`,
  network: (fn) =>
    `${fn} is a jest mock that returns a fixed successful response; no request is sent.`,
  io: (fn) => `${fn} is a jest mock that returns fixed data; no real file or process is touched.`,
  time: (fn) => `${fn} returns a fixed time (Jest fake timers), so every run sees the same clock.`,
  random: (fn) => `${fn} returns a fixed value (0.5), so every run gets the same number.`,
  none: (fn) => `${fn} is a jest mock with its default return value.`,
  unknown: (fn) => `${fn} is a jest mock with its default return value.`,
};

/** Rule-based placeholder behaviour (no model). C3-07 replaces summary/rationale using the steps. */
function defaultBehaviour(
  sc: C3ScenarioInput,
  dep: ScannedDependency,
  ruleId: string,
): NonNullable<MockDecision['behaviour']> {
  const fn = dep.symbol === 'default' ? `'${dep.importSpecifier}'` : `${dep.symbol}()`;
  const depWords = new Set([...pathWords(dep.importSpecifier), ...pathWords(dep.symbol)]);
  const setup = sc.steps.filter((s) => s.keyword !== 'Then');
  const related = setup.filter((s) =>
    s.text
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .some((w) => w.length > 2 && depWords.has(w)),
  );
  const steps = (related.length ? related : setup.filter((s) => s.keyword === 'Given')).map(
    (s) => `${s.keyword} ${s.text}`,
  );
  return {
    derived_from_steps: steps,
    summary: DEFAULT_SUMMARY[dep.sideEffect](fn),
    rationale: `Default for rule ${ruleId} (no model used). C3-07 replaces it with behaviour derived from the Given/When steps.`,
  };
}
