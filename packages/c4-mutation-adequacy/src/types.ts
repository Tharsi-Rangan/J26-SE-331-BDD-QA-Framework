// The parts of the shared contracts and of StrykerJS mutation.json that C4 reads.

export interface ManifestTest {
  test_id: string;
  scenario_id: string;
  requirement_id: string;
  file: string;
  jest_full_name: string;
  assertion_categories?: string[];
  mock_decision_ids?: string[];
  boundary_ref?: string;
}

export interface TestManifest {
  schema_version: string;
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
  files: Record<string, { source?: string; mutants: StrykerMutant[] }>;
  testFiles?: Record<string, { tests: { id: string; name: string }[] }>;
  framework?: { name: string; version: string };
}

/** The parts of `c2/scenario_metadata.json` that the embedding trace signal reads. */
export interface ScenarioMetadata {
  features: { requirement_id: string; feature_name: string; requirement_text_used?: string }[];
  scenarios: { scenario_id: string; requirement_id: string; scenario_name: string }[];
}

/** The parts of `c3/mock_decisions.json` that the gap classifier reads. */
export interface MockDecision {
  decision_id: string;
  scenario_id: string;
  dependency: { import_specifier: string; symbol: string };
  decision: string;
}

export interface MockDecisions {
  decisions: MockDecision[];
}
