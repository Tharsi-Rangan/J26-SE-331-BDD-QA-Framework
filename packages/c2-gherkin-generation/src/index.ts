import fs from 'node:fs';
import path from 'node:path';
import type { RunOptions } from './args.js';
import { generateWithLlm } from './llm-client.js';
import { AstBuilder, GherkinClassicTokenMatcher, Parser } from '@cucumber/gherkin';
import {
  IdGenerator,
  type GherkinDocument,
  type Scenario as GherkinScenario,
} from '@cucumber/messages';
import { validateGherkin } from './gherkin-validator.js';
import { extractNumericRanges, type ExtractedAnalysis } from './constraint-extractor.js';
import { buildVerificationResult, type ScenarioForVerification } from './verification-layers.js';
import { writeValidationReport, type FeatureValidationEntry } from './validation-report.js';

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

interface ParsedScenario {
  scenario_id: string;
  scenario_type: string;
  scenario_name: string;
  is_outline: boolean;
  line: number;
  start_line: number;
  end_line: number;
}

interface ParsedExampleRow {
  row_index: number;
  values: Record<string, unknown>;
}

interface ParsedExamplesBlock {
  name: string;
  headers: string[];
  rows: ParsedExampleRow[];
  insertion_line: number;
}

type GenerationMode = 'llm_only_baseline' | 'boundary_aware';

function getGenerationMode(): GenerationMode {
  const mode = process.env.C2_GENERATION_MODE ?? 'llm_only_baseline';

  if (mode !== 'llm_only_baseline' && mode !== 'boundary_aware') {
    throw new Error(
      `Unsupported C2_GENERATION_MODE "${mode}". ` +
        'Expected "llm_only_baseline" or "boundary_aware".',
    );
  }

  return mode;
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
    throw new Error(`LLM output for ${requirementId} has no Feature declaration`);
  }

  return match[1].trim();
}

function parseGherkinDocument(feature: string) {
  const builder = new AstBuilder(IdGenerator.uuid());
  const matcher = new GherkinClassicTokenMatcher();
  return new Parser(builder, matcher).parse(feature);
}

function getFeatureScenarios(document: GherkinDocument): GherkinScenario[] {
  const scenarios: GherkinScenario[] = [];

  for (const child of document.feature?.children ?? []) {
    if (child.scenario) scenarios.push(child.scenario);
    for (const ruleChild of child.rule?.children ?? []) {
      if (ruleChild.scenario) scenarios.push(ruleChild.scenario);
    }
  }

  return scenarios;
}

function parseExamplesBlocks(feature: string, scenario: ParsedScenario): ParsedExamplesBlock[] {
  if (!scenario.is_outline) return [];

  const document = parseGherkinDocument(feature);
  const parsedScenario = getFeatureScenarios(document).find(
    (item) => item.location.line === scenario.start_line + 1,
  );
  if (!parsedScenario) return [];

  return parsedScenario.examples.map((examples) => {
    const headers = examples.tableHeader?.cells.map((cell) => cell.value) ?? [];
    const body = examples.tableBody ?? [];
    const rows: ParsedExampleRow[] = body.map((row, rowIndex) => {
      const values: Record<string, unknown> = {};
      for (const [cellIndex, header] of headers.entries()) {
        const cell = row.cells[cellIndex].value;
        values[header] = /^-?\d+(?:\.\d+)?$/.test(cell) ? Number(cell) : cell;
      }
      return { row_index: rowIndex + 1, values };
    });
    const lastRow = body.at(-1) ?? examples.tableHeader;
    return {
      name: examples.name,
      headers,
      rows,
      insertion_line: lastRow?.location.line ?? examples.location.line,
    };
  });
}

function parseExampleRows(feature: string, scenario: ParsedScenario): ParsedExampleRow[] {
  let rowIndex = 0;
  return parseExamplesBlocks(feature, scenario).flatMap((block) =>
    block.rows.map((row) => ({ ...row, row_index: ++rowIndex })),
  );
}

