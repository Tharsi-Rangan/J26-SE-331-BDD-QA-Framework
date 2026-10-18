import path from 'node:path';
import { describe, expect, test } from 'vitest';
import { parseRunArgs } from '../src/args.js';

describe('c4 parseRunArgs', () => {
  test('reads the run command options', () => {
    const base = path.resolve('repo-root');
    const opts = parseRunArgs(['run', '--in', 'runs/RUN-1', '--out', 'runs/RUN-1'], base);
    expect(opts.in).toBe(path.join(base, 'runs', 'RUN-1'));
    expect(opts.out).toBe(path.join(base, 'runs', 'RUN-1'));
    expect(opts.subjectRoot).toBeUndefined();
    expect(opts.traceSignal).toBe('coverage_only');
  });

  test('reads --trace-signal and rejects an unknown mode', () => {
    expect(parseRunArgs(['run', '--out', 'x', '--trace-signal', 'full']).traceSignal).toBe('full');
    expect(() => parseRunArgs(['run', '--out', 'x', '--trace-signal', 'sbert'])).toThrow(
      /coverage_only, embedding_assisted, full/,
    );
  });

  test('rejects a missing run command', () => {
    expect(() => parseRunArgs(['--out', 'x'])).toThrow(/Usage/);
  });

  test('rejects a missing --out', () => {
    expect(() => parseRunArgs(['run'])).toThrow(/--out/);
  });
});
