import fs from 'node:fs';
import path from 'node:path';
import type { RunOptions, ScanCommandOptions } from './args.js';
import { readC3Inputs } from './input/reader.js';
import type { C3Inputs } from './input/types.js';
import {
  defaultBehaviourWork,
  deriveMockBehaviours,
  type BehaviourWorkFile,
} from './mock/behaviour.js';
import { buildMockDecisions, type MockDecision } from './mock/decisions.js';
import { planAssertions, planContext } from './assert/plan.js';
import { chooseStrategies } from './strategy.js';
import { TEST_ROOT, writeJestTests } from './writer/jest-writer.js';
import { createModelClient, readModelConfig, type ModelClient } from './model/index.js';
import { scanModule } from './scan/scanner.js';
import type { ModuleScan } from './scan/types.js';

export type { RunOptions, ScanCommandOptions } from './args.js';
export { readC3Inputs, C3InputError } from './input/reader.js';
export type * from './input/types.js';
export { scanModule, classifySpecifier } from './scan/scanner.js';
export type * from './scan/types.js';
export { buildMockDecisions, chooseTargetExports } from './mock/decisions.js';
export type { MockDecision, MockDecisionsFile, TargetChoice } from './mock/decisions.js';
export { RULES, RULES_VERSION, decide } from './mock/rules.js';
export {
  BEHAVIOUR_KINDS,
  BEHAVIOUR_PROMPT_VERSION,
  behaviourPrompt,
  behaviourToJest,
  checkAnswer,
  defaultBehaviourWork,
  defaultStructured,
  deriveMockBehaviours,
  usesResult,
} from './mock/behaviour.js';
export type {
  BehaviourKind,
  BehaviourRecord,
  BehaviourWorkFile,
  StructuredBehaviour,
} from './mock/behaviour.js';
export * from './model/index.js';
export {
  ASSERTION_CATEGORIES,
  ASSERTION_PROMPT_VERSION,
  assertionPrompt,
  buildCases,
  checkAssertionAnswer,
  mockLocalName,
  mockTarget,
  planAssertions,
  planContext,
  planScenario,
  ruleCategories,
  ruleCategory,
} from './assert/plan.js';
export type {
  AssertionCategory,
  AssertionSlot,
  AssertionWorkFile,
  PlanCase,
  PlanContext,
  ScenarioPlan,
} from './assert/plan.js';
export { renderCase, TEMPLATE_NOTES } from './assert/templates.js';
export { chooseStrategies, chooseStrategy, STRATEGY_RULES_VERSION } from './strategy.js';
export type { Strategy, StrategyChoice } from './strategy.js';
export {
  caseLabel,
  JEST_CONFIG,
  jestConfig,
  rowValue,
  TEST_ROOT,
  testId,
  writeJestTests,
} from './writer/jest-writer.js';
export type { ManifestTest, TestManifestFile, WrittenFiles } from './writer/jest-writer.js';
export { makeSandbox, removeSandbox, runJest } from './runner/jest.js';
export type { JestRunResult, JestTestResult } from './runner/jest.js';
export { checkExpression, paramName, renderValue, replacePlaceholders } from './assert/expr.js';

/** C3's version, written as producer.tool_version in every contract file. */
export const TOOL_VERSION: string = JSON.parse(
  fs.readFileSync(new URL('../package.json', import.meta.url), 'utf8'),
).version;

/** Internal (non-contract) work files go here, next to the contract files in <out>/c3/. */
export const WORK_DIR = 'c3/work';

/**
 * Runnable Test Generation with Explainable Assertions and Mocking.
 * Done so far: C3-03 input reader, C3-04 dependency scan, C3-05 rule-based mock decisions,
 * C3-06 model client, C3-07 mock behaviour from the Given/When steps, C3-08 typed assertions,
 * C3-09 strategy selection, C3-10 Jest writer + test_manifest.json.
 */
