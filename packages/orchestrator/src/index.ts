import fs from 'node:fs';
import path from 'node:path';
import type { RunOptions } from './args.js';
import {
  createRunFolder,
  defaultSubjectManifest,
  displayPath,
  repoRoot,
  resolveRunFolder,
  seedFromInput,
  validateRunFolder,
  type SeedResult,
} from './runfolder.js';

export type { RunOptions } from './args.js';
export * from './runfolder.js';

export const ORCH_VERSION = '0.1.0';

export interface RunResult {
  runId: string;
  dir: string;
  valid: boolean;
}

export interface RunDeps {
  root?: string;
  makeId?: () => string;
  now?: () => Date;
  log?: (line: string) => void;
}

/**
 * C3-15 skeleton (the full pipeline is PP2):
 *   1. make the run id and the run folder
 *   2. copy the subject manifest in
 *   3. optionally seed stage folders from a golden fixture (--in), with the new run_id
 *   4. run validate.mjs on the folder
 *   5. write orch/run.json (what was done, for evidence)
 * Throws when validation fails, so the CLI exits 1.
 */
export async function run(options: RunOptions, deps: RunDeps = {}): Promise<RunResult> {
  const root = deps.root ?? repoRoot();
  const log = deps.log ?? ((line: string) => console.log(line));
  const now = deps.now ?? (() => new Date());

  if (options.stages && !options.in) {
    throw new Error('--stages needs --in (the folder to copy the stages from)');
  }

  // 2a. find the subject manifest before making anything, so a bad path leaves no folder behind
  const manifest = pickSubjectManifest(options, root);

  // 1. run id + folder
  const { runId, dir } = resolveRunFolder(options.out, root, deps.makeId);
  createRunFolder(dir);
  log(`[orch] run ${runId}`);
  log(`  folder ${displayPath(dir, root)}`);

  // 2b. copy the subject manifest (byte for byte; it has no run_id)
  fs.copyFileSync(manifest, path.join(dir, 'subject-manifest.json'));
  log(`  subject manifest from ${displayPath(manifest, root)}`);

  // 3. seed from --in
  let seed: SeedResult | undefined;
  const stages = options.stages ?? ['c1', 'c2'];
  if (options.in) {
    seed = seedFromInput(options.in, dir, stages, runId);
    log(`  seeded from ${displayPath(options.in, root)}: ${seed.copied.join(', ')}`);
    if (seed.skippedStages.length > 0)
      log(`  not copied (later stages make them): ${seed.skippedStages.join(', ')}`);
    log(`  run_id set to ${runId} in ${seed.runIdRewritten.length} file(s)`);
  }
  if (options.srs || options.subjectRoot) {
    log('  --srs / --subject-root recorded only; running c1..c4 is PP2');
  }

  // 4. validate
  const check = validateRunFolder(dir);
  for (const line of check.output.split('\n')) if (line.trim()) log('  ' + line);

  // 5. record
  const record = {
    tool: `@j26/orchestrator ${ORCH_VERSION}`,
    run_id: runId,
    created_at: now().toISOString(),
    subject_manifest: displayPath(manifest, root),
    seeded_from: options.in ? displayPath(options.in, root) : null,
    stages_copied: seed ? seed.copied.filter((n) => /^c[1-4]$/.test(n)) : [],
    other_files_copied: seed ? seed.copied.filter((n) => !/^c[1-4]$/.test(n)) : [],
    run_id_rewritten: seed ? seed.runIdRewritten : [],
    pending_pp2: {
      srs: options.srs ? displayPath(options.srs, root) : null,
      subject_root: options.subjectRoot ? displayPath(options.subjectRoot, root) : null,
    },
    validate: { ok: check.ok },
  };
  fs.mkdirSync(path.join(dir, 'orch'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'orch', 'run.json'), JSON.stringify(record, null, 2) + '\n');

  if (!check.ok) {
    throw new Error(
      `run folder ${displayPath(dir, root)} failed validate.mjs (see the FAIL lines above)`,
    );
  }
  log(
    `[orch] ${runId} ready. Next: pnpm c3 run --in ${displayPath(dir, root)} --out ${displayPath(dir, root)}`,
  );
  return { runId, dir, valid: check.ok };
}

function pickSubjectManifest(options: RunOptions, root: string): string {
  const fromIn = options.in ? path.join(options.in, 'subject-manifest.json') : undefined;
  const file =
    options.subjectManifest ??
    (fromIn && fs.existsSync(fromIn) ? fromIn : defaultSubjectManifest(root));
  if (!fs.existsSync(file)) throw new Error(`subject manifest ${file} does not exist`);
  return file;
}
