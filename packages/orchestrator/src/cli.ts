#!/usr/bin/env node
// orch CLI entry point. Exit code 0 = success (docs/INTEGRATION_RULES.md section 4).
import { parseRunArgs } from './args.js';
import { run } from './index.js';

try {
  const options = parseRunArgs(process.argv.slice(2));
  await run(options);
  process.exit(0);
} catch (err) {
  console.error('[orch] ' + (err instanceof Error ? err.message : String(err)));
  process.exit(1);
}
