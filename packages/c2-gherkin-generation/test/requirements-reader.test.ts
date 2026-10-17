import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, test } from 'vitest';
import { readReadyRequirements } from '../src/requirements-reader.js';

const tempDirs: string[] = [];

function makeInput(requirements: unknown[], contract = 'c1.validated-requirements') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'c2-reader-'));
  tempDirs.push(dir);

  const c1Dir = path.join(dir, 'c1');
  fs.mkdirSync(c1Dir, { recursive: true });

  fs.writeFileSync(
    path.join(c1Dir, 'validated_requirements.json'),
    JSON.stringify({ contract, requirements }),
    'utf8',
  );

  return dir;
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe('readReadyRequirements', () => {
  test('returns only BDD-ready requirements using final_text', () => {
    const dir = makeInput([
      {
        requirement_id: 'REQ-EX-001',
        original_text: 'Original text must not be used',
        final_text: 'The system shall accept ages from 18 to 65.',
        bdd_ready: true,
      },
      {
        requirement_id: 'REQ-EX-002',
        final_text: 'This requirement is not ready.',
        bdd_ready: false,
      },
    ]);

    expect(readReadyRequirements(dir)).toEqual([
      {
        requirement_id: 'REQ-EX-001',
        final_text: 'The system shall accept ages from 18 to 65.',
      },
    ]);
  });

  test('rejects an unexpected contract identifier', () => {
    const dir = makeInput([], 'wrong.contract');
    expect(() => readReadyRequirements(dir)).toThrow(/contract identifier/);
  });

  test('rejects a missing requirements array', () => {
    const dir = makeInput([]);
    const file = path.join(dir, 'c1', 'validated_requirements.json');
    fs.writeFileSync(file, JSON.stringify({ contract: 'c1.validated-requirements' }));

    expect(() => readReadyRequirements(dir)).toThrow(/must be an array/);
  });

  test('rejects a ready requirement without final_text', () => {
    const dir = makeInput([
      { requirement_id: 'REQ-EX-003', bdd_ready: true, final_text: '' },
    ]);

    expect(() => readReadyRequirements(dir)).toThrow(/non-empty final_text/);
  });
});
