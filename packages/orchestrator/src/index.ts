import type { RunOptions } from './args.js';

export type { RunOptions } from './args.js';

/**
 * Pipeline orchestrator (run folder, run_id, validation).
 * Skeleton only: replace this body with the real pipeline (see README for task order).
 */
export async function run(options: RunOptions): Promise<void> {
  console.log('[orch] skeleton run', options);
}
