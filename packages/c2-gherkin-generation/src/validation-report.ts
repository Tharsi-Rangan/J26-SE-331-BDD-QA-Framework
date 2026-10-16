
import fs from 'node:fs';
import path from 'node:path';

export interface FeatureValidationEntry {
  requirement_id: string;
  feature_file: string;
  valid: boolean;
  error?: string;
}

export interface FeatureValidationReport {
  run_id: string;
  generated_at: string;
  total_files: number;
  valid_files: number;
  invalid_files: number;
  results: FeatureValidationEntry[];
}

export function writeValidationReport(
  c2Dir: string,
  runId: string,
  results: FeatureValidationEntry[],
): string {
  const report: FeatureValidationReport = {
    run_id: runId,
    generated_at: new Date().toISOString(),
    total_files: results.length,
    valid_files: results.filter((result) => result.valid).length,
    invalid_files: results.filter((result) => !result.valid).length,
    results,
  };

  const reportPath = path.join(c2Dir, 'validation_report.json');

  fs.writeFileSync(
    reportPath,
    `${JSON.stringify(report, null, 2)}\n`,
    'utf8',
  );

  return reportPath;
}
