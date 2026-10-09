import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import type { C4Inputs } from './loader.js';
import type { MutationReport } from './types.js';

const require = createRequire(import.meta.url);

export interface StrykerResult {
  report: MutationReport;
  strykerVersion: string;
  /** The StrykerJS config C4 used, as written to the work folder. */
  config: Record<string, unknown>;
}

const packageDir = (name: string) => path.dirname(require.resolve(`${name}/package.json`));

export function strykerVersion(): string {
  return (
    JSON.parse(
      fs.readFileSync(path.join(packageDir('@stryker-mutator/core'), 'package.json'), 'utf8'),
    ) as { version: string }
  ).version;
}

/** StrykerJS config for one subject: Jest runner, per-test coverage, JSON report. */
export function strykerConfig(inputs: C4Inputs): Record<string, unknown> {
  return {
    testRunner: 'jest',
    coverageAnalysis: 'perTest',
    mutate: inputs.mutate,
    reporters: ['json', 'clear-text'],
    jsonReporter: { fileName: 'reports/mutation/mutation.json' },
    jest: { configFile: inputs.jestConfig },
    // A path, because pnpm does not put the plugin where StrykerJS looks for '@stryker-mutator/*'.
    plugins: [import.meta.resolve('@stryker-mutator/jest-runner')],
    tempDirName: '.stryker-tmp',
    cleanTempDir: true,
  };
}

/**
 * Copy the run folder (and the subject, when it is outside the run folder) to a temp work folder.
 * StrykerJS writes its sandbox and reports there, so the input folder stays clean.
 */
export function prepareWorkDir(inputs: C4Inputs): string {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'c4-stryker-'));
  const skip = new Set(['c4', '.stryker-tmp', 'reports', 'node_modules', '.git']);
  fs.cpSync(inputs.inDir, work, {
    recursive: true,
    filter: (src) => !skip.has(path.relative(inputs.inDir, src).split(path.sep)[0]!),
  });
  const subjectInWork = path.join(work, inputs.subjectDirInRun);
  if (path.resolve(inputs.subjectRoot) !== path.resolve(inputs.inDir, inputs.subjectDirInRun)) {
    fs.rmSync(subjectInWork, { recursive: true, force: true });
    fs.cpSync(inputs.subjectRoot, subjectInWork, {
      recursive: true,
      filter: (src) => !['node_modules', '.git'].includes(path.basename(src)),
    });
  }
  // The subject keeps its own dependencies; the C3 tests resolve Jest from C4's node_modules.
  const subjectModules = path.join(inputs.subjectRoot, 'node_modules');
  if (fs.existsSync(subjectModules))
    fs.symlinkSync(subjectModules, path.join(subjectInWork, 'node_modules'), 'dir');
  fs.symlinkSync(
    path.join(packageDir('@j26/c4-mutation-adequacy'), 'node_modules'),
    path.join(work, 'node_modules'),
    'dir',
  );
  return work;
}

/** Run StrykerJS on the C3 tests and return its mutation.json. Throws when StrykerJS fails. */
export function runStryker(
  inputs: C4Inputs,
  log: (line: string) => void = console.log,
): StrykerResult {
  const work = prepareWorkDir(inputs);
  const config = strykerConfig(inputs);
  fs.writeFileSync(path.join(work, 'stryker.config.json'), JSON.stringify(config, null, 2));

  const core = packageDir('@stryker-mutator/core');
  const bin = path.join(
    core,
    (
      JSON.parse(fs.readFileSync(path.join(core, 'package.json'), 'utf8')) as {
        bin: Record<string, string>;
      }
    ).bin.stryker!,
  );
  log(`[c4] running StrykerJS in ${work}`);
  const res = spawnSync(process.execPath, [bin, 'run', 'stryker.config.json'], {
    cwd: work,
    encoding: 'utf8',
  });
  if (res.stdout) log(res.stdout.trimEnd());
  const reportFile = path.join(work, 'reports', 'mutation', 'mutation.json');
  if (res.status !== 0 || !fs.existsSync(reportFile)) {
    throw new Error(
      `StrykerJS failed (exit ${res.status}). Work folder kept at ${work}\n${res.stderr ?? ''}`,
    );
  }
  const report = JSON.parse(fs.readFileSync(reportFile, 'utf8')) as MutationReport;
  fs.rmSync(work, { recursive: true, force: true });
  return { report, strykerVersion: strykerVersion(), config };
}
