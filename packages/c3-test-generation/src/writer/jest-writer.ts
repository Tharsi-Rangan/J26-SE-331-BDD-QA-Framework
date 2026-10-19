// C3-10 Jest test writer + test_manifest.json (FR11).
// One file per requirement: c3/runnable_tests/<REQ>.test.js, one top-level describe('[REQ-...] <feature>'),
// test titles '[SCN-...][TST-...] <scenario> :: <case>' (packages/contracts/conventions/jest-tests.md).
// Outlines become test.each; rows whose assertions render to the same code share one test.each.
// Every test sets up its own mocks (behaviour from C3-07), so scenarios never share mock state.
// The manifest records each test's exact Jest full name, so C4 can map StrykerJS per-test coverage to IDs.
import { BEHAVIOUR_KINDS, behaviourToJest, type BehaviourWorkFile } from '../mock/behaviour.js';
import type { MockDecision, MockDecisionsFile } from '../mock/decisions.js';
import type { C3Inputs, C3ScenarioInput } from '../input/types.js';
import type { AssertionWorkFile, PlanCase, ScenarioPlan } from '../assert/plan.js';
import { mockLocalName, mockTarget } from '../assert/plan.js';
import { renderCase } from '../assert/templates.js';
import { checkExpression } from '../assert/expr.js';
import type { ScannedExport } from '../scan/types.js';
import type { StrategyChoice } from '../strategy.js';

export const TEST_ROOT = 'c3/runnable_tests';
export const JEST_CONFIG = 'c3/jest.config.cjs';
export const JEST_VERSION = '29.7.0';

export type CheckStatus = 'pass' | 'fail' | 'skipped';

export interface ManifestTest {
  test_id: string;
  scenario_id: string;
  requirement_id: string;
  file: string;
  jest_full_name: string;
  examples_row?: number;
  boundary_ref?: string;
  partition_ref?: string;
  strategy: StrategyChoice['strategy'];
  assertion_categories: string[];
  mock_decision_ids?: string[];
  verification: {
    syntactic: CheckStatus;
    referential: CheckStatus;
    traceability: CheckStatus;
    semantic: { status: CheckStatus; score?: number };
  };
  repair_rounds: number;
}

export interface ManifestStub {
  stub_id: string;
  scenario_id: string;
  requirement_id: string;
  file: string;
  reason: string;
}

export interface TestManifestFile {
  contract: 'c3.test-manifest';
  schema_version: '1.0.0';
  producer: { component: 'C3'; tool_version: string; model?: string };
  run_id: string;
  generated_at: string;
  upstream: { contract: string; path: string; schema_version: string }[];
  subject_id: string;
  runner: { name: 'jest'; version: string; config_path: string; test_root: string };
  tests: ManifestTest[];
  stubs: ManifestStub[];
}

export interface WriterInputs {
  inputs: C3Inputs;
  plans: AssertionWorkFile;
  strategies: StrategyChoice[];
  mockFile: MockDecisionsFile;
  behaviour: BehaviourWorkFile;
  /** Scanned exports of each subject module, keyed by module_path. */
  exports: ReadonlyMap<string, ScannedExport[]>;
  generatedAt?: string;
  toolVersion?: string;
}

export interface WrittenFiles {
  /** Path relative to the run folder -> file content. */
  files: Map<string, string>;
  manifest: TestManifestFile;
  /** Scenarios with no runnable test, and why (C3-13 makes stubs for them). */
  notWritten: { scenario_id: string; requirement_id: string; reason: string }[];
  /** C3-11: what each test file requires (checked by the referential layer). */
  requires: Map<string, FileRequires>;
}

/** The require() lines of one test file, relative to the subject root where they point into the subject. */
export interface FileRequires {
  repoPath: string;
  /** The module under test, relative to the subject root (e.g. 'src/registration.js'). */
  module: string;
  /** Export names the file takes from it. */
  names: string[];
  /** Mocked modules: subject-relative path for internal ones, else the package/builtin name. */
  mocks: { specifier: string; subjectPath?: string; kind: string }[];
}

/** TST id for one case: TST-<scenario part>-<rr> (rr = Examples row, or 01). */
export function testId(scenarioId: string, row?: number): string {
  return `TST-${scenarioId.slice(4)}-${String(row ?? 1).padStart(2, '0')}`;
}

