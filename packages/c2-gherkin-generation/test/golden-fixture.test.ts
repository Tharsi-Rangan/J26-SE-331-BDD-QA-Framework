import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, test } from 'vitest';

const fixtureRoot = path.resolve(
  process.cwd(),
  '../../packages/contracts/fixtures/golden/example-registration',
);

describe('C2 golden Gherkin fixture', () => {
  test('contains the expected feature and scenario metadata files', () => {
    expect(
      fs.existsSync(path.join(fixtureRoot, 'c2/features/REQ-EX-001.feature')),
    ).toBe(true);

    expect(
      fs.existsSync(path.join(fixtureRoot, 'c2/scenario_metadata.json')),
    ).toBe(true);
  });

  test('feature scenario names match the metadata', () => {
    const featurePath = path.join(
      fixtureRoot,
      'c2/features/REQ-EX-001.feature',
    );
    const metadataPath = path.join(fixtureRoot, 'c2/scenario_metadata.json');

    const feature = fs.readFileSync(featurePath, 'utf8');
    const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8')) as {
      scenarios: Array<{ scenario_name: string }>;
    };

    for (const scenario of metadata.scenarios) {
      const scenarioTitle = `Scenario: ${scenario.scenario_name}`;
      const outlineTitle = `Scenario Outline: ${scenario.scenario_name}`;

      expect(
        feature.includes(scenarioTitle) || feature.includes(outlineTitle),
      ).toBe(true);
    }
  });
});