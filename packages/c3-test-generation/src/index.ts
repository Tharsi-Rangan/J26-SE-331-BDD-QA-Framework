import fs from 'node:fs';
import path from 'node:path';
import type { RunOptions, ScanCommandOptions } from './args.js';
import { readC3Inputs } from './input/reader.js';
import type { C3Inputs } from './input/types.js';
import { buildMockDecisions } from './mock/decisions.js';
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

/** C3's version, written as producer.tool_version in every contract file. */
export const TOOL_VERSION: string = JSON.parse(
  fs.readFileSync(new URL('../package.json', import.meta.url), 'utf8'),
).version;

/** Internal (non-contract) work files go here, next to the contract files in <out>/c3/. */
export const WORK_DIR = 'c3/work';

/**
 * Runnable Test Generation with Explainable Assertions and Mocking.
 * Done so far: C3-03 input reader, C3-04 dependency scan, C3-05 rule-based mock decisions.
 * Next: C3-06 model client.
 */
export async function run(options: RunOptions & { generatedAt?: string }): Promise<void> {
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
    const { file, targets } = buildMockDecisions(inputs, index, {
      generatedAt: options.generatedAt,
      toolVersion: TOOL_VERSION,
    });
    const out = path.join(options.out, 'c3', 'mock_decisions.json');
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, JSON.stringify(file, null, 2) + '\n');
    console.log(`[c3] mock decisions (rules ${file.rules_version}):`);
    for (const sc of inputs.scenarios) {
      console.log(`  ${sc.scenarioId} tests ${targets.get(sc.scenarioId)?.exports.join(', ')}`);
      for (const d of file.decisions.filter((x) => x.scenario_id === sc.scenarioId)) {
        const dep = `${d.dependency.import_specifier}#${d.dependency.symbol}`;
        console.log(`    ${d.decision_id} ${d.decision.padEnd(7)} ${d.rule_id} ${dep}`);
      }
    }
    console.log(`[c3] mock decisions written to ${out}`);
  }
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
