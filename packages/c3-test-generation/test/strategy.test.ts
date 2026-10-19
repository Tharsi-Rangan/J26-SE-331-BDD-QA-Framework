import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';
import { run } from '../src/index.js';
import { readC3Inputs } from '../src/input/reader.js';
import type { C3ScenarioInput } from '../src/input/types.js';
import { chooseStrategies, chooseStrategy } from '../src/strategy.js';

const GOLDEN = fileURLToPath(
  new URL('../../contracts/fixtures/golden/example-registration', import.meta.url),
);

describe('C3-09 strategy selection', () => {
  const [plain, outline] = readC3Inputs(GOLDEN).scenarios as [C3ScenarioInput, C3ScenarioInput];

  test('a Scenario Outline is parametrised (S-01) and counts the C2 boundary rows', () => {
    expect(chooseStrategy(outline)).toEqual({
      scenario_id: 'SCN-EX-001-02',
      strategy: 'parametrised',
      rule_id: 'S-01',
      reason:
        'Scenario Outline with 6 Examples rows (6 boundary value and 0 partition rows from C2); one test.each row per Examples row, C2 values used as-is.',
    });
  });

  test('a plain scenario is factory (S-02); a numeric range is noted as a PP2 property-based candidate', () => {
    const c = chooseStrategy(plain);
    expect(c).toMatchObject({ strategy: 'factory', rule_id: 'S-02' });
    expect(c.reason).toMatch(
      /age has a numeric range \(CON-01\).*property-based candidate for PP2/,
    );
    const noRange = { ...plain, metadata: { ...plain.metadata, constraints: [] } };
    expect(chooseStrategy(noRange).reason).toBe(
      'Plain scenario: one test built from the Given/When step values.',
    );
  });

  test('an outline without C2 refs still gets S-01, with no refs in the reason', () => {
    const bare = {
      ...outline,
      examples: outline.examples.map(({ rowIndex, values }) => ({ rowIndex, values })),
    };
    expect(chooseStrategy(bare).reason).toBe(
      'Scenario Outline with 6 Examples rows; one test.each row per Examples row, C2 values used as-is.',
    );
  });

  test('golden strategies match the golden test_manifest.json', () => {
    const manifest = JSON.parse(
      fs.readFileSync(path.join(GOLDEN, 'c3/test_manifest.json'), 'utf8'),
    );
    const want = new Map(manifest.tests.map((t: any) => [t.scenario_id, t.strategy]));
    for (const c of chooseStrategies([plain, outline]).choices)
      expect(c.strategy).toBe(want.get(c.scenario_id));
  });

  test('c3 run writes c3/work/strategy.json', async () => {
    const out = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-st-'));
    try {
      await run({ in: GOLDEN, out });
      const s = JSON.parse(fs.readFileSync(path.join(out, 'c3/work/strategy.json'), 'utf8'));
      expect(s.choices.map((c: any) => c.strategy)).toEqual(['factory', 'parametrised']);
    } finally {
      fs.rmSync(out, { recursive: true, force: true });
    }
  });
});
