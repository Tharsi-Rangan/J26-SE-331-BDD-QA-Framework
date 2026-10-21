import path from 'node:path';
import { parseArgs } from 'node:util';

/** Options every component CLI accepts (docs/INTEGRATION_RULES.md section 4). */
export interface RunOptions {
  /** Golden fixture or earlier run folder to seed the new run from (PP1). */
  in?: string;
  /** Run folder. Its name must be a run id. Left out: runs/<new RUN-ID>. */
  out?: string;
  /** Subject manifest to copy in. Left out: the one in --in, else fixtures/subjects/subject-manifest.json. */
  subjectManifest?: string;
  /** Stage folders to copy from --in (default c1,c2: the inputs C3 needs). */
  stages?: string[];
  /** Recorded only; the full pipeline that uses them is PP2. */
  srs?: string;
  subjectRoot?: string;
}

export const USAGE =
  'Usage: orch run [--in <golden or run folder>] [--out runs/<RUN-ID>] ' +
  '[--subject-manifest <file>] [--stages c1,c2] [--srs <file>] [--subject-root <path>]';

/**
 * Parse `orch run ...`. Every option is optional.
 * Throws an Error with a readable message when the command line is wrong.
 */
export function parseRunArgs(argv: string[], baseDir = callerDir()): RunOptions {
  const { positionals, values } = parseArgs({
    args: argv,
    allowPositionals: true,
    options: {
      in: { type: 'string' },
      out: { type: 'string' },
      'subject-manifest': { type: 'string' },
      stages: { type: 'string' },
      srs: { type: 'string' },
      'subject-root': { type: 'string' },
    },
  });
  if (positionals[0] !== 'run') {
    throw new Error(USAGE);
  }
  const abs = (p?: string) => (p === undefined ? undefined : path.resolve(baseDir, p));
  return {
    in: abs(values.in),
    out: abs(values.out),
    subjectManifest: abs(values['subject-manifest']),
    stages: values.stages === undefined ? undefined : parseStages(values.stages),
    srs: abs(values.srs),
    subjectRoot: abs(values['subject-root']),
  };
}

export const STAGES = ['c1', 'c2', 'c3', 'c4'] as const;

/** "c1,c2" -> ['c1', 'c2']. Only c1..c4 are allowed. */
export function parseStages(text: string): string[] {
  const list = text
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  for (const s of list) {
    if (!(STAGES as readonly string[]).includes(s)) {
      throw new Error(`--stages: unknown stage "${s}" (use ${STAGES.join(', ')})`);
    }
  }
  return [...new Set(list)];
}

/**
 * Folder the user ran the command from. pnpm runs scripts inside the package folder,
 * but sets INIT_CWD to the original folder, so relative paths work from the repo root.
 */
export function callerDir(): string {
  return process.env.INIT_CWD ?? process.cwd();
}