/** Cell text -> JS value: the metadata's typed value when C2 gave one (C2 values used as-is). */
export function rowValue(
  sc: C3ScenarioInput,
  row: number,
  column: string,
  quoted: boolean,
): unknown {
  const cell = sc.examples.find((r) => r.rowIndex === row)?.values[column] ?? '';
  if (quoted) return cell;
  const meta = sc.metadata.examples?.find((r) => r.row_index === row)?.values?.[column];
  if (meta !== undefined) return meta;
  if (/^-?\d+(\.\d+)?$/.test(cell)) return Number(cell);
  if (cell === 'true' || cell === 'false') return cell === 'true';
  if (cell === 'null') return null;
  return cell;
}

/** Case label after '::' in the test title. */
export function caseLabel(sc: C3ScenarioInput, row?: number): string {
  if (row !== undefined) {
    const r = sc.examples.find((x) => x.rowIndex === row);
    return Object.entries(r?.values ?? {})
      .map(([k, v]) => `${k}=${v}`)
      .join(', ');
  }
  const when = sc.steps.filter((s) => s.keyword === 'When').map((s) => s.text);
  return (
    when.length ? when : sc.steps.filter((s) => s.keyword === 'Given').map((s) => s.text)
  ).join('; ');
}

const q = (s: string) => JSON.stringify(s);
const printfSafe = (s: string) => s.replace(/%/g, '%%');
const indent = (lines: string[], n: number) => lines.map((l) => (l ? ' '.repeat(n) + l : l));

/** require() path from c3/runnable_tests/ to a file of the subject (no extension). */
function subjectPath(repoPath: string, rel: string): string {
  return `../../${repoPath}/${rel.replace(/\.(c|m)?js$/, '')}`;
}

/** Jest setup lines for the mocks of one scenario (reset, then the C3-07 behaviour). */
function mockSetup(decisions: MockDecision[], behaviour: BehaviourWorkFile): string[] {
  const lines: string[] = [];
  for (const d of decisions) {
    const rec = behaviour.records.find((r) => r.decision_id === d.decision_id);
    const kind =
      rec?.kind && (BEHAVIOUR_KINDS as readonly string[]).includes(rec.kind) ? rec.kind : undefined;
    if (d.dependency.kind === 'global_object') {
      const target = `jest.spyOn(${d.dependency.import_specifier}, ${q(d.dependency.symbol)})`;
      lines.push(
        kind
          ? behaviourToJest(target, {
              kind,
              value: rec!.value,
              error_message: rec!.error_message,
              async: rec!.async,
            })
          : `${target};`,
      );
      continue;
    }
    const target = mockTarget(d.dependency);
    lines.push(`${target}.mockReset();`);
    if (kind)
      lines.push(
        ...behaviourToJest(target, {
          kind,
          value: rec!.value,
          error_message: rec!.error_message,
          async: rec!.async,
        }).split('\n'),
      );
  }
  return lines;
}

/** Export names a plan's code uses (for the require line). */
function usedExports(plan: ScenarioPlan, names: Set<string>): string[] {
  const used = new Set<string>();
  const ids = checkExpression(plan.act_code ?? '', new Set(names)).identifiers;
  for (const id of ids) if (names.has(id)) used.add(id);
  for (const a of plan.assertions) if (a.error && names.has(a.error)) used.add(a.error);
  return [...used];
}

