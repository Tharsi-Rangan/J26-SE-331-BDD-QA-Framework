import { describe, expect, test } from 'vitest';
import { preflightProblems, summarizePreflight, type JestJson } from '../src/preflight.js';
import type { ManifestTest } from '../src/types.js';

const tests = [
  {
    test_id: 'TST-EX-001-01-01',
    jest_full_name: '[REQ-EX-001] F [SCN-EX-001-01][TST-EX-001-01-01] a',
  },
  {
    test_id: 'TST-EX-001-01-02',
    jest_full_name: '[REQ-EX-001] F [SCN-EX-001-01][TST-EX-001-01-02] b',
  },
] as ManifestTest[];

const pass = (fullName: string) => ({ fullName, status: 'passed', failureMessages: [] });

function jest(results: JestJson['testResults']): JestJson {
  return { numTotalTests: 0, testResults: results };
}

describe('c4 summarizePreflight', () => {
  test('all manifest tests pass', () => {
    const r = summarizePreflight(
      jest([
        {
          name: '/w/c3/runnable_tests/REQ-EX-001.test.js',
          status: 'passed',
          message: '',
          assertionResults: tests.map((t) => pass(t.jest_full_name)),
        },
      ]),
      tests,
      '/w',
    );
    expect(r).toEqual({
      status: 'pass',
      tests_run: 2,
      passed: 2,
      failed: 0,
      file_errors: [],
      failed_tests: [],
      not_run: [],
    });
  });

  test('a test that fails on the original code fails the preflight', () => {
    const r = summarizePreflight(
      jest([
        {
          name: '/w/c3/runnable_tests/REQ-EX-001.test.js',
          status: 'failed',
          message: '',
          assertionResults: [
            pass(tests[0]!.jest_full_name),
            {
              fullName: tests[1]!.jest_full_name,
              status: 'failed',
              failureMessages: [
                '\u001b[31mExpected: 1\u001b[39m\nReceived: 2\n    at Object.toBe (/w/x.test.js:1:1)',
              ],
            },
          ],
        },
      ]),
      tests,
      '/w',
    );
    expect(r.status).toBe('fail');
    expect(r.failed_tests).toEqual([
      {
        test_id: 'TST-EX-001-01-02',
        jest_full_name: tests[1]!.jest_full_name,
        message: 'Expected: 1\nReceived: 2',
      },
    ]);
    expect(preflightProblems(r)[0]).toMatch(/fails on the original code: TST-EX-001-01-02/);
  });

  test('a file that does not compile fails the preflight', () => {
    const r = summarizePreflight(
      jest([
        {
          name: '/w/c3/runnable_tests/REQ-EX-001.test.js',
          status: 'failed',
          message: 'SyntaxError: Unexpected token (3:4)',
          assertionResults: [],
        },
      ]),
      tests,
      '/w',
    );
    expect(r.status).toBe('fail');
    expect(r.file_errors).toEqual([
      {
        file: 'c3/runnable_tests/REQ-EX-001.test.js',
        message: 'SyntaxError: Unexpected token (3:4)',
      },
    ]);
    expect(r.not_run).toEqual(['TST-EX-001-01-01', 'TST-EX-001-01-02']);
    expect(preflightProblems(r)).toContain('Jest ran no tests');
  });

  test('a file error keeps the text after "Details:" with no work folder path', () => {
    const r = summarizePreflight(
      jest([
        {
          name: '/w/c3/runnable_tests/REQ-EX-001.test.js',
          status: 'failed',
          message:
            'Jest encountered an unexpected token\n\n    Details:\n\n    SyntaxError: /w/c3/runnable_tests/REQ-EX-001.test.js: Unexpected token (19:6)\n',
          assertionResults: [],
        },
      ]),
      tests,
      '/w',
    );
    expect(r.file_errors[0]!.message).toBe(
      'SyntaxError: c3/runnable_tests/REQ-EX-001.test.js: Unexpected token (19:6)',
    );
  });

  test('a manifest test with a name Jest does not print is listed in not_run', () => {
    const r = summarizePreflight(
      jest([
        {
          name: '/w/c3/runnable_tests/REQ-EX-001.test.js',
          status: 'passed',
          message: '',
          assertionResults: [pass(tests[0]!.jest_full_name)],
        },
      ]),
      tests,
      '/w',
    );
    expect(r.status).toBe('pass');
    expect(r.not_run).toEqual(['TST-EX-001-01-02']);
  });
});
