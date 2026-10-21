#!/usr/bin/env node
// c3 CLI entry point. Exit code 0 = success (docs/INTEGRATION_RULES.md section 4).
//   c3 run  --in runs/<RUN-ID> --subject-root <path> --out runs/<RUN-ID> [--no-model]
//   c3 scan --subject-root <path> --module lib/utils.js [--exports a,b] [--out scan.json]
//   c3 model-check   (sends one tiny prompt to the model in .env and prints the answer)
//   c3 pilot --run runs/<RUN-ID> --buggy <path> --fixed <path> [--label Express-5] [--open]   (C3-14)
//   c3 report --run runs/<RUN-ID> [--open]                         (C3-16: one run page)
//   c3 report --index runs [--runs a,b] [--title <text>] [--open]  (C3-16: batch page + every run page)
//   --open on run / pilot / report opens the HTML report in the browser
import fs from 'node:fs';
import path from 'node:path';
import { parsePilotArgs, parseReportArgs, parseRunArgs, parseScanArgs } from './args.js';
import { modelCheck, run, scanCommand } from './index.js';
import { loadDotEnv } from './model/config.js';
import { pilot } from './pilot.js';
import { REPORT_FILE, writeBatchReport, writeRunReport } from './report/html.js';
import { openFile } from './report/open.js';
import { createModelClient, readModelConfig, type ModelClient } from './model/index.js';

try {
  const argv = process.argv.slice(2);
  const envFile = loadDotEnv();
  if (envFile) console.log(`[c3] settings from ${envFile}`);
  if (argv[0] === 'model-check') {
    await modelCheck();
  } else if (argv[0] === 'pilot') {
    const o = parsePilotArgs(argv);
    pilot(o);
    if (o.open) openFile(path.join(o.run, REPORT_FILE));
  } else if (argv[0] === 'report') {
    const o = parseReportArgs(argv);
    let file: string;
    if (o.index) {
      const r = writeBatchReport(o.index, { runs: o.runs, title: o.title });
      for (const m of r.missing) console.log(`[c3] skipped ${m}: no finished c3 run there`);
      console.log(
        `[c3] ${r.runs.length} run page(s) written (c3/c3_report.html in each run folder)`,
      );
      file = r.file;
    } else {
      file = writeRunReport(o.run!);
    }
    console.log(`[c3] HTML report (C3-16): ${file}`);
    if (o.open) openFile(file);
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
    const report = path.join(options.out, REPORT_FILE);
    if (options.open && fs.existsSync(report)) openFile(report);
  }
  process.exit(0);
} catch (err) {
  console.error('[c3] ' + (err instanceof Error ? err.message : String(err)));
  process.exit(1);
}
