import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, test } from 'vitest';
import { parseRunArgs } from '../src/args.js';
import {
  defaultSubjectManifest,
  newRunId,
  repoRoot,
  resolveRunFolder,
  run,
  runIdPattern,
  validateRunFolder,
} from '../src/index.js';

const GOLDEN = path.join(
  repoRoot(),
  'packages',
  'contracts',
  'fixtures',
  'golden',
  'example-registration',
);
const FIXED_ID = 'RUN-20261019-091500-ab12';
const quiet = () => {};

const temps: string[] = [];
function tempDir(): string {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'orch-'));
  temps.push(d);
  return d;
}
afterEach(() => {
  for (const d of temps.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});

const readJson = (f: string) => JSON.parse(fs.readFileSync(f, 'utf8'));

describe('C3-15 run id', () => {
  test('a new run id matches the frozen contract pattern', () => {
    const id = newRunId(new Date(2026, 9, 19, 9, 15, 0), () => Buffer.from([0, 1, 26, 35]));
    expect(id).toBe('RUN-20261019-091500-ab09');
    expect(runIdPattern().test(id)).toBe(true);
    for (let i = 0; i < 20; i++) expect(runIdPattern().test(newRunId())).toBe(true);
  });

  test('no --out: runs/<new id> under the repo root', () => {
    const r = resolveRunFolder(undefined, '/repo', () => FIXED_ID);
    expect(r.runId).toBe(FIXED_ID);
    expect(r.dir).toBe(path.join('/repo', 'runs', FIXED_ID));
  });

  test('--out must be named like a run id', () => {
    expect(resolveRunFolder(path.join('/x', FIXED_ID)).runId).toBe(FIXED_ID);
    expect(resolveRunFolder('/x/RUN-FIXTURE-EX-1').runId).toBe('RUN-FIXTURE-EX-1');
    expect(() => resolveRunFolder('/x/my-run', '/repo', () => FIXED_ID)).toThrow(/not a run id/);
  });
});

describe('C3-15 orch run', () => {
  test('creates the folder, copies the subject manifest, validates, writes orch/run.json', async () => {
    const out = path.join(tempDir(), FIXED_ID);
    const lines: string[] = [];
    const r = await run({ out }, { log: (l) => lines.push(l) });

    expect(r).toEqual({ runId: FIXED_ID, dir: out, valid: true });
    expect(fs.readFileSync(path.join(out, 'subject-manifest.json'))).toEqual(
      fs.readFileSync(defaultSubjectManifest()),
    );
    const rec = readJson(path.join(out, 'orch', 'run.json'));
    expect(rec.run_id).toBe(FIXED_ID);
    expect(rec.subject_manifest).toBe('fixtures/subjects/subject-manifest.json');
    expect(rec.seeded_from).toBeNull();
    expect(rec.validate.ok).toBe(true);
    expect(lines.join('\n')).toContain(
      'subject-manifest.json matches subject-manifest.schema.json',
    );
  });

  test('--in golden: copies c1 + c2 + subject source, not c3/c4; one run_id in the folder', async () => {
    const out = path.join(tempDir(), FIXED_ID);
    await run({ in: GOLDEN, out }, { log: quiet });

    for (const f of [
      'c1/validated_requirements.json',
      'c2/scenario_metadata.json',
      'c2/features/REQ-EX-001.feature',
    ]) {
      expect(fs.existsSync(path.join(out, f)), f).toBe(true);
    }
    expect(fs.existsSync(path.join(out, 'subject-src', 'src', 'registration.js'))).toBe(true);
    expect(fs.existsSync(path.join(out, 'c3'))).toBe(false);
    expect(fs.existsSync(path.join(out, 'c4'))).toBe(false);

    expect(readJson(path.join(out, 'c1', 'validated_requirements.json')).run_id).toBe(FIXED_ID);
    expect(readJson(path.join(out, 'c2', 'scenario_metadata.json')).run_id).toBe(FIXED_ID);
    // the golden manifest comes with --in (its source.repo_path points at subject-src)
    expect(readJson(path.join(out, 'subject-manifest.json')).subjects[0].subject_id).toBe(
      'SUB-EX-1',
    );

    const rec = readJson(path.join(out, 'orch', 'run.json'));
    expect(rec.stages_copied).toEqual(['c1', 'c2']);
    expect(rec.run_id_rewritten).toEqual([
      'c1/validated_requirements.json',
      'c2/scenario_metadata.json',
    ]);
    expect(rec.validate.ok).toBe(true);

    // the golden fixture itself is untouched
    expect(readJson(path.join(GOLDEN, 'c1', 'validated_requirements.json')).run_id).toBe(
      'RUN-FIXTURE-EX-1',
    );
  });

  test('--stages c1,c2,c3,c4 copies every stage and the whole folder still validates', async () => {
    const out = path.join(tempDir(), FIXED_ID);
    await run({ in: GOLDEN, out, stages: ['c1', 'c2', 'c3', 'c4'] }, { log: quiet });
    expect(readJson(path.join(out, 'c3', 'test_manifest.json')).run_id).toBe(FIXED_ID);
    expect(readJson(path.join(out, 'c4', 'adequacy_report.json')).run_id).toBe(FIXED_ID);
    expect(validateRunFolder(out).ok).toBe(true);
  });

  test('a folder that is not empty is never reused', async () => {
    const out = path.join(tempDir(), FIXED_ID);
    fs.mkdirSync(out);
    fs.writeFileSync(path.join(out, 'old.txt'), 'x');
    await expect(run({ out }, { log: quiet })).rejects.toThrow(/not empty/);
  });

  test('an invalid subject manifest fails validation: orch run throws, run.json says ok=false', async () => {
    const dir = tempDir();
    const bad = path.join(dir, 'bad-manifest.json');
    fs.writeFileSync(
      bad,
      JSON.stringify({
        contract: 'shared.subject-manifest',
        schema_version: '1.0.0',
        subjects: [],
      }),
    );
    const out = path.join(dir, FIXED_ID);
    await expect(run({ out, subjectManifest: bad }, { log: quiet })).rejects.toThrow(
      /failed validate\.mjs/,
    );
    expect(readJson(path.join(out, 'orch', 'run.json')).validate.ok).toBe(false);
  });

  test('a missing subject manifest or a missing stage stops with a clear message', async () => {
    const dir = tempDir();
    await expect(
      run(
        { out: path.join(dir, FIXED_ID), subjectManifest: path.join(dir, 'nope.json') },
        { log: quiet },
      ),
    ).rejects.toThrow(/does not exist/);
    expect(fs.existsSync(path.join(dir, FIXED_ID))).toBe(false);

    const onlyC1 = path.join(dir, 'only-c1');
    fs.cpSync(path.join(GOLDEN, 'c1'), path.join(onlyC1, 'c1'), { recursive: true });
    await expect(
      run({ in: onlyC1, out: path.join(dir, 'RUN-20261019-091501-cd34') }, { log: quiet }),
    ).rejects.toThrow(/has no c2 folder/);
  });

  test('--stages without --in is refused', async () => {
    await expect(run({ stages: ['c1'] }, { log: quiet })).rejects.toThrow(/--stages needs --in/);
  });

  test('CLI options: --stages is checked, --subject-manifest is resolved', () => {
    const base = path.resolve('repo-root');
    const o = parseRunArgs(['run', '--stages', 'c1, c2', '--subject-manifest', 'm.json'], base);
    expect(o.stages).toEqual(['c1', 'c2']);
    expect(o.subjectManifest).toBe(path.join(base, 'm.json'));
    expect(o.out).toBeUndefined();
    expect(() => parseRunArgs(['run', '--stages', 'c5'])).toThrow(/unknown stage "c5"/);
  });
});