function selectScenarioConstraints(
  feature: string,
  scenario: ParsedScenario,
  extracted: ExtractedAnalysis,
): ExtractedAnalysis {
  const scenarioLines = feature.split(/\r?\n/).slice(scenario.start_line, scenario.end_line);
  const placeholders = new Set(
    [...scenarioLines.join('\n').matchAll(/<([^<>]+)>/g)].map((match) => match[1].trim()),
  );
  const parsedExamples = parseExampleRows(feature, scenario);
  const blocks = parseExamplesBlocks(feature, scenario);
  const headers = new Set(blocks.flatMap((block) => block.headers));
  const selectedIds = new Set<string>();

  for (const constraint of extracted.constraints) {
    const hasPlaceholder = placeholders.has(constraint.parameter);
    const hasExampleColumn = headers.has(constraint.parameter);

    if (hasPlaceholder !== hasExampleColumn) {
      throw new Error(
        `Scenario ${scenario.scenario_id} has an incomplete input binding ` +
          `for constrained parameter "${constraint.parameter}"; ` +
          'the parameter must appear in both a step placeholder and an Examples column.',
      );
    }

    if (hasPlaceholder && hasExampleColumn) {
      selectedIds.add(constraint.constraint_id);
    }
  }

  return {
    constraints: extracted.constraints.filter((item) => selectedIds.has(item.constraint_id)),
    equivalence_partitions: extracted.equivalence_partitions.filter((item) =>
      selectedIds.has(item.constraint_id),
    ),
    boundary_values: extracted.boundary_values.filter((item) =>
      selectedIds.has(item.constraint_id),
    ),
  };
}

