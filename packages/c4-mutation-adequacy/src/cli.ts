#!/usr/bin/env node
// c4 CLI entry point. Exit code 0 = success (docs/INTEGRATION_RULES.md section 4).
import fs from 'node:fs';
import path from 'node:path';
import { parseRunArgs } from './args.js';
import { run } from './index.js';

try {
  const options = parseRunArgs(process.argv.slice(2));
  fs.mkdirSync(path.join(options.out, 'c4'), { recursive: true });
  await run(options);
  process.exit(0);
} catch (err) {
  console.error('[c4] ' + (err instanceof Error ? err.message : String(err)));
  process.exit(1);
}
