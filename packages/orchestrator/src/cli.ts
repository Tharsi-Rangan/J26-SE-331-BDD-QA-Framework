#!/usr/bin/env node
// orch CLI entry point. Exit code 0 = success (docs/INTEGRATION_RULES.md section 4).
import fs from 'node:fs';
import path from 'node:path';
import { parseRunArgs } from './args.js';
import { run } from './index.js';

try {
  const options = parseRunArgs(process.argv.slice(2));
  fs.mkdirSync(options.out, { recursive: true });
  await run(options);
  process.exit(0);
} catch (err) {
  console.error('[orch] ' + (err instanceof Error ? err.message : String(err)));
  process.exit(1);
}
