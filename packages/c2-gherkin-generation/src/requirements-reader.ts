import fs from 'node:fs';
import path from 'node:path';

export interface ReadyRequirement {
  requirement_id: string;
  final_text: string;
}

interface C1Requirement {
  requirement_id?: unknown;
  final_text?: unknown;
  bdd_ready?: unknown;
}

interface C1ValidatedRequirements {
  contract?: unknown;
  requirements?: unknown;
}

/**
 * Read the C1 validated-requirements file and return only BDD-ready items.
 * C2 uses final_text, never original_text or candidate text.
 */
export function readReadyRequirements(inputDir: string): ReadyRequirement[] {
  const inputPath = path.join(inputDir, 'c1', 'validated_requirements.json');

  if (!fs.existsSync(inputPath)) {
    throw new Error(`C1 validated requirements file not found: ${inputPath}`);
  }

  let data: C1ValidatedRequirements;

  try {
    data = JSON.parse(fs.readFileSync(inputPath, 'utf8')) as C1ValidatedRequirements;
  } catch {
    throw new Error(`Invalid JSON in C1 validated requirements file: ${inputPath}`);
  }

  if (data.contract !== 'c1.validated-requirements') {
    throw new Error('Unexpected C1 contract identifier');
  }

  if (!Array.isArray(data.requirements)) {
    throw new Error('C1 requirements must be an array');
  }

  const ready: ReadyRequirement[] = [];

  for (const item of data.requirements as C1Requirement[]) {
    if (item.bdd_ready !== true) {
      continue;
    }

    if (
      typeof item.requirement_id !== 'string' ||
      typeof item.final_text !== 'string' ||
      item.final_text.trim().length === 0
    ) {
      throw new Error('A BDD-ready requirement must have requirement_id and non-empty final_text');
    }

    ready.push({
      requirement_id: item.requirement_id,
      final_text: item.final_text,
    });
  }

  return ready;
}
