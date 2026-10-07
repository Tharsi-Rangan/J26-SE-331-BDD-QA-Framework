import path from 'node:path';
import { parseArgs } from 'node:util';

/** Options every component CLI accepts (docs/INTEGRATION_RULES.md section 4). */
export interface RunOptions {
  in?: string;
  out: string;
  srs?: string;
  subjectRoot?: string;
}

/**
 * Parse `c2 run --in runs/<RUN-ID> --out runs/<RUN-ID>`.
 * Throws an Error with a readable message when the command line is wrong.
 */
export function parseRunArgs(argv: string[], baseDir = callerDir()): RunOptions {
  const { positionals, values } = parseArgs({
    args: argv,
    allowPositionals: true,
    options: {
      in: { type: 'string' },
      out: { type: 'string' },
      srs: { type: 'string' },
      'subject-root': { type: 'string' },
    },
  });
  if (positionals[0] !== 'run') {
    throw new Error('Usage: c2 run --in runs/<RUN-ID> --out runs/<RUN-ID>');
  }
  if (!values.out) {
    throw new Error('Missing --out <run folder>');
  }
  const abs = (p?: string) => (p === undefined ? undefined : path.resolve(baseDir, p));
  return {
    in: abs(values.in),
    out: path.resolve(baseDir, values.out),
    srs: abs(values.srs),
    subjectRoot: abs(values['subject-root']),
  };
}

/**
 * Folder the user ran the command from. pnpm runs scripts inside the package folder,
 * but sets INIT_CWD to the original folder, so relative paths work from the repo root.
 */
export function callerDir(): string {
  return process.env.INIT_CWD ?? process.cwd();
}