/** Build every runnable test file and test_manifest.json (no files are written to disk here). */
export function writeJestTests(w: WriterInputs): WrittenFiles {
  const { inputs } = w;
  const planOf = new Map(w.plans.plans.map((p) => [p.scenario_id, p]));
  const strategyOf = new Map(w.strategies.map((s) => [s.scenario_id, s]));
  const files = new Map<string, string>();
  const tests: ManifestTest[] = [];
  const notWritten: WrittenFiles['notWritten'] = [];
  const requires = new Map<string, FileRequires>();

  const byReq = new Map<string, C3ScenarioInput[]>();
  for (const sc of inputs.scenarios) {
    const plan = planOf.get(sc.scenarioId);
    if (!plan || plan.source !== 'model' || !plan.act_code || !plan.cases.length) {
      notWritten.push({
        scenario_id: sc.scenarioId,
        requirement_id: sc.requirementId,
        reason: plan?.problems.length
          ? `no usable assertion plan (${plan.problems.at(-1)})`
          : 'no usable assertion plan',
      });
      continue;
    }
    byReq.set(sc.requirementId, [...(byReq.get(sc.requirementId) ?? []), sc]);
  }

  for (const [req, scenarios] of [...byReq].sort(([a], [b]) => a.localeCompare(b))) {
    const sc0 = scenarios[0]!;
    const subject = sc0.subject;
    const repoPath =
      typeof subject.source['repo_path'] === 'string'
        ? (subject.source['repo_path'] as string)
        : 'subject-src';
    const exportsList = w.exports.get(subject.modulePath) ?? [];
    const names = new Set(exportsList.map((e) => e.name));
    const file = `${TEST_ROOT}/${req}.test.js`;
    const describe = `[${req}] ${sc0.featureName}`;

    // requires: mocked modules (jest.mock is hoisted by Jest), then the module under test
    const decisionsOf = (scId: string) =>
      w.mockFile.decisions.filter((d) => d.scenario_id === scId && d.decision === 'mock');
    const mocked = new Map<string, string>(); // jest.mock path -> local name
    for (const sc of scenarios)
      for (const d of decisionsOf(sc.scenarioId)) {
        if (d.dependency.kind === 'global_object') continue;
        const p =
          d.dependency.kind === 'internal_module' && d.dependency.resolved_path
            ? subjectPath(repoPath, d.dependency.resolved_path)
            : d.dependency.import_specifier;
        mocked.set(p, mockLocalName(d.dependency.import_specifier));
      }
    const used = new Set(scenarios.flatMap((sc) => usedExports(planOf.get(sc.scenarioId)!, names)));
    const moduleStyle = exportsList.find((e) => e.style === 'module' && used.has(e.name));
    const named = [...used].filter((n) => n !== moduleStyle?.name).sort();
    const modPath = subjectPath(repoPath, subject.modulePath);
    const head = [
      `// @requirement ${req}`,
      `// Generated by C3 ${w.toolVersion ?? '0.1.0'} (run ${inputs.runId}). Do not edit: C3 writes this file again.`,
      ...[...mocked.keys()].map((p) => `jest.mock(${q(p)});`),
      ...[...mocked].map(([p, local]) => `const ${local} = require(${q(p)});`),
      ...(moduleStyle ? [`const ${moduleStyle.name} = require(${q(modPath)});`] : []),
      ...(named.length
        ? [
            moduleStyle
              ? `const { ${named.join(', ')} } = ${moduleStyle.name};`
              : `const { ${named.join(', ')} } = require(${q(modPath)});`,
          ]
        : []),
    ];
    const hasSpies = scenarios.some((sc) =>
      decisionsOf(sc.scenarioId).some((d) => d.dependency.kind === 'global_object'),
    );

    const blocks: string[][] = [];
    for (const sc of scenarios) {
      const plan = planOf.get(sc.scenarioId)!;
      const strategy =
        strategyOf.get(sc.scenarioId)?.strategy ?? (sc.isOutline ? 'parametrised' : 'factory');
      const mdIds = decisionsOf(sc.scenarioId).map((d) => d.decision_id);
      const setup = mockSetup(decisionsOf(sc.scenarioId), w.behaviour);
      const asyncKw = plan.await ? 'async ' : '';
      const manifestEntry = (c: PlanCase, title: string): ManifestTest => {
        const row = sc.examples.find((r) => r.rowIndex === c.row);
        return {
          test_id: testId(sc.scenarioId, c.row),
          scenario_id: sc.scenarioId,
          requirement_id: req,
          file,
          jest_full_name: `${describe} ${title}`,
          ...(c.row !== undefined ? { examples_row: c.row } : {}),
          ...(row?.boundaryRef ? { boundary_ref: row.boundaryRef } : {}),
          ...(row?.partitionRef ? { partition_ref: row.partitionRef } : {}),
          strategy,
          assertion_categories: c.categories,
          ...(mdIds.length ? { mock_decision_ids: mdIds } : {}),
          verification: {
            syntactic: 'skipped',
            referential: 'skipped',
            traceability: 'skipped',
            semantic: { status: 'skipped' },
          },
          repair_rounds: 0,
        };
      };

      if (!sc.isOutline) {
        const c = plan.cases[0]!;
        const title = `[${sc.scenarioId}][${testId(sc.scenarioId)}] ${sc.scenarioName} :: ${caseLabel(sc)}`;
        blocks.push([
          `test(${q(title)}, ${asyncKw}() => {`,
          ...indent([...setup, ...renderCase(plan, c)], 2),
          '});',
        ]);
        tests.push(manifestEntry(c, title));
        continue;
      }

      // Outline: group rows whose test body is the same code -> one test.each per group.
      const cols = Object.keys(plan.params);
      const quoted = new Set(plan.quoted_columns);
      const groups = new Map<string, PlanCase[]>();
      for (const c of plan.cases) {
        const body = [...setup, ...renderCase(plan, c)].join('\n');
        groups.set(body, [...(groups.get(body) ?? []), c]);
      }
      for (const [body, cases] of groups) {
        const rows = cases.map((c) => {
          const vals = cols.map((col) =>
            JSON.stringify(rowValue(sc, c.row!, col, quoted.has(col))),
          );
          return `[${[q(testId(sc.scenarioId, c.row)), q(caseLabel(sc, c.row)), ...vals].join(', ')}],`;
        });
        const title = `[${sc.scenarioId}][%s] ${printfSafe(sc.scenarioName)} :: %s`;
        const args = ['_id', '_case', ...cols.map((c) => plan.params[c]!)].join(', ');
        blocks.push([
          'test.each([',
          ...indent(rows, 2),
          `])(${q(title)}, ${asyncKw}(${args}) => {`,
          ...indent(body.split('\n'), 2),
          '});',
        ]);
        for (const c of cases)
          tests.push(
            manifestEntry(
              c,
              `[${sc.scenarioId}][${testId(sc.scenarioId, c.row)}] ${sc.scenarioName} :: ${caseLabel(sc, c.row)}`,
            ),
          );
      }
    }

    const content = [
      ...head,
      '',
      `describe(${q(describe)}, () => {`,
      ...(hasSpies ? ['  afterEach(() => jest.restoreAllMocks());', ''] : []),
      ...blocks.flatMap((b, i) => [...(i ? [''] : []), ...indent(b, 2)]),
      '});',
      '',
    ].join('\n');
    files.set(file, content);
    requires.set(file, {
      repoPath,
      module: subject.modulePath,
      names: [...used].sort(),
      mocks: [
        ...new Map(
          scenarios
            .flatMap((sc) => decisionsOf(sc.scenarioId))
            .filter((d) => d.dependency.kind !== 'global_object')
            .map((d) => [
              d.dependency.import_specifier,
              {
                specifier: d.dependency.import_specifier,
                ...(d.dependency.kind === 'internal_module' && d.dependency.resolved_path
                  ? { subjectPath: d.dependency.resolved_path }
                  : {}),
                kind: d.dependency.kind,
              },
            ]),
        ).values(),
      ],
    });
  }

  files.set(JEST_CONFIG, jestConfig(inputs));
  tests.sort((a, b) => a.test_id.localeCompare(b.test_id));
  const subjects = [...new Set(inputs.scenarios.map((s) => s.subject.subjectId))];
  const model = w.plans.model ?? undefined;
  const manifest: TestManifestFile = {
    contract: 'c3.test-manifest',
    schema_version: '1.0.0',
    producer: {
      component: 'C3',
      tool_version: w.toolVersion ?? '0.1.0',
      ...(model ? { model } : {}),
    },
    run_id: inputs.runId,
    generated_at: w.generatedAt ?? new Date().toISOString(),
    upstream: [
      {
        contract: 'c2.scenario-metadata',
        path: 'c2/scenario_metadata.json',
        schema_version: '1.0.0',
      },
      { contract: 'c3.mock-decisions', path: 'c3/mock_decisions.json', schema_version: '1.0.0' },
    ],
    subject_id: subjects[0] ?? 'SUB-NONE',
    runner: { name: 'jest', version: JEST_VERSION, config_path: JEST_CONFIG, test_root: TEST_ROOT },
    tests,
    stubs: [],
  };
  return { files, manifest, notWritten, requires };
}

/** c3/jest.config.cjs: run from the run folder. The subject's own node_modules is on the module path. */
export function jestConfig(inputs: C3Inputs): string {
  const repoPaths = [
    ...new Set(
      inputs.scenarios.map((s) =>
        typeof s.subject.source['repo_path'] === 'string'
          ? (s.subject.source['repo_path'] as string)
          : 'subject-src',
      ),
    ),
  ];
  const paths = (repoPaths.length ? repoPaths : ['subject-src']).map(
    (p) => `'<rootDir>/${p}/node_modules'`,
  );
  return [
    '// Written by C3. Run from the run folder: npx jest -c c3/jest.config.cjs',
    'module.exports = {',
    "  rootDir: '..',",
    "  testEnvironment: 'node',",
    "  roots: ['<rootDir>/c3/runnable_tests'],",
    `  modulePaths: [${paths.join(', ')}],`,
    '};',
    '',
  ].join('\n');
}
