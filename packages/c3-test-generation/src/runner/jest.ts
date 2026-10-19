// Run the generated Jest tests in a sandbox (C3-10 name check, C3-11 verification, C3-14 pilot runs).
// Sandbox = a temp folder with the run's c3/ files and the subject copied to its repo_path
// (node_modules is linked, not copied, so big projects stay fast).
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';

const require = createRequire(import.meta.url);

export interface JestTestResult {
  fullName: string;
  status: 'passed' | 'failed' | 'pending' | 'todo' | 'skipped' | 'disabled';
  failureMessages: string[];
  file: string; // relative to the sandbox, with '/'
}

export interface JestRunResult {
  ok: boolean; // Jest ran (tests may still fail)
  exitCode: number | null;
  tests: JestTestResult[];
  /** Files Jest could not run at all (syntax error, missing module), with the message. */
  suiteErrors: { file: string; message: string }[];
  stderr: string;
}

/** Copy a folder, skipping .git and node_modules (node_modules is linked instead). */
function copySubject(from: string, to: string): void {
  fs.mkdirSync(to, { recursive: true });
  for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
    if (entry.name === '.git' || entry.name === '.stryker-tmp') continue;
    const src = path.join(from, entry.name);
    const dst = path.join(to, entry.name);
    if (entry.name === 'node_modules' && entry.isDirectory()) {
      fs.symlinkSync(src, dst, process.platform === 'win32' ? 'junction' : 'dir');
    } else if (entry.isDirectory()) {
      copySubject(src, dst);
    } else if (entry.isFile()) {
      fs.copyFileSync(src, dst);
    }
  }
}

export interface SandboxOptions {
  /** The run folder with c3/ (written by C3). */
  runDir: string;
  /** The checked-out subject (--subject-root), or a folder inside the run folder (golden fixtures). */
  subjectRoot: string;
  /** Where the tests expect the subject: source.repo_path (default subject-src). */
  repoPath?: string;
  /** Replace or add files in the sandbox, e.g. one test file during repair. Path -> content. */
  overrides?: ReadonlyMap<string, string>;
  /** Copy <runDir>/c3 into the sandbox (default true). False: only `overrides` are written. */
  copyRun?: boolean;
}

/** Make a sandbox; the caller removes it with removeSandbox(). */
export function makeSandbox(o: SandboxOptions): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-jest-'));
  // A package.json here makes Node treat the subject's .js as CommonJS even under a "type": "module" folder.
  fs.writeFileSync(path.join(dir, 'package.json'), '{"private": true, "type": "commonjs"}\n');
  if (o.copyRun !== false && fs.existsSync(path.join(o.runDir, 'c3')))
    fs.cpSync(path.join(o.runDir, 'c3'), path.join(dir, 'c3'), {
      recursive: true,
      filter: (src) =>
        !src.includes(`${path.sep}work${path.sep}`) && !src.endsWith(`${path.sep}work`),
    });
  copySubject(o.subjectRoot, path.join(dir, o.repoPath ?? 'subject-src'));
  for (const [rel, content] of o.overrides ?? []) {
    const f = path.join(dir, rel);
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f, content);
  }
  return dir;
}

export function removeSandbox(dir: string): void {
  fs.rmSync(dir, { recursive: true, force: true });
}

/** Run Jest once in `dir` with c3/jest.config.cjs and return every test's full name and status. */
export function runJest(
  dir: string,
  options: { config?: string; timeoutMs?: number; testPathPattern?: string } = {},
): JestRunResult {
  const jestBin = require.resolve('jest/bin/jest');
  const outFile = path.join(dir, '.c3-jest-result.json');
  const args = [
    jestBin,
    '-c',
    options.config ?? 'c3/jest.config.cjs',
    '--json',
    `--outputFile=${outFile}`,
    '--ci',
    '--silent',
    '--no-cache',
    '--testTimeout=10000',
    ...(options.testPathPattern ? ['--testPathPattern', options.testPathPattern] : []),
  ];
  const res = spawnSync(process.execPath, args, {
    cwd: dir,
    encoding: 'utf8',
    timeout: options.timeoutMs ?? 120_000,
    env: { ...process.env, NODE_OPTIONS: '', FORCE_COLOR: '0' },
  });
  if (!fs.existsSync(outFile)) {
    return {
      ok: false,
      exitCode: res.status,
      tests: [],
      suiteErrors: [],
      stderr: (res.stderr || res.error?.message || '').slice(0, 4000),
    };
  }
  const json = JSON.parse(fs.readFileSync(outFile, 'utf8')) as {
    testResults: {
      name: string;
      status: string;
      message: string;
      assertionResults: {
        fullName: string;
        status: JestTestResult['status'];
        failureMessages: string[];
      }[];
    }[];
  };
  const rel = (f: string) => path.relative(dir, f).split(path.sep).join('/');
  const tests: JestTestResult[] = [];
  const suiteErrors: JestRunResult['suiteErrors'] = [];
  for (const suite of json.testResults) {
    if (suite.status === 'failed' && suite.assertionResults.length === 0)
      suiteErrors.push({ file: rel(suite.name), message: stripAnsi(suite.message).slice(0, 2000) });
    for (const a of suite.assertionResults)
      tests.push({
        fullName: a.fullName,
        status: a.status,
        failureMessages: a.failureMessages.map((m) => stripAnsi(m).slice(0, 2000)),
        file: rel(suite.name),
      });
  }
  return {
    ok: true,
    exitCode: res.status,
    tests,
    suiteErrors,
    stderr: (res.stderr ?? '').slice(0, 4000),
  };
}

export function stripAnsi(s: string): string {
  // eslint-disable-next-line no-control-regex
  return s.replace(/\u001b\[[0-9;]*m/g, '');
}
