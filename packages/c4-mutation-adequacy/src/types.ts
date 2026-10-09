// The parts of the shared contracts and of StrykerJS mutation.json that C4 reads.

export interface ManifestTest {
  test_id: string;
  scenario_id: string;
  requirement_id: string;
  file: string;
  jest_full_name: string;
}

export interface TestManifest {
  run_id: string;
  subject_id: string;
  runner: { name: 'jest'; version?: string; config_path: string; test_root?: string };
  tests: ManifestTest[];
  stubs: { stub_id: string; scenario_id: string; requirement_id: string; file: string }[];
}

export interface Subject {
  subject_id: string;
  project_code: string;
  source: { kind: 'bugsjs' | 'example'; repo_path?: string };
  module_path: string;
  exports: string[];
  jest_config?: string;
  requirement_ids: string[];
}

export interface SubjectManifest {
  subjects: Subject[];
}

export type MutantStatus =
  | 'Killed'
  | 'Survived'
  | 'NoCoverage'
  | 'Timeout'
  | 'CompileError'
  | 'RuntimeError'
  | 'Ignored'
  | 'Pending';

export interface Position {
  line: number;
  column: number;
}

export interface StrykerMutant {
  id: string;
  mutatorName: string;
  replacement?: string;
  status: MutantStatus;
  location: { start: Position; end: Position };
  coveredBy?: string[];
  killedBy?: string[];
}

/** StrykerJS mutation-testing-report-schema, only the fields C4 uses. */
export interface MutationReport {
  files: Record<string, { mutants: StrykerMutant[] }>;
  testFiles?: Record<string, { tests: { id: string; name: string }[] }>;
  framework?: { name: string; version: string };
}
