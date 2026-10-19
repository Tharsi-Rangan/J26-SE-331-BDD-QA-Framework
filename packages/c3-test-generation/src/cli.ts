#!/usr/bin/env node
// c3 CLI entry point. Exit code 0 = success (docs/INTEGRATION_RULES.md section 4).
//   c3 run  --in runs/<RUN-ID> --subject-root <path> --out runs/<RUN-ID> [--no-model]
//   c3 scan --subject-root <path> --module lib/utils.js [--exports a,b] [--out scan.json]
//   c3 model-check   (sends one tiny prompt to the model in .env and prints the answer)
import fs from 'node:fs';
import path from 'node:path';
import { parseRunArgs, parseScanArgs } from './args.js';
import { modelCheck, run, scanCommand } from './index.js';
import { loadDotEnv } from './model/config.js';
import { createModelClient, readModelConfig, type ModelClient } from './model/index.js';

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
    // A model is used only when .env sets one; a wrong .env is an error, a missing one is not.
    let model: ModelClient | undefined;
    if (!options.noModel && process.env.LLM_BASE_URL) {
      const config = readModelConfig();
      model = createModelClient(config);
      console.log(`[c3] model ${model.modelTag} (cache ${config.cacheMode})`);
    } else {
      console.log('[c3] no model (--no-model or no LLM_BASE_URL): rule defaults only');
    }
    await run({ ...options, model });
  }
  process.exit(0);
} catch (err) {
  console.error('[c3] ' + (err instanceof Error ? err.message : String(err)));
  process.exit(1);
}
