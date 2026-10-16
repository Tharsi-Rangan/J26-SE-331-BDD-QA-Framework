
import fs from 'node:fs';
import path from 'node:path';
import type { RunOptions } from './args.js';
import { generateWithLlm } from './llm-client.js';
import { validateGherkin } from './gherkin-validator.js';
import {
  writeValidationReport,
  type FeatureValidationEntry,
} from './validation-report.js';

export type { RunOptions } from './args.js';

interface ValidatedRequirement {
  requirement_id: string;
  final_text: string;
  bdd_ready: boolean;
}

interface C1Input {
  contract: string;
  schema_version: string;
  run_id: string;
  requirements: ValidatedRequirement[];
}

function readRequirements(inputDir: string): C1Input {
  const file = path.join(inputDir, 'c1', 'validated_requirements.json');

  if (!fs.existsSync(file)) {
    throw new Error(`Missing validated requirements: ${file}`);
  }

  const input = JSON.parse(fs.readFileSync(file, 'utf8')) as C1Input;

  if (
    input.contract !== 'c1.validated-requirements' ||
    typeof input.run_id !== 'string' ||
    !Array.isArray(input.requirements)
  ) {
    throw new Error('Invalid C1 validated requirements input');
  }

  for (const requirement of input.requirements) {
    if (
      typeof requirement.requirement_id !== 'string' ||
      typeof requirement.final_text !== 'string' ||
      typeof requirement.bdd_ready !== 'boolean'
    ) {
      throw new Error('Invalid requirement entry in C1 input');
    }
  }

  return input;
}

function stripMarkdownFence(text: string): string {
  return text
    .trim()
    .replace(/^```(?:gherkin|feature)?\s*/i, '')
    .replace(/\s*```$/, '')
    .trim();
}

function parseFeatureName(feature: string, requirementId: string): string {
  const match = feature.match(/^\s*Feature:\s*(.+)$/m);

  if (!match) {
    throw new Error(
      `LLM output for ${requirementId} has no Feature declaration`,
    );
  }

  return match[1].trim();
}