export async function run(
  options: RunOptions & { generatedAt?: string; model?: ModelClient },
): Promise<void> {
  if (!options.in) throw new Error('Missing --in <run folder>');
  const inputs = readC3Inputs(options.in);
  console.log(
    `[c3] run ${inputs.runId}: ${inputs.scenarios.length} scenario(s) to build, ${inputs.skipped.length} skipped`,
  );
  for (const s of inputs.scenarios) {
    const rows = s.isOutline ? `, ${s.examples.length} example rows` : '';
    console.log(
      `  ${s.scenarioId} [${s.scenarioType}] ${s.subject.subjectId}:${s.subject.modulePath}${rows}`,
    );
  }
  for (const s of inputs.skipped) console.log(`  skip ${s.scenarioId}: ${s.reason}`);

  const scans = scanSubjects(inputs, options.subjectRoot);
  if (scans.length) {
    const file = path.join(options.out, WORK_DIR, 'dependency_scan.json');
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify(scans, null, 2) + '\n');
    for (const s of scans) printScan(s.scan, `${s.subjectId}:`);
    console.log(`[c3] dependency scan written to ${file}`);
  }

  // C3-05: rule-based mock / no_mock decisions -> c3/mock_decisions.json (contract file)
  if (scans.length && inputs.scenarios.length) {
    const index = new Map(scans.map((s) => [`${s.subjectId}|${s.modulePath}`, s.scan]));
    const built = buildMockDecisions(inputs, index, {
      generatedAt: options.generatedAt,
      toolVersion: TOOL_VERSION,
    });
    const { targets } = built;
    let file = built.file;

    // C3-07: the model fills the behaviour of each 'mock' decision from the Given/When steps.
    let work: BehaviourWorkFile;
    if (options.model && file.decisions.some((d) => d.decision === 'mock')) {
      console.log(`[c3] mock behaviour (C3-07) with ${options.model.modelTag}:`);
      const derived = await deriveMockBehaviours(file, inputs, options.model, {
        targets,
        callSites: callSitesFrom(scans),
        log: (l) => console.log(l),
      });
      file = derived.file;
      work = derived.work;
    } else {
      work = defaultBehaviourWork(file);
    }
    writeJson(path.join(options.out, WORK_DIR, 'mock_behaviour.json'), work);

    const out = path.join(options.out, 'c3', 'mock_decisions.json');
    writeJson(out, file);
    console.log(`[c3] mock decisions (rules ${file.rules_version}):`);
    for (const sc of inputs.scenarios) {
      console.log(`  ${sc.scenarioId} tests ${targets.get(sc.scenarioId)?.exports.join(', ')}`);
      for (const d of file.decisions.filter((x) => x.scenario_id === sc.scenarioId)) {
        const dep = `${d.dependency.import_specifier}#${d.dependency.symbol}`;
        console.log(`    ${d.decision_id} ${d.decision.padEnd(7)} ${d.rule_id} ${dep}`);
        if (d.behaviour) console.log(`      behaviour: ${d.behaviour.summary}`);
      }
    }
    console.log(`[c3] mock decisions written to ${out}`);

    // C3-08: typed assertions (one model call per scenario) -> c3/work/assertion_plan.json
    const contexts = inputs.scenarios.map((sc) => {
      const scan = index.get(`${sc.subject.subjectId}|${sc.subject.modulePath}`)!;
      return planContext(sc, scan.exports, targets.get(sc.scenarioId)?.exports ?? [], file, work);
    });
    console.log(
      `[c3] assertions (C3-08)${options.model ? ` with ${options.model.modelTag}` : ': no model, so no scenario can be planned'}:`,
    );
    const plans = await planAssertions(contexts, options.model, { log: (l) => console.log(l) });
    writeJson(path.join(options.out, WORK_DIR, 'assertion_plan.json'), plans);

    // C3-09: test strategy per scenario (rules) -> c3/work/strategy.json
    const strategies = chooseStrategies(inputs.scenarios);
    writeJson(path.join(options.out, WORK_DIR, 'strategy.json'), strategies);
    console.log(`[c3] strategy (rules ${strategies.rules_version}):`);
    for (const c of strategies.choices)
      console.log(`  ${c.scenario_id} ${c.strategy} (${c.rule_id}): ${c.reason}`);

    // C3-10: Jest files (one per requirement) + c3/test_manifest.json (contract file)
    const written = writeJestTests({
      inputs,
      plans,
      strategies: strategies.choices,
      mockFile: file,
      behaviour: work,
      exports: new Map(scans.map((x) => [x.modulePath, x.scan.exports])),
      generatedAt: options.generatedAt,
      toolVersion: TOOL_VERSION,
    });
    for (const dir of [TEST_ROOT, 'c3/test_stubs'])
      fs.rmSync(path.join(options.out, dir), { recursive: true, force: true });
    for (const [rel, content] of written.files) {
      const f = path.join(options.out, rel);
      fs.mkdirSync(path.dirname(f), { recursive: true });
      fs.writeFileSync(f, content);
    }
    writeJson(path.join(options.out, 'c3', 'test_manifest.json'), written.manifest);
    console.log(
      `[c3] Jest tests (C3-10): ${written.manifest.tests.length} test(s) in ${written.files.size - 1} file(s); ${written.notWritten.length} scenario(s) without a runnable test`,
    );
    for (const f of [...written.files.keys()].filter((k) => k.startsWith(TEST_ROOT)))
      console.log(`  ${f}`);
    for (const n of written.notWritten) console.log(`  no test for ${n.scenario_id}: ${n.reason}`);
  }
}