function addCoverageRows(
  feature: string,
  scenario: ParsedScenario,
  analysis: ExtractedAnalysis,
): string {
  if (!scenario.is_outline) {
    throw new Error(
      `Boundary-aware generation requires a Scenario Outline for ${scenario.scenario_id}.`,
    );
  }

  const lines = feature.split(/\r?\n/);
  const blocks = parseExamplesBlocks(feature, scenario);
  if (blocks.length === 0) {
    throw new Error(
      `Boundary-aware generation requires an Examples table for ${scenario.scenario_id}.`,
    );
  }

  const scenarioLines = lines.slice(scenario.start_line, scenario.end_line);
  const scenarioAst = getFeatureScenarios(parseGherkinDocument(feature)).find(
    (item) => item.location.line === scenario.start_line + 1,
  );
  const hasResultAssertion =
    scenarioAst?.steps.some((step, index, steps) => {
      const stepType = step.keyword.trim();
      const precedingStepType = steps
        .slice(0, index)
        .reverse()
        .map((prior) => prior.keyword.trim())
        .find((keyword) => !['And', 'But'].includes(keyword));
      const isThenAssertion =
        stepType === 'Then' || (['And', 'But'].includes(stepType) && precedingStepType === 'Then');
      if (!isThenAssertion) return false;
      const text = step.text.toLowerCase();
      return (
        /\b(?:result|outcome|status)\b.{0,40}\b(?:is|equals?|should be|must be)\b.{0,20}<result>/i.test(
          text,
        ) ||
        /<result>.{0,20}\b(?:is|equals?|should be|must be)\b.{0,40}\b(?:result|outcome|status)\b/i.test(
          text,
        )
      );
    }) ?? false;
  if (!hasResultAssertion) {
    throw new Error(
      `Boundary-aware generation requires a <result> assertion in ${scenario.scenario_id}.`,
    );
  }

  if (blocks.some((block) => !block.headers.includes('result') || block.rows.length === 0)) {
    throw new Error(
      `Boundary-aware generation requires a result column and at least one Examples row in every block for ${scenario.scenario_id}.`,
    );
  }

  const validRepresentatives = new Map<string, number>();
  for (const constraint of analysis.constraints) {
    const partition = analysis.equivalence_partitions.find(
      (candidate) =>
        candidate.constraint_id === constraint.constraint_id && candidate.validity === 'valid',
    );
    if (!partition || typeof partition.representative !== 'number') {
      throw new Error(
        `Boundary-aware generation has no valid EP representative for "${constraint.parameter}".`,
      );
    }
    validRepresentatives.set(constraint.constraint_id, partition.representative);
  }

  const insertions: Array<{ line: number; rows: string[] }> = [];

  for (const block of blocks) {
    const baseline = block.rows[0]?.values;
    if (!baseline || block.headers.some((header) => baseline[header] === undefined)) {
      throw new Error(
        `Boundary-aware generation cannot build complete Examples rows for ${scenario.scenario_id}.`,
      );
    }
    const knownRows = new Set(
      block.rows.map((row) =>
        block.headers.map((header) => String(row.values[header])).join('\u0000'),
      ),
    );
    const generatedRows: Record<string, unknown>[] = [];
    const addTargetRow = (constraintId: string, value: number, result: 'accepted' | 'rejected') => {
      const constraint = analysis.constraints.find((item) => item.constraint_id === constraintId);
      if (!constraint || !block.headers.includes(constraint.parameter)) return;
      const values: Record<string, unknown> = { ...baseline };
      for (const otherConstraint of analysis.constraints) {
        if (otherConstraint.constraint_id === constraintId) continue;
        if (!block.headers.includes(otherConstraint.parameter)) {
          throw new Error(
            `Examples block "${block.name}" cannot isolate constrained parameter "${constraint.parameter}".`,
          );
        }
        const representative = validRepresentatives.get(otherConstraint.constraint_id);
        if (representative === undefined)
          throw new Error(
            `Boundary-aware generation has no valid representative for "${otherConstraint.parameter}".`,
          );
        values[otherConstraint.parameter] = representative;
      }
      values[constraint.parameter] = value;
      values.result = result;
      const key = block.headers.map((header) => String(values[header])).join('\u0000');
      if (!knownRows.has(key)) {
        knownRows.add(key);
        generatedRows.push(values);
      }
    };
    for (const partition of analysis.equivalence_partitions) {
      if (typeof partition.representative !== 'number') continue;
      addTargetRow(
        partition.constraint_id,
        partition.representative,
        partition.validity === 'valid' ? 'accepted' : 'rejected',
      );
    }
    for (const boundary of analysis.boundary_values) {
      addTargetRow(
        boundary.constraint_id,
        boundary.value,
        boundary.expected === 'accept' ? 'accepted' : 'rejected',
      );
    }
    const renderedRows = generatedRows.map((values) => {
      const cells = block.headers.map((header) => {
        const value = String(values[header]);
        if (/[|\r\n]/.test(value))
          throw new Error(
            `Boundary-aware generation cannot safely write "${header}" in ${scenario.scenario_id}.`,
          );
        return value;
      });
      return `      | ${cells.join(' | ')} |`;
    });
    if (renderedRows.length > 0)
      insertions.push({ line: block.insertion_line, rows: renderedRows });
  }

  for (const insertion of insertions.sort((a, b) => b.line - a.line)) {
    lines.splice(insertion.line, 0, ...insertion.rows);
  }
  return lines.join('\n');
}

function parseScenarios(feature: string): ParsedScenario[] {
  const lines = feature.split(/\r?\n/);
  const scenarios: ParsedScenario[] = [];

  const scenarioIdPattern = /^\s*@(SCN-[A-Z0-9]+-[0-9]{3,4}-[0-9]{2})\s*$/;

  const scenarioTypePattern = /^\s*@type:(positive|negative|boundary|edge)\s*$/;

  const declarationPattern = /^\s*(Scenario(?: Outline)?:)\s*(.+?)\s*$/;

  for (let index = 0; index < lines.length; index += 1) {
    const idMatch = lines[index].match(scenarioIdPattern);

    if (!idMatch) continue;

    let typeIndex = -1;
    let declarationIndex = -1;

    // Allow blank lines between the ID tag, type tag, and declaration.
    for (let next = index + 1; next < lines.length && next <= index + 4; next += 1) {
      if (!lines[next].trim()) continue;

      if (typeIndex < 0) {
        if (!scenarioTypePattern.test(lines[next])) break;

        typeIndex = next;
        continue;
      }

      if (!declarationPattern.test(lines[next])) break;

      declarationIndex = next;
      break;
    }

    if (typeIndex < 0 || declarationIndex < 0) continue;

    const typeMatch = lines[typeIndex].match(scenarioTypePattern);
    const declarationMatch = lines[declarationIndex].match(declarationPattern);

    if (!typeMatch || !declarationMatch) continue;

    let endLine = lines.length;

    for (let next = declarationIndex + 1; next < lines.length; next += 1) {
      if (
        scenarioIdPattern.test(lines[next]) ||
        /^\s*Scenario(?: Outline)?:\s*/.test(lines[next]) ||
        /^\s*Rule:\s*/.test(lines[next])
      ) {
        endLine = next;
        break;
      }
    }

    scenarios.push({
      scenario_id: idMatch[1],
      scenario_type: typeMatch[1],
      scenario_name: declarationMatch[2].trim(),
      is_outline: declarationMatch[1] === 'Scenario Outline:',
      line: declarationIndex + 1,
      start_line: declarationIndex,
      end_line: endLine,
    });

    index = declarationIndex;
  }

  return scenarios;
}

