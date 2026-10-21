// C3-15 orchestrator skeleton: run folder + run_id, subject manifest, validate.
// The full pipeline (calling c1..c4 one after another) is PP2.
import { spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { STAGES } from './args.js';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));

/** Repo root: packages/orchestrator/src (or dist) -> three folders up. */
export function repoRoot(): string {
  return path.resolve(here, '..', '..', '..');
}

/** Default subject manifest for real runs (owned by C3 + C4). */
export function defaultSubjectManifest(root = repoRoot()): string {
  return path.join(root, 'fixtures', 'subjects', 'subject-manifest.json');
}

/** The validator every stage uses (packages/contracts/scripts/validate.mjs). */
export function validateScript(): string {
  return require.resolve('@j26/contracts/scripts/validate.mjs');
}

/** The run id pattern, read from the frozen contract so the two never drift apart. */
export function runIdPattern(): RegExp {
  const file = require.resolve('@j26/contracts/schemas/common.schema.json');
  const schema = JSON.parse(fs.readFileSync(file, 'utf8'));
  return new RegExp(schema.$defs.runId.pattern);
}

/**
 * New run id: RUN-<yyyymmdd>-<hhmmss>-<4 random [a-z0-9]>, local time.
 * `now` and `random` are parameters so tests get a fixed id.
 */
export function newRunId(now = new Date(), random: (n: number) => Buffer = randomBytes): string {
  const p = (n: number, w = 2) => String(n).padStart(w, '0');
  const date = `${p(now.getFullYear(), 4)}${p(now.getMonth() + 1)}${p(now.getDate())}`;
  const time = `${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}`;
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  const tail = [...random(4)].map((b) => chars[b % chars.length]).join('');
  return `RUN-${date}-${time}-${tail}`;
}

/**
 * Where the run goes and which run id it gets.
 * - no --out: runs/<new id> under the repo root
 * - --out given: its folder name must already be a run id (rule: one run_id per run folder)
 */
export function resolveRunFolder(
  out: string | undefined,
  root = repoRoot(),
  makeId: () => string = () => newRunId(),
): { runId: string; dir: string } {
  const pattern = runIdPattern();
  if (out === undefined) {
    const runId = makeId();
    return { runId, dir: path.join(root, 'runs', runId) };
  }
  const name = path.basename(out);
  if (!pattern.test(name)) {
    throw new Error(
      `--out folder name "${name}" is not a run id. Use a name like ${makeId()}, ` +
        'or leave --out out and a new id is made for you.',
    );
  }
  return { runId: name, dir: out };
}

/** A run folder must be new (or empty), so one folder never mixes two runs. */
export function createRunFolder(dir: string): void {
  if (fs.existsSync(dir) && fs.readdirSync(dir).length > 0) {
    throw new Error(`run folder ${dir} already exists and is not empty; use a new run id`);
  }
  fs.mkdirSync(dir, { recursive: true });
}

/** Never copied from --in: tool folders and the orchestrator's own log. */
const SKIP = new Set(['node_modules', '.git', 'orch', 'subject-manifest.json']);

export interface SeedResult {
  /** Top-level entries copied, e.g. ["c1", "c2", "subject-src", "jest.config.js"]. */
  copied: string[];
  /** Stage folders in --in that were left out because they were not asked for. */
  skippedStages: string[];
  /** JSON files (relative, with /) whose run_id was set to the new run id. */
  runIdRewritten: string[];
}

/**
 * Copy the asked-for stage folders from --in, plus everything that is not a stage
 * (subject source, Jest/Stryker config). Copied JSON files get the new run_id, so the
 * run folder holds one run_id (INTEGRATION_RULES s3). The --in folder is never changed.
 */
export function seedFromInput(
  inDir: string,
  outDir: string,
  stages: string[],
  runId: string,
): SeedResult {
  if (!fs.existsSync(inDir) || !fs.statSync(inDir).isDirectory()) {
    throw new Error(`--in folder ${inDir} does not exist`);
  }
  const result: SeedResult = { copied: [], skippedStages: [], runIdRewritten: [] };
  for (const name of fs.readdirSync(inDir).sort()) {
    if (SKIP.has(name)) continue;
    const isStage = (STAGES as readonly string[]).includes(name);
    if (isStage && !stages.includes(name)) {
      result.skippedStages.push(name);
      continue;
    }
    fs.cpSync(path.join(inDir, name), path.join(outDir, name), { recursive: true });
    result.copied.push(name);
    if (isStage) {
      for (const rel of jsonFiles(path.join(outDir, name))) {
        const file = path.join(outDir, name, rel);
        if (setRunId(file, runId)) result.runIdRewritten.push(`${name}/${rel}`);
      }
    }
  }
  const missing = stages.filter((s) => !result.copied.includes(s));
  if (missing.length > 0) {
    throw new Error(`--in folder ${inDir} has no ${missing.join(', ')} folder`);
  }
  return result;
}

function jsonFiles(dir: string, prefix = ''): string[] {
  const out: string[] = [];
  for (const e of fs
    .readdirSync(dir, { withFileTypes: true })
    .sort((a, b) => a.name.localeCompare(b.name))) {
    const rel = prefix ? `${prefix}/${e.name}` : e.name;
    if (e.isDirectory()) out.push(...jsonFiles(path.join(dir, e.name), rel));
    else if (e.name.endsWith('.json')) out.push(rel);
  }
  return out;
}

/** Set the top-level run_id of a contract file. Files without run_id are left alone. */
function setRunId(file: string, runId: string): boolean {
  const text = fs.readFileSync(file, 'utf8');
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return false;
  }
  if (!data || typeof data !== 'object' || Array.isArray(data) || !('run_id' in data)) return false;
  (data as { run_id: string }).run_id = runId;
  fs.writeFileSync(file, JSON.stringify(data, null, 2) + '\n');
  return true;
}

/** Run validate.mjs on the run folder. ok = exit code 0. */
export function validateRunFolder(dir: string): { ok: boolean; output: string } {
  const r = spawnSync(process.execPath, [validateScript(), dir], { encoding: 'utf8' });
  return { ok: r.status === 0, output: `${r.stdout ?? ''}${r.stderr ?? ''}`.trim() };
}

/** Path for JSON: relative to the repo root when inside it, always with /. */
export function displayPath(p: string, root = repoRoot()): string {
  const rel = path.relative(root, p);
  const shown = rel && !rel.startsWith('..') && !path.isAbsolute(rel) ? rel : p;
  return shown.split(path.sep).join('/');
}