/** For C3-07: the source lines of the module under test that use a decision's dependency. */
export function callSitesFrom(scans: SubjectScan[]): (d: MockDecision) => string[] {
  const sources = new Map<string, string[]>();
  return (d) => {
    const s = scans.find((x) => x.modulePath === d.module_path);
    if (!s) return [];
    const dep = s.scan.dependencies.find(
      (x) =>
        x.importSpecifier === d.dependency.import_specifier && x.symbol === d.dependency.symbol,
    );
    if (!dep) return [];
    const file = path.join(s.scan.subjectRoot, s.scan.modulePath);
    if (!sources.has(file)) sources.set(file, fs.readFileSync(file, 'utf8').split(/\r?\n/));
    const lines = sources.get(file)!;
    return dep.lines
      .slice(0, 5)
      .map((n) => lines[n - 1] ?? '')
      .filter((l) => l.trim());
  };
}

function writeJson(file: string, data: unknown): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(data, null, 2) + '\n');
}

export interface SubjectScan {
  subjectId: string;
  modulePath: string;
  scan: ModuleScan;
}

/**
 * C3-04: scan the module of every subject that has a scenario to build.
 * Subject folder = --subject-root, or the manifest's source.repo_path inside the run folder (golden fixtures).
 */
export function scanSubjects(inputs: C3Inputs, subjectRoot?: string): SubjectScan[] {
  const out: SubjectScan[] = [];
  const seen = new Set<string>();
  for (const sc of inputs.scenarios) {
    const subject = sc.subject;
    const id = `${subject.subjectId}|${subject.modulePath}`;
    if (seen.has(id)) continue;
    seen.add(id);
    const repoPath = subject.source['repo_path'];
    const root =
      subjectRoot ?? (typeof repoPath === 'string' ? path.join(inputs.inDir, repoPath) : undefined);
    if (!root) {
      console.log(
        `  scan skipped for ${subject.subjectId}: pass --subject-root <checked-out subject>`,
      );
      continue;
    }
    out.push({
      subjectId: subject.subjectId,
      modulePath: subject.modulePath,
      scan: scanModule(root, subject.modulePath, { expectedExports: subject.exports }),
    });
  }
  return out;
}

/** `c3 scan`: scan one module and print a summary (and save the full JSON with --out). */
export function scanCommand(options: ScanCommandOptions): ModuleScan {
  const scan = scanModule(options.subjectRoot, options.module, {
    expectedExports: options.exports,
  });
  printScan(scan, '');
  if (options.out) {
    fs.mkdirSync(path.dirname(options.out), { recursive: true });
    fs.writeFileSync(options.out, JSON.stringify(scan, null, 2) + '\n');
    console.log(`[c3] scan written to ${options.out}`);
  }
  return scan;
}

function printScan(scan: ModuleScan, prefix: string): void {
  console.log(
    `[c3] scan ${prefix}${scan.modulePath}: ${scan.imports.length} import(s), ${scan.dependencies.length} used dependency symbol(s)`,
  );
  for (const d of scan.dependencies) {
    const where = d.resolvedPath ? ` -> ${d.resolvedPath}` : '';
    console.log(`  dep  ${d.key} [${d.kind}]${where} lines ${d.lines.join(',')}`);
  }
  for (const e of scan.exports) {
    console.log(
      `  export ${e.name}: ${e.dependencies.length ? e.dependencies.join(', ') : '(none)'}`,
    );
  }
  if (scan.moduleLoadDependencies.length) {
    console.log(`  on require(): ${scan.moduleLoadDependencies.join(', ')}`);
  }
  for (const w of scan.warnings) console.log(`  warning: ${w}`);
}

/**
 * `c3 model-check` (C3-06 / SH-07 evidence): one tiny call to the model in .env, cache off,
 * so you see the real server, the model tag and how long it took.
 */
export async function modelCheck(client?: ModelClient): Promise<string> {
  const config = readModelConfig();
  const c = client ?? createModelClient({ ...config, cacheMode: 'off' });
  console.log(`[c3] model-check: ${c.modelTag} at ${config.baseUrl}`);
  const res = await c.complete({
    messages: [{ role: 'user', content: 'Reply with exactly the word OK.' }],
    maxTokens: 5,
    purpose: 'model-check',
  });
  console.log(
    `[c3] answer "${res.text.trim()}" from ${res.model} via ${res.provider} in ${res.latencyMs} ms`,
  );
  return res.text;
}