export async function run(options: RunOptions): Promise<void> {
  const inputDir = options.in ?? options.out;
  const input = readRequirements(inputDir);

  const readyRequirements = input.requirements.filter(
    (requirement) => requirement.bdd_ready,
  );

  if (readyRequirements.length === 0) {
    throw new Error('No BDD-ready requirements found in C1 input');
  }

  const model = process.env.LLM_MODEL;

  if (!model) {
    throw new Error('Missing LLM_MODEL configuration');
  }

  const c2Dir = path.join(options.out, 'c2');
  const featuresDir = path.join(c2Dir, 'features');

  fs.mkdirSync(featuresDir, { recursive: true });

  const validationResults: FeatureValidationEntry[] = [];

  const metadata = {
    contract: 'c2.scenario-metadata',
    schema_version: '1.0.0',
    producer: {
      component: 'C2',
      tool_version: '0.1.0',
      model,
    },
    run_id: input.run_id,
    generated_at: new Date().toISOString(),
    upstream: [
      {
        contract: 'c1.validated-requirements',
        path: 'c1/validated_requirements.json',
        schema_version: input.schema_version,
      },
    ],
    features: [] as Array<Record<string, unknown>>,
    scenarios: [] as Array<Record<string, unknown>>,
  };

  for (const requirement of readyRequirements) {
    const prompt = [
      `Generate a single Gherkin feature for requirement ${requirement.requirement_id}.`,
      'Use only the requirement text provided below. Do not invent business rules.',
      'Return only valid English Gherkin, without Markdown fences.',
      'Follow the exact structure and tag format in this example:',
      '',
      '@REQ-EX-001',
      'Feature: User registration',
      '',
      '  @SCN-EX-001-01',
      '  @type:positive',
      '  Scenario: Register a user with a valid age',
      '    Given the user is on the registration page',
      '    When the user enters a valid age',
      '    And the user submits the registration form',
      '    Then the system should register the user successfully',
      '',
      'The example illustrates formatting only. Generate scenarios for the actual requirement below.',
      'Use exactly one @REQ-<requirement-id> tag immediately before Feature.',
      'Every Scenario must have exactly two tags immediately before its declaration:',
      'one @SCN-<requirement-id>-<two-digit-sequence> tag and one @type:positive, @type:negative, @type:boundary, or @type:edge tag.',
      'Write each tag on its own line. Never include spaces inside a tag.',
      'Use sequential scenario IDs based on the actual requirement ID, starting at 01.',
      'Indent each scenario declaration by two spaces and each Given, When, Then, And, or But step by four spaces.',
      'Include positive, negative, boundary, or edge scenarios only when supported by the requirement.',
      'Do not claim boundary or equivalence-partition coverage unless the scenario explicitly tests it.',
      '',
      `Requirement ID: ${requirement.requirement_id}`,
      `Requirement text: ${requirement.final_text}`,
    ].join('\n');

    const rawFeature = await generateWithLlm([
      {
        role: 'system',
        content: 'You generate conservative, traceable Gherkin acceptance scenarios.',
      },
      {
        role: 'user',
        content: prompt,
      },
    ]);

    const feature = stripMarkdownFence(rawFeature);
    const featureRelativePath =
      `c2/features/${requirement.requirement_id}.feature`;

    const validation = validateGherkin(feature);

    validationResults.push({
      requirement_id: requirement.requirement_id,
      feature_file: featureRelativePath,
      valid: validation.valid,
      ...(!validation.valid
        ? {
            error:
              validation.error ?? 'Unknown Gherkin parsing error',
          }
        : {}),
    });

    if (!validation.valid) {
      console.error(
        `[c2] Invalid Gherkin for ${requirement.requirement_id}: ${
          validation.error ?? 'Unknown parsing error'
        }`,
      );

      // Keep processing the remaining requirements.
      continue;
    }

    const requirementTag = `@${requirement.requirement_id}`;

    if (!feature.includes(requirementTag)) {
      throw new Error(
        `LLM output for ${requirement.requirement_id} is missing its requirement tag`,
      );
    }

    const featureName = parseFeatureName(
      feature,
      requirement.requirement_id,
    );

    const scenarioPattern =
      /^\s*(@SCN-[A-Z0-9]+-[0-9]{3,4}-[0-9]{2})\s*\r?\n\s*(@type:(positive|negative|boundary|edge))\s*\r?\n\s*(Scenario(?: Outline)?:\s*(.+))$/gm;

    const scenarios: Array<{
      scenario_id: string;
      scenario_type: string;
      scenario_name: string;
      is_outline: boolean;
      line: number;
    }> = [];

    let match: RegExpExecArray | null;

    while ((match = scenarioPattern.exec(feature)) !== null) {
      scenarios.push({
        scenario_id: match[1].slice(1),
        scenario_type: match[3],
        scenario_name: match[5].trim(),
        is_outline: match[4].startsWith('Scenario Outline:'),
        line: feature.slice(0, match.index).split('\n').length + 2,
      });
    }

    if (scenarios.length === 0) {
      console.warn(
        `[c2] No correctly tagged scenarios found for ${requirement.requirement_id}.`,
      );

      // Do not create feature or scenario metadata for unusable output.
      continue;
    }

    const featureAbsolutePath = path.join(
      featuresDir,
      `${requirement.requirement_id}.feature`,
    );

    fs.writeFileSync(featureAbsolutePath, `${feature}\n`, 'utf8');

    metadata.features.push({
      feature_file: featureRelativePath,
      requirement_id: requirement.requirement_id,
      feature_name: featureName,
      requirement_text_used: requirement.final_text,
    });

    for (const scenario of scenarios) {
      metadata.scenarios.push({
        scenario_id: scenario.scenario_id,
        requirement_id: requirement.requirement_id,
        feature_file: featureRelativePath,
        scenario_name: scenario.scenario_name,
        line: scenario.line,
        scenario_type: scenario.scenario_type,
        is_outline: scenario.is_outline,
        constraints: [],
        equivalence_partitions: [],
        boundary_values: [],
        ...(scenario.is_outline ? { examples: [] } : {}),
        generation: {
          mode: 'llm_only_baseline',
          regeneration_rounds: 0,
        },
        verification: {
          syntax: 'pass',
          requirement_consistency: { status: 'skipped' },
          ep_coverage: 'skipped',
          bva_coverage: 'skipped',
          completeness: 'skipped',
          fully_verified: false,
          notes:
            'Baseline generated; independent verification is still required.',
        },
      });
    }
  }

  const reportPath = writeValidationReport(
    c2Dir,
    input.run_id,
    validationResults,
  );

  fs.writeFileSync(
    path.join(c2Dir, 'scenario_metadata.json'),
    `${JSON.stringify(metadata, null, 2)}\n`,
    'utf8',
  );

  console.log(
    `[c2] Generated ${metadata.features.length} feature file(s) from ${readyRequirements.length} BDD-ready requirement(s).`,
  );

  console.log(
    `[c2] Syntax validation: ${
      validationResults.filter((result) => result.valid).length
    } valid, ${
      validationResults.filter((result) => !result.valid).length
    } invalid.`,
  );

  console.log(`[c2] Validation report: ${reportPath}`);
}
