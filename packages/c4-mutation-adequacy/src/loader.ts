import fs from 'node:fs';
import path from 'node:path';
import { assertMatchesSchema } from './contracts.js';
import type { Subject, SubjectManifest, TestManifest } from './types.js';

/** Everything C4 needs from the run folder, checked against the contracts. */
export interface C4Inputs {
  inDir: string;
  manifest: TestManifest;
  subject: Subject;
  /** Root of the code under test (absolute). */
  subjectRoot: string;
  /** Folder name the C3 tests use to import the subject, relative to the run folder. */
  subjectDirInRun: string;
  /** Jest config, relative to the run folder. */
  jestConfig: string;
  /** Files StrykerJS mutates, relative to the run folder. */
  mutate: string[];
}

function readJson<T>(file: string): T {
  if (!fs.existsSync(file)) throw new Error(`Missing input file: ${file}`);
  return JSON.parse(fs.readFileSync(file, 'utf8')) as T;
}

/**
 * Load `c3/test_manifest.json` and `subject-manifest.json` from a run folder (or a golden fixture folder).
 * When `subjectRoot` is not given, the subject is the `source.repo_path` folder inside the run folder.
 */
export function loadInputs(inDir: string, subjectRoot?: string): C4Inputs {
  const manifest = readJson<TestManifest>(path.join(inDir, 'c3', 'test_manifest.json'));
  assertMatchesSchema(manifest, 'c3-test-manifest.schema.json', 'c3/test_manifest.json');
  const subjects = readJson<SubjectManifest>(path.join(inDir, 'subject-manifest.json'));
  assertMatchesSchema(subjects, 'subject-manifest.schema.json', 'subject-manifest.json');

  const subject = subjects.subjects.find((s) => s.subject_id === manifest.subject_id);
  if (!subject)
    throw new Error(
      `subject-manifest.json has no subject ${manifest.subject_id} (from test_manifest.json)`,
    );

  for (const t of manifest.tests) {
    if (!fs.existsSync(path.join(inDir, t.file)))
      throw new Error(`${t.test_id}: test file not found: ${t.file}`);
  }
  const jestConfig = manifest.runner.config_path;
  if (!fs.existsSync(path.join(inDir, jestConfig)))
    throw new Error(`Jest config not found: ${jestConfig}`);

  const subjectDirInRun = subject.source.repo_path ?? 'subject-src';
  const root = subjectRoot ?? path.join(inDir, subjectDirInRun);
  const moduleFile = path.join(root, subject.module_path);
  if (!fs.existsSync(moduleFile)) throw new Error(`Module under test not found: ${moduleFile}`);

  return {
    inDir,
    manifest,
    subject,
    subjectRoot: root,
    subjectDirInRun,
    jestConfig,
    mutate: [path.posix.join(subjectDirInRun, subject.module_path)],
  };
}
