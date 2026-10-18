// Types for what C3 reads (C3-03, FR1).
// Shapes follow packages/contracts/schemas: c2-scenario-metadata + subject-manifest.

/** One Gherkin step, with And/But resolved to the step type it continues. */
export interface ScenarioStep {
  keyword: 'Given' | 'When' | 'Then';
  text: string;
  line: number;
}

/** One Examples row of a Scenario Outline (C3 makes one test per row). */
export interface ExampleRow {
  rowIndex: number; // 1-based, same as examples[].row_index in the metadata
  values: Record<string, string>; // column header -> cell text
  boundaryRef?: string; // BV-nn from the metadata, if C2 linked one
  partitionRef?: string; // EP-nn from the metadata, if C2 linked one
}

/** The subject (code under test) a requirement belongs to, from subject-manifest.json. */
export interface SubjectRef {
  subjectId: string;
  projectCode: string;
  modulePath: string;
  exports: string[];
  moduleSystem?: string;
  source: Record<string, unknown>;
}

/** C2's metadata for one scenario, kept as-is (C3 must use C2's boundary values unchanged). */
export interface C2ScenarioMeta {
  scenario_id: string;
  requirement_id: string;
  feature_file: string;
  scenario_name: string;
  line?: number;
  scenario_type: string;
  is_outline: boolean;
  constraints?: unknown[];
  equivalence_partitions?: unknown[];
  boundary_values?: unknown[];
  examples?: {
    row_index: number;
    values: Record<string, unknown>;
    boundary_ref?: string;
    partition_ref?: string;
  }[];
  verification: { fully_verified: boolean; [check: string]: unknown };
  [key: string]: unknown;
}

/** Everything C3 needs about one scenario, joined from the 3 inputs. */
export interface C3ScenarioInput {
  scenarioId: string;
  requirementId: string;
  scenarioName: string;
  scenarioType: string;
  isOutline: boolean;
  featureFile: string; // relative to the run folder, with '/'
  line: number;
  steps: ScenarioStep[];
  examples: ExampleRow[];
  metadata: C2ScenarioMeta;
  subject: SubjectRef;
}

export interface SkippedScenario {
  scenarioId: string;
  requirementId: string;
  reason: string;
}

export interface C3Inputs {
  runId: string;
  inDir: string;
  scenarios: C3ScenarioInput[]; // fully verified by C2 -> C3 builds tests for these
  skipped: SkippedScenario[]; // not fully verified -> no test (reported later as skipped_not_verified)
}
