export interface ExtractedConstraint {
  constraint_id: string;
  parameter: string;
  kind: 'range';
  data_type: 'integer' | 'number';
  min: number;
  max: number;
  min_inclusive: boolean;
  max_inclusive: boolean;
  step: number;
  source_phrase: string;
}

export interface ExtractedPartition {
  partition_id: string;
  constraint_id: string;
  validity: 'valid' | 'invalid';
  description: string;
  representative: number;
}

export interface ExtractedBoundary {
  boundary_id: string;
  constraint_id: string;
  position: 'below_min' | 'min' | 'above_min' | 'below_max' | 'max' | 'above_max';
  value: number;
  expected: 'accept' | 'reject';
}

export interface ExtractedAnalysis {
  constraints: ExtractedConstraint[];
  equivalence_partitions: ExtractedPartition[];
  boundary_values: ExtractedBoundary[];
}

interface NumericRangeMatch {
  parameter: string;
  min: number;
  max: number;
  sourcePhrase: string;
}

const NUMBER = String.raw`-?\d+(?:\.\d+)?`;

const RANGE_PHRASE = String.raw`(?:between\s+(?<betweenMin>${NUMBER})(?:\s*(?:\(\s*(?<betweenMinParenInclusivity>inclusive|exclusively|exclusive)\s*\)|\s+(?<betweenMinInclusivity>inclusive|exclusively|exclusive)))?\s+and\s+(?<betweenMax>${NUMBER})(?:\s*\(\s*(?<betweenMaxInclusivity>inclusive|exclusively|exclusive)\s*\))?|from\s+(?<fromMin>${NUMBER})(?:\s*(?:\(\s*(?<fromMinParenInclusivity>inclusive|exclusively|exclusive)\s*\)|\s+(?<fromMinInclusivity>inclusive|exclusively|exclusive)))?\s+to\s+(?<fromMax>${NUMBER})(?:\s*\(\s*(?<fromMaxInclusivity>inclusive|exclusively|exclusive)\s*\))?)(?:\s*,?\s*(?<inclusivity>inclusive|exclusively|exclusive))?`;

const PARAMETER_PATTERN = String.raw`[a-z][a-z0-9_]*`;

function emptyAnalysis(): ExtractedAnalysis {
  return {
    constraints: [],
    equivalence_partitions: [],
    boundary_values: [],
  };
}

function getRangeInclusivity(match: RegExpMatchArray): { min: boolean; max: boolean } {
  const groups = match.groups ?? {};
  const rangeQualifier = groups.inclusivity;
  const minQualifier =
    rangeQualifier ??
    groups.betweenMinParenInclusivity ??
    groups.betweenMinInclusivity ??
    groups.fromMinParenInclusivity ??
    groups.fromMinInclusivity;
  const maxQualifier = rangeQualifier ?? groups.betweenMaxInclusivity ?? groups.fromMaxInclusivity;
  const isInclusive = (qualifier: string | undefined): boolean =>
    qualifier !== 'exclusive' && qualifier !== 'exclusively';

  return {
    min: isInclusive(minQualifier),
    max: isInclusive(maxQualifier),
  };
}

