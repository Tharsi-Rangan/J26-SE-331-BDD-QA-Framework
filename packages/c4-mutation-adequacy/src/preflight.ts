import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import type { C4Inputs } from './loader.js';
import type { ManifestTest } from './types.js';

const require = createRequire(import.meta.url);

/** The parts of the Jest `--json` output that C4 reads. */
export interface JestJson {
  numTotalTests: number;
  testResults: {
    name: string;
    status: string;
    message: string;
    assertionResults: { fullName: string; status: string; failureMessages: string[] }[];
  }[];
}

export interface PreflightResult {
  status: 'pass' | 'fail';
  tests_run: number;
  passed: number;
  failed: number;
  /** Test files that Jest could not load, for example a syntax error or a missing module. */
  file_errors: { file: string; message: string }[];
  failed_tests: { test_id: string | null; jest_full_name: string; message: string }[];
  /** Manifest tests that Jest did not run, because no test has their `jest_full_name`. */
  not_run: string[];
}

/** Short Jest message with no colour codes and no work folder path. */
function shortMessage(text: string, workDir: string): string {
  // eslint-disable-next-line no-control-regex
  let plain = text.replace(/\u001b\[[0-9;]*m/g, '').replaceAll(workDir + path.sep, '');
  // A file that does not load has a long help text, and the real error comes after "Details:".
  const details = plain.indexOf('Details:');
  if (details >= 0) plain = plain.slice(details + 'Details:'.length);
  return plain
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('at '))
    .slice(0, 6)
    .join('\n');
}

/** Check the Jest result of the C3 tests on the original code. `workDir` must be a real path. */
export function summarizePreflight(
  jest: JestJson,
  tests: ManifestTest[],
  workDir: string,
): PreflightResult {
  const idByName = new Map(tests.map((t) => [t.jest_full_name, t.test_id]));
  const ran = new Set<string>();
  const fileErrors: PreflightResult['file_errors'] = [];
  const failedTests: PreflightResult['failed_tests'] = [];
  let passed = 0;

  for (const file of jest.testResults) {
    if (file.status === 'failed' && file.assertionResults.length === 0)
      fileErrors.push({
        file: path.relative(workDir, file.name),
        message: shortMessage(file.message, workDir),
      });
    for (const a of file.assertionResults) {
      ran.add(a.fullName);
      if (a.status === 'passed') passed++;
      else if (a.status === 'failed')
        failedTests.push({
          test_id: idByName.get(a.fullName) ?? null,
          jest_full_name: a.fullName,
          message: shortMessage(a.failureMessages.join('\n'), workDir),
        });
    }
  }
  const testsRun = jest.testResults.reduce((n, f) => n + f.assertionResults.length, 0);
  const ok = fileErrors.length === 0 && failedTests.length === 0 && testsRun > 0;
  return {
    status: ok ? 'pass' : 'fail',
    tests_run: testsRun,
    passed,
    failed: failedTests.length,
    file_errors: fileErrors,
    failed_tests: failedTests,
    not_run: tests.filter((t) => !ran.has(t.jest_full_name)).map((t) => t.test_id),
  };
}

/** Readable reasons for a failed preflight, one per line. */
export function preflightProblems(r: PreflightResult): string[] {
  const lines = [
    ...r.file_errors.map((e) => `test file does not load: ${e.file}\n    ${e.message}`),
    ...r.failed_tests.map(
      (t) => `test fails on the original code: ${t.test_id ?? t.jest_full_name}\n    ${t.message}`,
    ),
  ];
  if (r.tests_run === 0) lines.push('Jest ran no tests');
  return lines;
}

/**
 * Run the C3 tests once with Jest on the original code, in the work folder from `prepareWorkDir`.
 * The result goes to `c4/preflight.json` in `outDir`.
 */
export function runPreflight(
  inputs: C4Inputs,
  workDir: string,
  outDir: string,
  log: (line: string) => void = console.log,
): PreflightResult {
  const jestBin = path.join(path.dirname(require.resolve('jest/package.json')), 'bin', 'jest.js');
  const jsonFile = path.join(workDir, 'reports', 'preflight', 'jest.json');
  fs.mkdirSync(path.dirname(jsonFile), { recursive: true });
  const args = [
    jestBin,
    '--config',
    inputs.jestConfig,
    '--ci',
    '--json',
    `--outputFile=${jsonFile}`,
  ];
  const subjectModules = path.resolve(inputs.subjectRoot, 'node_modules');
  if (fs.existsSync(subjectModules)) args.push('--modulePaths', subjectModules);

  log(`[c4] preflight: running the C3 tests on the original code`);
  const res = spawnSync(process.execPath, args, { cwd: workDir, encoding: 'utf8' });
  // Jest prints real paths, and on macOS the temp folder is a link (/var -> /private/var).
  const realWork = fs.realpathSync(workDir);
  if (!fs.existsSync(jsonFile))
    throw new Error(`Preflight: Jest did not run (exit ${res.status})\n${res.stderr ?? ''}`);

  const jest = JSON.parse(fs.readFileSync(jsonFile, 'utf8')) as JestJson;
  const result = summarizePreflight(jest, inputs.manifest.tests, realWork);
  const outFile = path.join(outDir, 'c4', 'preflight.json');
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, JSON.stringify(result, null, 2) + '\n');
  log(
    `[c4] preflight ${result.status}: ${result.passed}/${result.tests_run} tests pass, ${result.file_errors.length} file errors; wrote ${outFile}`,
  );
  for (const id of result.not_run)
    console.warn(`[c4] warning: Jest did not run manifest test ${id}`);
  return result;
}
