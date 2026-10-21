import path from 'node:path';
import { describe, expect, test } from 'vitest';
import { parseRunArgs, parseScanArgs } from '../src/args.js';

describe('c3 parseRunArgs', () => {
  test('reads the run command options', () => {
    const base = path.resolve('repo-root');
    const opts = parseRunArgs(['run', '--in', 'runs/RUN-1', '--out', 'runs/RUN-1'], base);
    expect(opts.in).toBe(path.join(base, 'runs', 'RUN-1'));
    expect(opts.out).toBe(path.join(base, 'runs', 'RUN-1'));
    expect(opts.subjectRoot).toBeUndefined();
    expect(opts.noModel).toBeUndefined();
  });

  test('--no-model turns the model off (C3-07)', () => {
    expect(parseRunArgs(['run', '--out', 'x', '--no-model']).noModel).toBe(true);
  });

  test('rejects a missing run command', () => {
    expect(() => parseRunArgs(['--out', 'x'])).toThrow(/Usage/);
  });

  test('rejects a missing --out', () => {
    expect(() => parseRunArgs(['run'])).toThrow(/--out/);
  });
});

describe('c3 parseScanArgs', () => {
  test('reads the scan command options', () => {
    const base = path.resolve('repo-root');
    const opts = parseScanArgs(
      [
        'scan',
        '--subject-root',
        'subjects/express',
        '--module',
        'lib/utils.js',
        '--exports',
        'isAbsolute, etag',
      ],
      base,
    );
    expect(opts).toEqual({
      subjectRoot: path.join(base, 'subjects', 'express'),
      module: 'lib/utils.js',
      exports: ['isAbsolute', 'etag'],
      out: undefined,
    });
  });

  test('rejects a scan without --module', () => {
    expect(() => parseScanArgs(['scan', '--subject-root', 'x'])).toThrow(/Usage: c3 scan/);
  });
});