function validateScenarioTrace(
  feature: string,
  requirementId: string,
  scenarios: ParsedScenario[],
): void {
  const lines = feature.split(/\r?\n/);
  const requirementTag = `@${requirementId}`;
  const requirementTagIndexes = lines.flatMap((line, index) =>
    line.trim() === requirementTag ? [index] : [],
  );
  const featureIndex = lines.findIndex((line) => /^\s*Feature\s*:/i.test(line));
  let nextNonEmptyLineAfterTag = (requirementTagIndexes[0] ?? -1) + 1;
  while (nextNonEmptyLineAfterTag < lines.length && !lines[nextNonEmptyLineAfterTag].trim()) {
    nextNonEmptyLineAfterTag += 1;
  }

  if (
    requirementTagIndexes.length !== 1 ||
    featureIndex < 0 ||
    nextNonEmptyLineAfterTag !== featureIndex
  ) {
    throw new Error(
      `LLM output for ${requirementId} must place exactly one requirement tag immediately before Feature`,
    );
  }

  const declaredScenarioCount = lines.filter((line) =>
    /^\s*Scenario(?: Outline)?:/.test(line),
  ).length;

  if (scenarios.length !== declaredScenarioCount) {
    throw new Error(
      `LLM output for ${requirementId} has ${declaredScenarioCount} scenario declaration(s), ` +
        `but only ${scenarios.length} have valid C2 scenario tags.`,
    );
  }

  const scenarioIds = new Set(scenarios.map((scenario) => scenario.scenario_id));
  if (scenarioIds.size !== scenarios.length) {
    throw new Error(`LLM output for ${requirementId} contains duplicate scenario IDs`);
  }

  const expectedScenarioPrefix = `SCN-${requirementId.slice('REQ-'.length)}-`;
  const mismatchedScenario = scenarios.find(
    (scenario) => !scenario.scenario_id.startsWith(expectedScenarioPrefix),
  );

  if (mismatchedScenario) {
    throw new Error(
      `Scenario ${mismatchedScenario.scenario_id} does not belong to requirement ${requirementId}`,
    );
  }
}

function assignExampleReferences(
  examples: ParsedExampleRow[],
  constraints: Array<{ constraint_id: string; parameter: string }>,
  partitions: Array<{
    partition_id: string;
    constraint_id: string;
    representative: unknown;
  }>,
  boundaries: Array<{
    boundary_id: string;
    constraint_id: string;
    value: unknown;
  }>,
): Array<
  ParsedExampleRow & {
    boundary_ref?: string;
    partition_ref?: string;
  }
> {
  return examples.map((example) => {
    let boundaryRef: string | undefined;
    let partitionRef: string | undefined;

    for (const constraint of constraints) {
      const value = example.values[constraint.parameter];

      if (value === undefined) continue;

      const boundary = boundaries.find(
        (candidate) =>
          candidate.constraint_id === constraint.constraint_id && candidate.value === value,
      );

      const partition = partitions.find(
        (candidate) =>
          candidate.constraint_id === constraint.constraint_id &&
          candidate.representative === value,
      );

      if (boundary) boundaryRef = boundary.boundary_id;
      if (partition) partitionRef = partition.partition_id;
    }

    return {
      ...example,
      ...(boundaryRef ? { boundary_ref: boundaryRef } : {}),
      ...(partitionRef ? { partition_ref: partitionRef } : {}),
    };
  });
}