function createAnalysis(
  parameter: string,
  min: number,
  max: number,
  constraintId: string,
  sourcePhrase: string,
  minInclusive = true,
  maxInclusive = true,
): ExtractedAnalysis {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min >= max) {
    return emptyAnalysis();
  }

  const integerRange = Number.isInteger(min) && Number.isInteger(max);

  const step = integerRange ? 1 : 0.01;

  const lowestValidValue = minInclusive ? min : min + step;
  const highestValidValue = maxInclusive ? max : max - step;

  if (lowestValidValue > highestValidValue) {
    throw new Error(
      `The range for "${parameter}" contains no representable valid value at step ${step}.`,
    );
  }

  const constraint: ExtractedConstraint = {
    constraint_id: constraintId,
    parameter,
    kind: 'range',
    data_type: integerRange ? 'integer' : 'number',
    min,
    max,
    min_inclusive: minInclusive,
    max_inclusive: maxInclusive,
    step,
    source_phrase: sourcePhrase,
  };

  // Keep the representative inside the valid interval.
  const validRepresentative = integerRange
    ? lowestValidValue + Math.floor((highestValidValue - lowestValidValue) / 2)
    : lowestValidValue + (highestValidValue - lowestValidValue) / 2;
  const isValid = (value: number): boolean =>
    (minInclusive ? value >= min : value > min) && (maxInclusive ? value <= max : value < max);

  const equivalencePartitions: ExtractedPartition[] = [
    {
      partition_id: 'EP-01',
      constraint_id: constraintId,
      validity: 'invalid',
      description: `${parameter} ${minInclusive ? '<' : '<='} ${min}`,
      representative: minInclusive ? min - step : min,
    },
    {
      partition_id: 'EP-02',
      constraint_id: constraintId,
      validity: 'valid',
      description: `${min} ${minInclusive ? '<=' : '<'} ${parameter} ${maxInclusive ? '<=' : '<'} ${max}`,
      representative: validRepresentative,
    },
    {
      partition_id: 'EP-03',
      constraint_id: constraintId,
      validity: 'invalid',
      description: `${parameter} ${maxInclusive ? '>' : '>='} ${max}`,
      representative: maxInclusive ? max + step : max,
    },
  ];

  const boundaryValues: ExtractedBoundary[] = [
    {
      boundary_id: 'BV-01',
      constraint_id: constraintId,
      position: 'below_min',
      value: min - step,
      expected: isValid(min - step) ? 'accept' : 'reject',
    },
    {
      boundary_id: 'BV-02',
      constraint_id: constraintId,
      position: 'min',
      value: min,
      expected: isValid(min) ? 'accept' : 'reject',
    },
    {
      boundary_id: 'BV-03',
      constraint_id: constraintId,
      position: 'above_min',
      value: min + step,
      expected: isValid(min + step) ? 'accept' : 'reject',
    },
    {
      boundary_id: 'BV-04',
      constraint_id: constraintId,
      position: 'below_max',
      value: max - step,
      expected: isValid(max - step) ? 'accept' : 'reject',
    },
    {
      boundary_id: 'BV-05',
      constraint_id: constraintId,
      position: 'max',
      value: max,
      expected: isValid(max) ? 'accept' : 'reject',
    },
    {
      boundary_id: 'BV-06',
      constraint_id: constraintId,
      position: 'above_max',
      value: max + step,
      expected: isValid(max + step) ? 'accept' : 'reject',
    },
  ];

  return {
    constraints: [constraint],
    equivalence_partitions: equivalencePartitions,
    boundary_values: boundaryValues,
  };
}

/**
 * Extract a numeric range explicitly associated with the given parameter.
 *
 * Supported examples:
 * - "age must be from 18 to 65"
 * - "quantity must be between 1 and 100"
 * - "age between 18 and 65"
 *
 * Searches are limited to the parameter's clause. This is a lightweight
 * heuristic, not a complete natural-language parser.
 */
export function extractNumericRange(requirementText: string, parameter: string): ExtractedAnalysis {
  const normalizedParameter = parameter.toLowerCase();

  if (!new RegExp(`^${PARAMETER_PATTERN}$`, 'i').test(parameter)) {
    throw new Error(
      `Unsupported parameter name "${parameter}". ` +
        'Expected a simple identifier containing letters, numbers, or underscores.',
    );
  }

  const escapedParameter = normalizedParameter.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  const rangePattern = new RegExp(
    String.raw`\b${escapedParameter}\b` +
      String.raw`(?:\s+(?:must|should|shall)\s+be|\s+is|\s+of)?` +
      String.raw`\s*${RANGE_PHRASE}(?=$|[^a-z0-9_])`,
    'gi',
  );

  const matches = [...requirementText.matchAll(rangePattern)];

  if (matches.length === 0) {
    return emptyAnalysis();
  }

  if (matches.length > 1) {
    throw new Error(
      `Multiple numeric ranges were associated with parameter "${parameter}". ` +
        'The requirement must be disambiguated before extraction.',
    );
  }

  const match = matches[0];
  const min = Number(match.groups?.betweenMin ?? match.groups?.fromMin);
  const max = Number(match.groups?.betweenMax ?? match.groups?.fromMax);

  if (!Number.isFinite(min) || !Number.isFinite(max) || min >= max) {
    throw new Error(
      `Invalid numeric range for parameter "${parameter}": ` +
        `"${match[0]}". The minimum must be less than the maximum.`,
    );
  }

  const inclusivity = getRangeInclusivity(match);

  return createAnalysis(
    normalizedParameter,
    min,
    max,
    'CON-01',
    match[0].trim(),
    inclusivity.min,
    inclusivity.max,
  );
}

