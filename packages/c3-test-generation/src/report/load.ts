// C3-16 report, part 1: read everything `c3 run` and `c3 pilot` wrote for one run folder.
// Read-only. A missing or broken file is skipped (the report says "not written"), so the report also
// works for a run that stopped early.
import fs from 'node:fs';
import path from 'node:path';
import { readC3Inputs } from '../input/reader.js';
import type { C3Inputs } from '../input/types.js';
import type { AssertionWorkFile } from '../assert/plan.js';
import type { BehaviourWorkFile } from '../mock/behaviour.js';
import type { MockDecisionsFile } from '../mock/decisions.js';
import type { ConfidenceReportFile } from '../route/confidence.js';
import type { ModuleScan } from '../scan/types.js';
import type { StrategyChoice } from '../strategy.js';
import type { RepairLogEntry } from '../verify/repair.js';
import type { VerificationWorkFile } from '../verify/verify.js';
import type { TestManifestFile } from '../writer/jest-writer.js';
import type { PilotResult } from '../pilot.js';

/** The subject entry of subject-manifest.json (only the fields the report shows). */
export interface ReportSubject {
  subject_id: string;
  project?: string;
  project_code?: string;
  source?: {
    kind?: string;
    bug_id?: string;
    buggy_ref?: string;
    fixed_ref?: string;
    repo_path?: string;
  };
  module_path: string;
  exports?: string[];
  notes?: string;
}

/** One feature of c2/scenario_metadata.json. */
export interface ReportFeature {
  feature_file: string;
  requirement_id: string;
  feature_name?: string;
  requirement_text_used?: string;
}

export interface RunData {
  runDir: string; // absolute
  folder: string; // folder name, e.g. bugsjs-eslint-22
  label: string; // pilot label, else the folder name
  inputs?: C3Inputs;
  inputsError?: string;
  subjects: ReportSubject[];
  features: ReportFeature[];
  scans: { subjectId: string; modulePath: string; scan: ModuleScan }[];
  mock?: MockDecisionsFile;
  behaviour?: BehaviourWorkFile;
  plans?: AssertionWorkFile;
  strategy?: { rules_version: string; choices: StrategyChoice[] };
  manifest?: TestManifestFile;
  verification?: VerificationWorkFile;
  repair?: { max_rounds: number; entries: RepairLogEntry[] };
  confidence?: ConfidenceReportFile;
  pilot?: PilotResult;
  /** Generated test and stub files: path relative to the run folder (with '/') -> text. */
  files: Map<string, string>;
}

function readJson<T>(file: string): T | undefined {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8')) as T;
  } catch {
    return undefined;
  }
}

function listFiles(dir: string, rel: string, out: Map<string, string>): void {
  if (!fs.existsSync(dir)) return;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name);
    const r = `${rel}/${e.name}`;
    if (e.isDirectory()) listFiles(full, r, out);
    else if (/\.(c?js|ts)$/.test(e.name)) out.set(r, fs.readFileSync(full, 'utf8'));
  }
}

/** True when the folder holds a finished `c3 run` (the confidence report is its last file). */
export function isC3Run(dir: string): boolean {
  return fs.existsSync(path.join(dir, 'c3', 'generation_confidence_report.json'));
}

export function loadRun(runDir: string): RunData {
  const dir = path.resolve(runDir);
  const work = path.join(dir, 'c3', 'work');
  const data: RunData = {
    runDir: dir,
    folder: path.basename(dir),
    label: path.basename(dir),
    subjects:
      readJson<{ subjects: ReportSubject[] }>(path.join(dir, 'subject-manifest.json'))?.subjects ??
      [],
    features:
      readJson<{ features?: ReportFeature[] }>(path.join(dir, 'c2', 'scenario_metadata.json'))
        ?.features ?? [],
    scans: readJson<RunData['scans']>(path.join(work, 'dependency_scan.json')) ?? [],
    mock: readJson(path.join(dir, 'c3', 'mock_decisions.json')),
    behaviour: readJson(path.join(work, 'mock_behaviour.json')),
    plans: readJson(path.join(work, 'assertion_plan.json')),
    strategy: readJson(path.join(work, 'strategy.json')),
    manifest: readJson(path.join(dir, 'c3', 'test_manifest.json')),
    verification: readJson(path.join(work, 'verification.json')),
    repair: readJson(path.join(work, 'repair_log.json')),
    confidence: readJson(path.join(dir, 'c3', 'generation_confidence_report.json')),
    pilot: readJson(path.join(work, 'pilot_results.json')),
    files: new Map(),
  };
  try {
    data.inputs = readC3Inputs(dir);
  } catch (err) {
    data.inputsError = err instanceof Error ? err.message : String(err);
  }
  if (data.pilot?.summary.label) data.label = data.pilot.summary.label;
  listFiles(path.join(dir, 'c3', 'runnable_tests'), 'c3/runnable_tests', data.files);
  listFiles(path.join(dir, 'c3', 'test_stubs'), 'c3/test_stubs', data.files);
  return data;
}