export async function run(options: RunOptions): Promise<void> {
  const inputDir = options.in ?? options.out;
  const input = readRequirements(inputDir);

  const readyRequirements = input.requirements.filter((requirement) => requirement.bdd_ready);

  if (readyRequirements.length === 0) {
    throw new Error('No BDD-ready requirements found in C1 input');
  }

  const model = process.env.LLM_MODEL;
  const generationMode = getGenerationMode();

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
    const extracted = extractNumericRanges(requirement.final_text);
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
      ...(generationMode === 'boundary_aware' && extracted.constraints.length > 0
        ? [
            'Create a Scenario Outline with a step placeholder and Examples column for every numeric parameter listed below.',
            'Include a result Examples column and assert <result> in a Then step. C2 will complete the numeric EP and BVA rows.',
            `Explicit numeric constraints: ${extracted.constraints
              .map(
                (constraint) => `${constraint.parameter}: ${constraint.min} to ${constraint.max}`,
              )
              .join('; ')}.`,
          ]
        : [
            'For explicit numeric ranges, prefer a Scenario Outline with Examples rows covering values below, at, and above each limit.',
          ]),
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

    let feature = stripMarkdownFence(rawFeature);
    const featureRelativePath = `c2/features/${requirement.requirement_id}.feature`;

    const validation = validateGherkin(feature);

    validationResults.push({
      requirement_id: requirement.requirement_id,
      feature_file: featureRelativePath,
      valid: validation.valid,
      ...(!validation.valid
        ? {
            error: validation.error ?? 'Unknown Gherkin parsing error',
          }
        : {}),
    });

    if (!validation.valid) {
      console.error(
        `[c2] Invalid Gherkin for ${requirement.requirement_id}: ${
          validation.error ?? 'Unknown parsing error'
        }`,
      );
      continue;
    }

    const requirementTags = [...feature.matchAll(/^\s*@(REQ-[A-Z0-9]+-[0-9]{3,4})\s*$/gm)].map(
      (match) => match[1],
    );

    if (requirementTags.length !== 1 || requirementTags[0] !== requirement.requirement_id) {
      throw new Error(
        `LLM output for ${requirement.requirement_id} is missing its requirement tag or contains mismatched/duplicate requirement tags`,
      );
    }

    const featureName = parseFeatureName(feature, requirement.requirement_id);

    let scenarios = parseScenarios(feature);

    if (scenarios.length === 0) {
      console.warn(`[c2] No correctly tagged scenarios found for ${requirement.requirement_id}.`);
      continue;
    }

    validateScenarioTrace(feature, requirement.requirement_id, scenarios);

    const featureAbsolutePath = path.join(featuresDir, `${requirement.requirement_id}.feature`);

    let scenarioAnalyses = scenarios.map((scenario) =>
      selectScenarioConstraints(feature, scenario, extracted),
    );
    const associatedConstraintIds = new Set(
      scenarioAnalyses.flatMap((analysis) =>
        analysis.constraints.map((constraint) => constraint.constraint_id),
      ),
    );
    const unassociatedConstraints = extracted.constraints.filter(
      (constraint) => !associatedConstraintIds.has(constraint.constraint_id),
    );

    if (unassociatedConstraints.length > 0) {
      throw new Error(
        `Numeric constraints could not be associated with a scenario input: ${unassociatedConstraints
          .map((constraint) => constraint.parameter)
          .join(', ')}.`,
      );
    }

    if (generationMode === 'boundary_aware') {
      for (let index = scenarios.length - 1; index >= 0; index -= 1) {
        if (scenarioAnalyses[index].constraints.length === 0) continue;
        feature = addCoverageRows(feature, scenarios[index], scenarioAnalyses[index]);
      }

      scenarios = parseScenarios(feature);
      scenarioAnalyses = scenarios.map((scenario) =>
        selectScenarioConstraints(feature, scenario, extracted),
      );

      const finalValidation = validateGherkin(feature);
      if (!finalValidation.valid) {
        validationResults[validationResults.length - 1] = {
          requirement_id: requirement.requirement_id,
          feature_file: featureRelativePath,
          valid: false,
          error: finalValidation.error ?? 'Unknown parsing error after boundary augmentation',
        };
        console.error(
          `[c2] Invalid Gherkin after boundary augmentation for ${requirement.requirement_id}: ${finalValidation.error ?? 'Unknown parsing error'}`,
        );
        continue;
      }
    }

    fs.writeFileSync(featureAbsolutePath, `${feature}\n`, 'utf8');

    metadata.features.push({
      feature_file: featureRelativePath,
      requirement_id: requirement.requirement_id,
      feature_name: featureName,
      requirement_text_used: requirement.final_text,
    });

    for (const [scenarioIndex, scenario] of scenarios.entries()) {
      const scenarioAnalysis = scenarioAnalyses[scenarioIndex];
      const parsedExamples = parseExampleRows(feature, scenario);

      const examples = assignExampleReferences(
        parsedExamples,
        scenarioAnalysis.constraints,
        scenarioAnalysis.equivalence_partitions,
        scenarioAnalysis.boundary_values,
      );

      const scenarioForVerification: ScenarioForVerification = {
        scenario_id: scenario.scenario_id,
        requirement_id: requirement.requirement_id,
        scenario_name: scenario.scenario_name,
        scenario_type: scenario.scenario_type,
        is_outline: scenario.is_outline,
        constraints: scenarioAnalysis.constraints,
        equivalence_partitions: scenarioAnalysis.equivalence_partitions,
        boundary_values: scenarioAnalysis.boundary_values,
        ...(scenario.is_outline ? { examples } : {}),
        verification: {
          syntax: 'pass',
          requirement_consistency: { status: 'skipped' },
          ep_coverage: 'skipped',
          bva_coverage: 'skipped',
          completeness: 'skipped',
          fully_verified: false,
        },
      };

      const verification = buildVerificationResult(scenarioForVerification, feature);

      metadata.scenarios.push({
        scenario_id: scenario.scenario_id,
        requirement_id: requirement.requirement_id,
        feature_file: featureRelativePath,
        scenario_name: scenario.scenario_name,
        line: scenario.line,
        scenario_type: scenario.scenario_type,
        is_outline: scenario.is_outline,
        constraints: scenarioForVerification.constraints,
        equivalence_partitions: scenarioForVerification.equivalence_partitions,
        boundary_values: scenarioForVerification.boundary_values,
        ...(scenario.is_outline ? { examples: scenarioForVerification.examples ?? [] } : {}),
        generation: {
          mode:
            generationMode === 'boundary_aware' && scenarioAnalysis.constraints.length > 0
              ? 'boundary_aware'
              : 'llm_only_baseline',
          regeneration_rounds: 0,
        },
        verification: {
          syntax: 'pass',
          requirement_consistency: {
            status: verification.requirement_consistency.status,
          },
          ep_coverage: verification.ep_coverage,
          bva_coverage: verification.bva_coverage,
          completeness: verification.completeness,
          fully_verified: verification.fully_verified,
          notes: verification.notes.join(' '),
        },
      });
    }
  }

  const reportPath = writeValidationReport(c2Dir, input.run_id, validationResults);

  if (metadata.features.length === 0 || metadata.scenarios.length === 0) {
    throw new Error(`No usable C2 scenarios were generated. Validation report: ${reportPath}`);
  }

  fs.writeFileSync(
    path.join(c2Dir, 'scenario_metadata.json'),
    `${JSON.stringify(metadata, null, 2)}\n`,
    'utf8',
  );

  console.log(
    `[c2] Generated ${metadata.features.length} feature file(s) from ${readyRequirements.length} BDD-ready requirement(s).`,
  );

  console.log(
    `[c2] Syntax validation: ${validationResults.filter((result) => result.valid).length} valid, ${
      validationResults.filter((result) => !result.valid).length
    } invalid.`,
  );

  console.log(`[c2] Validation report: ${reportPath}`);
}
