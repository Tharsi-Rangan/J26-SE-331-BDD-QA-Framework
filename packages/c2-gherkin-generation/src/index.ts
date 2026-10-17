import type { RunOptions } from './args.js';
import { readReadyRequirements } from './requirements-reader.js';

export type { RunOptions } from './args.js';

/**
 * C2: Boundary-Aware Gherkin Scenario Generation.
 *
 * C2-03 currently reads the validated requirements produced by C1.
 * Only requirements marked bdd_ready=true are accepted, and C2 uses
 * final_text as the approved requirement wording.
 */
export async function run(options: RunOptions): Promise<void> {
  if (!options.in) {
    throw new Error(
      'C2 requires --in pointing to a run folder containing c1/validated_requirements.json',
    );
  }

  const requirements = readReadyRequirements(options.in);

  console.log(`[c2] Read ${requirements.length} BDD-ready requirement(s).`);

  for (const requirement of requirements) {
    console.log(`[c2] ${requirement.requirement_id}: ${requirement.final_text}`);
  }
}
