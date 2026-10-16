#!/usr/bin/env node
// c3 CLI entry point. Exit code 0 = success (docs/INTEGRATION_RULES.md section 4).
//   c3 run  --in runs/<RUN-ID> --subject-root <path> --out runs/<RUN-ID>
//   c3 scan --subject-root <path> --module lib/utils.js [--exports a,b] [--out scan.json]
//   c3 model-check   (sends one tiny prompt to the model in .env and prints the answer)
import fs from 'node:fs';
import path from 'node:path';
import { parseRunArgs, parseScanArgs } from './args.js';
import { modelCheck, run, scanCommand } from './index.js';
import { loadDotEnv } from './model/config.js';

try {
  const argv = process.argv.slice(2);
  const envFile = loadDotEnv();
  if (envFile) console.log(`[c3] settings from ${envFile}`);
  if (argv[0] === 'model-check') {
    await modelCheck();
  } else if (argv[0] === 'scan') {
    scanCommand(parseScanArgs(argv));
  } else {
    const options = parseRunArgs(argv);
    fs.mkdirSync(path.join(options.out, 'c3'), { recursive: true });
    await run(options);
  }
  process.exit(0);
} catch (err) {
  console.error('[c3] ' + (err instanceof Error ? err.message : String(err)));
  process.exit(1);
}
