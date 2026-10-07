import path from 'node:path';
import { describe, expect, test } from 'vitest';
import { parseRunArgs } from '../src/args.js';

describe('orch parseRunArgs', () => {
  test('reads the run command options', () => {
    const base = path.resolve('repo-root');
    const opts = parseRunArgs(['run', '--in', 'runs/RUN-1', '--out', 'runs/RUN-1'], base);
    expect(opts.in).toBe(path.join(base, 'runs', 'RUN-1'));
    expect(opts.out).toBe(path.join(base, 'runs', 'RUN-1'));
    expect(opts.subjectRoot).toBeUndefined();
  });

  test('rejects a missing run command', () => {
    expect(() => parseRunArgs(['--out', 'x'])).toThrow(/Usage/);
  });

  test('rejects a missing --out', () => {
    expect(() => parseRunArgs(['run'])).toThrow(/--out/);
  });
});
