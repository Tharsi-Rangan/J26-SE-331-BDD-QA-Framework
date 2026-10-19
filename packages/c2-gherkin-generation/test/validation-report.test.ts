
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, test } from 'vitest';
import { writeValidationReport } from '../src/validation-report.js';

let tempDir = '';

afterEach(() => {
  if (tempDir && fs.existsSync(tempDir)) {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }

  tempDir = '';
});

describe('writeValidationReport', () => {
  test('writes totals and results for valid and invalid feature files', () => {
    tempDir = fs.mkdtempSync(
      path.join(os.tmpdir(), 'c2-validation-report-'),
    );

    const reportPath = writeValidationReport(
      tempDir,
      'RUN-FIXTURE-TEST-1',
      [
        {
          requirement_id: 'REQ-EX-001',
          feature_file: 'c2/features/REQ-EX-001.feature',
          valid: true,
        },
        {
          requirement_id: 'REQ-EX-002',
          feature_file: 'c2/features/REQ-EX-002.feature',
          valid: false,
          error: 'Syntax error at line 5',
        },
      ],
    );

    expect(fs.existsSync(reportPath)).toBe(true);
    expect(path.basename(reportPath)).toBe('validation_report.json');

    const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));

    expect(report.run_id).toBe('RUN-FIXTURE-TEST-1');
    expect(report.total_files).toBe(2);
    expect(report.valid_files).toBe(1);
    expect(report.invalid_files).toBe(1);
    expect(report.results[0].valid).toBe(true);
    expect(report.results[1].requirement_id).toBe('REQ-EX-002');
    expect(report.results[1].error).toBe('Syntax error at line 5');
  });

  test('writes an empty report when there are no results', () => {
    tempDir = fs.mkdtempSync(
      path.join(os.tmpdir(), 'c2-validation-report-'),
    );

    const reportPath = writeValidationReport(
      tempDir,
      'RUN-FIXTURE-TEST-1',
      [],
    );

    const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));

    expect(report.total_files).toBe(0);
    expect(report.valid_files).toBe(0);
    expect(report.invalid_files).toBe(0);
    expect(report.results).toEqual([]);
  });
});
