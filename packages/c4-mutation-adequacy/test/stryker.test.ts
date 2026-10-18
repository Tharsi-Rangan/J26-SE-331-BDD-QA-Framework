import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, test } from 'vitest';
import type { C4Inputs } from '../src/loader.js';
import { strykerConfig } from '../src/stryker.js';

const temps: string[] = [];
afterEach(() => {
  for (const d of temps.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});

function inputs(withModules: boolean): C4Inputs {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'c4-subject-'));
  temps.push(root);
  if (withModules) fs.mkdirSync(path.join(root, 'node_modules'));
  return {
    inDir: root,
    manifest: {} as C4Inputs['manifest'],
    subject: {} as C4Inputs['subject'],
    subjectRoot: root,
    subjectDirInRun: 'subject-src',
    jestConfig: 'jest.config.js',
    mutate: ['subject-src/lib/utils.js'],
  };
}

describe('c4 strykerConfig', () => {
  test('a subject with node_modules gives Jest its path in modulePaths', () => {
    const i = inputs(true);
    expect(strykerConfig(i).jest).toEqual({
      configFile: 'jest.config.js',
      config: { modulePaths: [path.join(i.subjectRoot, 'node_modules')] },
    });
  });

  test('a subject with no node_modules keeps only the Jest config file', () => {
    expect(strykerConfig(inputs(false)).jest).toEqual({ configFile: 'jest.config.js' });
  });
});