/**
 * Extract explicitly associated numeric parameter/range pairs.
 *
 * A range must follow its parameter in the same local expression.
 * The extractor deliberately does not search ahead across arbitrary
 * text to guess which parameter owns a range.
 */
export function extractNumericRanges(requirementText: string): ExtractedAnalysis {
  const constraints: ExtractedConstraint[] = [];
  const equivalencePartitions: ExtractedPartition[] = [];
  const boundaryValues: ExtractedBoundary[] = [];

  const pattern = new RegExp(
    String.raw`\b(${PARAMETER_PATTERN})\b` +
      String.raw`(?:\s+(?:must|should|shall)\s+be|\s+is|\s+of)?` +
      String.raw`\s*${RANGE_PHRASE}(?=$|[^a-z0-9_])`,
    'gi',
  );

  const matches = [...requirementText.matchAll(pattern)];

  // Every detected range phrase must belong to one explicit parameter match.
  // This also catches an unassociated range when another range was matched.
  const rangePhrases = [
    ...requirementText.matchAll(new RegExp(String.raw`\b${RANGE_PHRASE}(?=$|[^a-z0-9_])`, 'gi')),
  ];
  const unassociatedRange = rangePhrases.find((rangePhrase) => {
    const phraseStart = rangePhrase.index ?? 0;
    const phraseEnd = phraseStart + rangePhrase[0].length;

    return !matches.some((match) => {
      const matchStart = match.index ?? 0;
      const matchEnd = matchStart + match[0].length;
      return matchStart <= phraseStart && matchEnd >= phraseEnd;
    });
  });

  if (unassociatedRange) {
    throw new Error(
      'A numeric range was found, but it could not be explicitly ' +
        'associated with a parameter. Clarify the requirement before extraction.',
    );
  }

  const seenParameters = new Set<string>();

  for (const match of matches) {
    const parameter = match[1].toLowerCase();

    if (
      [
        'a',
        'an',
        'be',
        'between',
        'from',
        'has',
        'have',
        'is',
        'must',
        'of',
        'should',
        'shall',
        'the',
        'to',
        'user',
      ].includes(parameter)
    ) {
      continue;
    }

    if (seenParameters.has(parameter)) {
      throw new Error(
        `Parameter "${parameter}" has multiple extracted numeric ranges. ` +
          'Disambiguate the requirement before extraction.',
      );
    }

    const min = Number(match.groups?.betweenMin ?? match.groups?.fromMin);
    const max = Number(match.groups?.betweenMax ?? match.groups?.fromMax);

    if (!Number.isFinite(min) || !Number.isFinite(max) || min >= max) {
      throw new Error(`Invalid numeric range associated with "${parameter}": "${match[0]}".`);
    }

    seenParameters.add(parameter);

    const constraintId = `CON-${String(constraints.length + 1).padStart(2, '0')}`;

    const inclusivity = getRangeInclusivity(match);
    const analysis = createAnalysis(
      parameter,
      min,
      max,
      constraintId,
      match[0].trim(),
      inclusivity.min,
      inclusivity.max,
    );

    constraints.push(...analysis.constraints);

    for (const partition of analysis.equivalence_partitions) {
      equivalencePartitions.push({
        ...partition,
        partition_id: `EP-${String(equivalencePartitions.length + 1).padStart(2, '0')}`,
      });
    }

    for (const boundary of analysis.boundary_values) {
      boundaryValues.push({
        ...boundary,
        boundary_id: `BV-${String(boundaryValues.length + 1).padStart(2, '0')}`,
      });
    }
  }

  return {
    constraints,
    equivalence_partitions: equivalencePartitions,
    boundary_values: boundaryValues,
  };
}
